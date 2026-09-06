"""Workable job spider.

Workable embeds its job search results inside a window.jobBoard script tag
as initialState["api/v1/jobs"]["data"]["jobs"].
We fetch the search page via an AsyncStealthySession (with solve_cloudflare=True
defensively) and extract the JSON directly.

Single search URL per query, NO pagination, and NO detail-page fetching
needed because the full job description and requirements HTML are embedded
directly in the search page state.
"""

import json
import re
from datetime import datetime

from scrapling import Selector
from scrapling.fetchers import AsyncStealthySession
from scrapling.spiders import Request, Response, Spider

from core import blocklist, db, markup, telegram
from core.browser import patch_no_load_wait

_STATE_MARKER = re.compile(r"initialState\s*:\s*")


def _dig(obj, *keys):
    """Safely walk nested dicts; returns None when any level is missing."""
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _extract_initial_state(html: str) -> dict:
    """Locate `initialState:` in the HTML and balance-brace extract the JSON."""
    m = _STATE_MARKER.search(html or "")
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
        print("[workable] Unbalanced JSON blob — marker found, brace never closed.")
        return {}

    try:
        return json.loads(html[start : k + 1])
    except (ValueError, TypeError) as e:
        print(f"[workable] Could not parse embedded initialState JSON: {e}")
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


def _parse_created(iso_str: str) -> str:
    """Parse ISO-8601 UTC string to local 'YYYY-MM-DD HH:MM'."""
    if not iso_str:
        return datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M")


def _extract_jobs(html: str, seen_ids: set) -> tuple[list, int, bool]:
    """Parse the Workable search-page job state.

    Returns (new_jobs, seen_count, blob_missing). `blob_missing` is True
    when the initialState JSON or api/v1/jobs path was completely absent.
    """
    state = _extract_initial_state(html)
    if not state:
        return [], 0, True

    jobs_data = _dig(state, "api/v1/jobs", "data", "jobs")
    if not isinstance(jobs_data, list):
        return [], 0, True

    jobs: list[dict] = []
    seen = 0
    for item in jobs_data:
        if not isinstance(item, dict):
            continue
        key = item.get("id")
        if not key:
            continue
        if str(key) in seen_ids:
            seen += 1
            continue

        company_obj = item.get("company") or {}
        company = company_obj.get("title", "") if isinstance(company_obj, dict) else ""

        loc_obj = item.get("location") or {}
        city = loc_obj.get("city") if isinstance(loc_obj, dict) else ""
        country = loc_obj.get("countryName") if isinstance(loc_obj, dict) else ""
        location_parts = list(filter(None, [city, country]))
        location = ", ".join(location_parts) if location_parts else ""

        desc_raw = item.get("description") or ""
        desc_clean = _strip_html(desc_raw)

        extra: dict = {
            "workplace": item.get("workplace"),
            "location": location,
            "employment_type": item.get("employmentType"),
        }
        req_raw = item.get("requirementsSection")
        if req_raw:
            extra["requirements_html"] = req_raw
        if desc_raw:
            extra["description_html"] = desc_raw

        jobs.append(
            {
                "source": "workable",
                "external_id": str(key),
                "title": _clean(item.get("title") or ""),
                "company": _clean(company),
                "posted_at": _parse_created(item.get("created")),
                "description": desc_clean,
                "link": (item.get("url") or "").strip(),
                "extra": extra,
                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
        )

    return jobs, seen, False


class WorkableJobSpider(Spider):
    name = "workable_job_spider"

    def __init__(
        self,
        selectors: dict,
        cdp_url: str,
        url: str,
        seen_ids: set | None = None,
        *args,
        **kwargs,
    ):
        self.sel = selectors  # unused stub, kept for JobBoard parity
        self.cdp_url = cdp_url
        self.url = url
        self.seen_ids = seen_ids if seen_ids is not None else db.load_seen_ids("workable")

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
        yield Request(
            self.url,
            callback=self.parse,
            sid="stealth",
            page_action=self.scan_search_page,
        )

    async def scan_search_page(self, page):
        self._page_jobs = []

        try:
            await page.wait_for_timeout(2000)
            html = await page.content()
        except Exception as e:
            print(f"[workable] Could not read search page: {e}")
            return

        jobs, seen, blob_missing = _extract_jobs(html, self.seen_ids)
        self._page_jobs = jobs
        for job in jobs:
            self.seen_ids.add(job["external_id"])

        print(
            f"[workable] {len(jobs)} new, {seen} already seen"
            f" ({blob_missing and 'blob MISSING' or 'blob ok'})"
        )

        if blob_missing:
            markup.save_snapshot("workable", "blob_missing", html)

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
            sent = telegram.notify_jobs(db.get_unnotified("workable"))
            if sent:
                print(f"[workable] Notified {sent} job(s)")


def scrape(
    selectors: dict, cdp_url: str, url: str, seen_ids: set | None = None
) -> dict:
    """Run the spider and return results including incremental counts."""
    spider = WorkableJobSpider(
        selectors=selectors, cdp_url=cdp_url, url=url, seen_ids=seen_ids
    )
    result = spider.start()
    items = list(result.items)
    print(
        f"[workable] {len(items)} item(s) scraped in {result.stats.elapsed_seconds:.1f}s"
    )
    return {
        "items": items,
        "new_count": spider._new_count,
        "blocked_names": spider._blocked_names,
    }
