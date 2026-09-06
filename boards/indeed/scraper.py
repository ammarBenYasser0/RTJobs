"""Indeed job spider.

Indeed is Cloudflare-gated (403 Security Check for plain curl — see
INDEED.md) and embeds all its data as JSON inside <script> tags, so we fetch
the search page through a stealth browser session with solve_cloudflare=True
and parse the blobs — no CSS selectors needed.

Data source:
Search page: `window.mosaic.providerData["mosaic-provider-jobcards"]`
-> metaData.mosaicProviderJobCardsModel.results — one dict per job card
(jobkey, displayTitle, company, formattedLocation, extractedSalary,
jobTypes, pubDate in unix ms, snippet, viewJobLink).

Single search URL per query, sort=date, NO pagination (pagination is login-gated),
and NO detail-page fetching (stores direct viewjob link + card snippet).
"""

import json
import re
from datetime import datetime

from scrapling import Selector
from scrapling.fetchers import AsyncStealthySession
from scrapling.spiders import Request, Response, Spider

from core import blocklist, db, markup, telegram
from core.browser import patch_no_load_wait

_BASE_URL = "https://eg.indeed.com"

_CARDS_MARKER = re.compile(
    r'window\.mosaic\.providerData\[\'?"?mosaic-provider-jobcards\'?"?\]\s*=\s*'
)


def _dig(obj, *keys):
    """Safely walk nested dicts; returns None when any level is missing."""
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _extract_balanced_json(html: str, marker_re: re.Pattern) -> dict:
    """Locate `marker` in the HTML and parse the following `{...}` object.

    Marker regex must end right before the opening brace (it usually matches
    `... = `). Brace balancing is string-aware (handles braces inside quoted
    strings and escaped quotes). Returns {} when absent/unparseable.
    """
    m = marker_re.search(html or "")
    if not m:
        return {}
    start = html.find("{", m.end())
    if start == -1:
        return {}

    depth = 0
    in_str = False
    esc = False
    k = start
    while k < len(html):
        ch = html[k]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
        k += 1

    if depth != 0:
        print("[indeed] Unbalanced JSON blob — marker found, brace never closed.")
        return {}

    try:
        return json.loads(html[start:k + 1])
    except (ValueError, TypeError) as e:
        print(f"[indeed] Could not parse embedded JSON: {e}")
        return {}


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


def _parse_pubdate(value) -> str:
    """Unix ms -> local 'YYYY-MM-DD HH:MM' (container TZ = Africa/Cairo)."""
    try:
        return datetime.fromtimestamp(int(value) / 1000).strftime(
            "%Y-%m-%d %H:%M"
        )
    except (ValueError, TypeError):
        return datetime.now().strftime("%Y-%m-%d %H:%M")


