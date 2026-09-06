"""Tanqeeb job spider.

Tanqeeb renders its job search cards in the HTML response under
div.search-job-card. We fetch the search page via an AsyncStealthySession
connected to Chrome over CDP and parse the DOM elements using selectors
loaded from markup/tanqeeb/selectors.json.

Single search URL per query, NO pagination for v1 (sorted by most recent,
search_period=1 limits to past 24 hours), and card description extraction.
"""

import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit

from scrapling import Selector
from scrapling.fetchers import AsyncStealthySession
from scrapling.spiders import Request, Response, Spider

from core import blocklist, db, markup, telegram
from core.browser import patch_no_load_wait

_BASE_URL = "https://egypt.tanqeeb.com"

_TIME_DELTAS = {
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _strip_html(html_text: str) -> str:
    """Convert an HTML fragment (snippet/description) to plain text."""
    if not html_text:
        return ""
    try:
        text = Selector(html_text).get_all_text()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html_text)
    return _clean(text)


def _parse_posted_at(time_str: str) -> str:
    """Parse relative time string like '6 hours ago' to 'YYYY-MM-DD HH:MM'."""
    text = (time_str or "").strip().lower()
    if not text:
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    # Match English relative formats: '6 hours ago', '1 day ago', '30 mins ago'
    match = re.search(r"(\d+)\s*(minute|min|hour|hr|day|week|month)", text)
    if match:
        val, unit_str = int(match.group(1)), match.group(2)
        unit = "minute" if "min" in unit_str else ("hour" if "hr" in unit_str else unit_str)
        delta = _TIME_DELTAS.get(unit, timedelta(hours=1)) * val
        return (datetime.now() - delta).strftime("%Y-%m-%d %H:%M")

    # Arabic relative formats
    if "أمس" in text or "امس" in text or "yesterday" in text:
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    if "ساعتين" in text:
        return (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    if "يومين" in text:
        return (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")

    ar_match = re.search(r"(\d+)\s*(دقيقة|ساعة|ساعات|يوم|ايام|أيام|اسبوع|أسبوع|شهر)", text)
    if ar_match:
        val, unit_ar = int(ar_match.group(1)), ar_match.group(2)
        if "دقيق" in unit_ar:
            delta = timedelta(minutes=val)
        elif "ساع" in unit_ar:
            delta = timedelta(hours=val)
        elif "يوم" in unit_ar or "يام" in unit_ar:
            delta = timedelta(days=val)
        elif "سبوع" in unit_ar:
            delta = timedelta(weeks=val)
        elif "شهر" in unit_ar:
            delta = timedelta(days=30 * val)
        else:
            delta = timedelta(hours=val)
        return (datetime.now() - delta).strftime("%Y-%m-%d %H:%M")

    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _extract_id_from_url(url: str) -> str:
    """Extract numeric job ID from Tanqeeb URL like '/jobs-in-egypt/all/jobs/021214890.html'."""
    m = re.search(r"(\d+)\.html", url or "")
    if m:
        return m.group(1)
    cleaned = (url or "").split("?")[0].rstrip("/").split("/")[-1].replace(".html", "")
    return cleaned or url


def _extract_jobs(
    html: str, selectors: dict, seen_ids: set, base_url: str = _BASE_URL
) -> tuple[list, int, bool]:
    """Parse the search-page job cards using CSS selectors.

    Returns (new_jobs, seen_count, is_empty_state).
    """
    sel = Selector(html)
    search_sel = selectors.get("search", {})
    card_sel = search_sel.get("job_card", "div.search-job-card")
    cards = sel.css(card_sel)

    no_results_marker = search_sel.get("no_results_marker", "div.alert[role='alert']")
    is_empty_state = (
        bool(sel.css(no_results_marker))
        or "Your search didn't return any results" in (html or "")
        or "لم تسفر نتائج بحثك عن أي وظائف" in (html or "")
    )

    if not cards:
        return [], 0, is_empty_state

    jobs: list[dict] = []
    seen = 0

    title_sel = search_sel.get("title_link", "a.search-job-title-link")
    company_sel = search_sel.get("company", "a.search-job-company-link")
    location_sel = search_sel.get("location", ".search-job-company-city")
    meta_sel = search_sel.get("meta_line", ".search-job-meta-line")
    date_sel = search_sel.get("posted_at", ".search-job-date")
    desc_sel = search_sel.get("description", ".job-card-description-alt")

    for card in cards:
        title_nodes = card.css(title_sel)
        if not title_nodes:
            continue
        title = _clean(title_nodes[0].get_all_text())
        href = (title_nodes[0].attrib.get("href") or "").strip()
        if not title or not href:
            continue

        external_id = _extract_id_from_url(href)
        if not external_id:
            continue

        if external_id in seen_ids:
            seen += 1
            continue

        company_nodes = card.css(company_sel)
        company = _clean(company_nodes[0].get_all_text()) if company_nodes else ""

        loc_nodes = card.css(location_sel)
        location = _clean(loc_nodes[0].get_all_text()) if loc_nodes else ""

        meta_nodes = card.css(meta_sel)
        meta_text = _clean(meta_nodes[0].get_all_text()) if meta_nodes else ""

        date_nodes = card.css(date_sel)
        date_text = date_nodes[0].get_all_text().strip() if date_nodes else ""
        posted_at = _parse_posted_at(date_text)

        desc_nodes = card.css(desc_sel)
        desc_raw = desc_nodes[0].get() if desc_nodes else ""
        description = _strip_html(desc_raw)

        # Detect workplace nature (remote, hybrid, on-site)
        combined_text = f"{meta_text} {location}".lower()
        workplace = None
        if "remote" in combined_text or "عن بعد" in combined_text:
            workplace = "remote"
        elif "hybrid" in combined_text or "هجين" in combined_text:
            workplace = "hybrid"
        elif "on_site" in combined_text or "on-site" in combined_text or "موقع" in combined_text:
            workplace = "on_site"

        full_link = urljoin(base_url, href)

        extra: dict = {
            "location": location,
        }
        if workplace:
            extra["workplace"] = workplace
        if desc_raw:
            extra["description_html"] = desc_raw

        jobs.append(
            {
                "source": "tanqeeb",
                "external_id": str(external_id),
                "title": title,
                "company": company,
                "posted_at": posted_at,
                "description": description,
                "link": full_link,
                "extra": extra,
                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
        )

    return jobs, seen, False


class TanqeebJobSpider(Spider):
    name = "tanqeeb_job_spider"

    def __init__(
        self,
        selectors: dict,
        cdp_url: str,
        url: str,
        seen_ids: set | None = None,
        *args,
        **kwargs,
    ):
        self.sel = selectors
        self.cdp_url = cdp_url
        self.url = url
        self.seen_ids = seen_ids if seen_ids is not None else db.load_seen_ids("tanqeeb")

        self._page_jobs: list[dict] = []
        self._new_count: int = 0
        self._blocked_names: list[str] = []

        super().__init__(*args, **kwargs)

    def configure_sessions(self, manager):
        manager.add(
            "stealth",
            AsyncStealthySession(
                cdp_url=self.cdp_url,
                solve_cloudflare=False,
                timeout=120_000,
                page_setup=patch_no_load_wait,
            ),
        )

    async def start_requests(self):
        yield Request(
            self.url,
            callback=self.parse,
            sid="stealth",
            page_action=self.scan_search_page,
        )

    async def scan_search_page(self, page):
        self._page_jobs = []

        try:
            # Wait briefly for DOM/card elements to settle
            card_sel = self.sel.get("search", {}).get("job_card", "div.search-job-card")
            try:
                await page.wait_for_selector(card_sel, timeout=10000)
            except Exception:
                pass

            html = await page.content()
        except Exception as e:
            print(f"[tanqeeb] Could not read search page: {e}")
            return

        page_url = getattr(page, "url", None) or self.url
        parts = urlsplit(page_url)
        base_url = f"{parts.scheme}://{parts.netloc}" if parts.netloc else _BASE_URL

        jobs, seen, is_empty_state = _extract_jobs(
            html, self.sel, self.seen_ids, base_url=base_url
        )
        self._page_jobs = jobs
        for job in jobs:
            self.seen_ids.add(job["external_id"])

        print(
            f"[tanqeeb] {len(jobs)} new, {seen} already seen"
            f" ({is_empty_state and 'empty search' or f'{len(jobs)+seen} cards found'})"
        )

        if not jobs and not is_empty_state:
            markup.save_snapshot("tanqeeb", "search_empty", html)

    async def parse(self, response: Response):
        for job in self._page_jobs:
            if blocklist.is_blocked(job["source"], job.get("company") or ""):
                db.mark_seen(job["source"], job["external_id"])
                self._blocked_names.append(job.get("company") or "?")
                continue
            db.save_job(job)
            self._new_count += 1
            yield job

        if self._page_jobs:
            sent = telegram.notify_jobs(db.get_unnotified("tanqeeb"))
            if sent:
                print(f"[tanqeeb] Notified {sent} job(s)")


def scrape(
    selectors: dict, cdp_url: str, url: str, seen_ids: set | None = None
) -> dict:
    """Run the spider and return results including incremental counts."""
    spider = TanqeebJobSpider(
        selectors=selectors, cdp_url=cdp_url, url=url, seen_ids=seen_ids
    )
    result = spider.start()
    items = list(result.items)
    print(
        f"[tanqeeb] {len(items)} item(s) scraped in {result.stats.elapsed_seconds:.1f}s"
    )
    return {
        "items": items,
        "new_count": spider._new_count,
        "blocked_names": spider._blocked_names,
    }