def _extract_jobs(html: str, seen_ids: set, base_url: str = _BASE_URL) -> tuple[list, int, bool]:
    """Parse the search-page job cards blob.

    Returns (new_jobs, seen_count, blob_missing). `blob_missing` is True
    when the cards JSON was absent (CF challenge page, empty page, redesign).
    """
    data = _extract_balanced_json(html, _CARDS_MARKER)
    if not data:
        return [], 0, True

    results = _dig(data, "metaData", "mosaicProviderJobCardsModel", "results")
    if not isinstance(results, list):
        return [], 0, True

    jobs: list[dict] = []
    seen = 0
    for item in results:
        if not isinstance(item, dict):
            continue
        key = item.get("jobkey")
        if not key:
            continue
        if str(key) in seen_ids:
            seen += 1
            continue

        company = item.get("company") or ""
        if not isinstance(company, str):
            company = (company or {}).get("name", "") if isinstance(company, dict) else ""

        snippet = _strip_html(item.get("snippet"))
        extra: dict = {
            "location": _clean(
                item.get("formattedLocation") or item.get("jobLocationCity") or ""
            ),
        }
        if snippet:
            extra["snippet"] = snippet

        salary = item.get("extractedSalary")
        if isinstance(salary, dict) and (
            salary.get("min") is not None or salary.get("max") is not None
        ):
            extra["salary"] = {
                "min": salary.get("min"),
                "max": salary.get("max"),
                "type": salary.get("type"),
                "currency": salary.get("currency"),
            }

        job_types = [t for t in (item.get("jobTypes") or []) if isinstance(t, str)]
        if job_types:
            extra["job_types"] = job_types
        if item.get("sponsored"):
            extra["sponsored"] = True

        jobs.append(
            {
                "source": "indeed",
                "external_id": str(key),
                "title": _clean(item.get("displayTitle") or item.get("normTitle") or ""),
                "company": _clean(company),
                # createDate is the precise ms epoch; pubDate is normalized
                # to midnight — prefer createDate.
                "posted_at": _parse_pubdate(
                    item.get("createDate") or item.get("pubDate")
                ),
                "description": snippet,
                "link": f"{base_url}/viewjob?jk={key}",
                "extra": extra,
                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
        )

    return jobs, seen, False


class IndeedJobSpider(Spider):
    name = "indeed_job_spider"

    def __init__(self, selectors: dict, cdp_url: str, url: str, seen_ids: set | None = None, *args, **kwargs):
        self.sel = selectors  # unused — data comes from JSON blobs, kept for parity
        self.cdp_url = cdp_url
        self.url = url
        self.seen_ids = seen_ids if seen_ids is not None else db.load_seen_ids("indeed")

        self._page_jobs: list[dict] = []
        self._new_count: int = 0
        self._blocked_names: list[str] = []

        super().__init__(*args, **kwargs)

    def configure_sessions(self, manager):
        manager.add(
            "stealth",
            AsyncStealthySession(
                cdp_url=self.cdp_url,
                solve_cloudflare=True,
                timeout=120_000,
                page_setup=patch_no_load_wait,
            ),
        )

    async def start_requests(self):
        from urllib.parse import urlsplit
        clean_url = re.sub(r"[?&]vjk=[^&]+", "", self.url)
        if "?" not in clean_url and "&" in clean_url:
            clean_url = clean_url.replace("&", "?", 1)
        yield Request(
            clean_url,
            callback=self.parse,
            sid="stealth",
            page_action=self.scan_search_page,
        )

    async def scan_search_page(self, page):
        self._page_jobs = []

        try:
            await page.wait_for_timeout(2500)  # let the SSR blobs land
            html = await page.content()
        except Exception as e:
            print(f"[indeed] Could not read search page: {e}")
            return

        if "INDEED_CLOUDFLARE_STATIC_PAGE" in html:
            print("[indeed] Cloudflare challenge page detected.")
            markup.save_snapshot("indeed", "cloudflare_challenge", html)
            return

        from urllib.parse import urlsplit
        page_url = getattr(page, "url", None) or self.url
        parts = urlsplit(page_url)
        base_url = f"{parts.scheme}://{parts.netloc}" if parts.netloc else _BASE_URL

        jobs, seen, blob_missing = _extract_jobs(html, self.seen_ids, base_url=base_url)
        self._page_jobs = jobs
        for job in jobs:
            self.seen_ids.add(job["external_id"])

        print(
            f"[indeed] {len(jobs)} new, {seen} already seen"
            f" ({blob_missing and 'blob MISSING' or 'blob ok'})"
        )
        is_empty_search = "did not match any jobs" in html or "No matching jobs found" in html
        if blob_missing and not jobs and not is_empty_search:
            markup.save_snapshot("indeed", "search_empty", html)

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
            sent = telegram.notify_jobs(db.get_unnotified("indeed"))
            if sent:
                print(f"[indeed] Notified {sent} job(s)")


def scrape(selectors: dict, cdp_url: str, url: str, seen_ids: set | None = None) -> dict:
    """Run the spider and return results including incremental counts."""
    spider = IndeedJobSpider(selectors=selectors, cdp_url=cdp_url, url=url, seen_ids=seen_ids)
    result = spider.start()
    items = list(result.items)
    print(
        f"[indeed] {len(items)} item(s) scraped in {result.stats.elapsed_seconds:.1f}s"
    )
    return {
        "items": items,
        "new_count": spider._new_count,
        "blocked_names": spider._blocked_names,
    }
