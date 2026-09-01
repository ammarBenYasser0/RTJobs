"""LinkedIn job spider built on scrapling's Spider framework.

Structure verified against the scrapling docs (spiders/sessions.html and
fetching/stealthy.html): configure_sessions + manager.add, requests routed
with sid="stealth", and per-request page_action callbacks.
"""

import asyncio
import random
import re
from datetime import datetime, timedelta

from scrapling import Selector
from scrapling.fetchers import AsyncStealthySession
from scrapling.spiders import Request, Response, Spider

from core import blocklist, db, markup, telegram
from core.browser import patch_no_load_wait

_MAX_START = 75
_PAGE_SIZE = 25
_DETAIL_TIMEOUT = 8_000

_TIME_DELTAS = {
    "minute": lambda v: timedelta(minutes=v),
    "hour": lambda v: timedelta(hours=v),
    "day": lambda v: timedelta(days=v),
    "week": lambda v: timedelta(weeks=v),
    "month": lambda v: timedelta(days=v * 30),
}


def _parse_linkedin_time(time_str: str) -> str:
    if not time_str:
        return datetime.now().strftime("%Y-%m-%d %H:%M")
    match = re.search(r"(\d+)\s+(minute|hour|day|week|month)", time_str)
    if not match:
        return datetime.now().strftime("%Y-%m-%d %H:%M")
    value, unit = int(match.group(1)), match.group(2)
    return (datetime.now() - _TIME_DELTAS[unit](value)).strftime("%Y-%m-%d %H:%M")


def _text(sel: Selector, css: str, separator: str = "") -> str:
    el = sel.css(css).first
    if not el:
        return ""
    text = el.get_all_text(separator=separator) if separator else el.get_all_text()
    return (text or "").strip()


class LinkedInJobSpider(Spider):
    name = "linkedin_job_spider"

    def __init__(self, selectors: dict, cdp_url: str, url: str, seen_ids: set | None = None, *args, **kwargs):
        self.sel = selectors
        self.cdp_url = cdp_url
        self.url = url
        self.seen_ids = seen_ids if seen_ids is not None else db.load_seen_ids("linkedin")

        self._page_jobs: list[dict] = []
        self._repeat_found: bool = False
        self._login_redirect: bool = False
        self._new_count: int = 0
        self._blocked_names: list[str] = []

        super().__init__(*args, **kwargs)

    def configure_sessions(self, manager):
        manager.add(
            "stealth",
            AsyncStealthySession(
                cdp_url=self.cdp_url,
                disable_resources=True,
                timeout=15_000,
                page_setup=patch_no_load_wait,
            ),
        )

    async def start_requests(self):
        yield Request(
            self.url,
            callback=self.parse,
            sid="stealth",
            page_action=self.deep_scan_page,
        )

    async def deep_scan_page(self, page):
        self._page_jobs = []
        found_at_least_one_duplicate = False

        try:
            await page.wait_for_selector(
                self.sel["search"]["job_card"], timeout=10_000
            )

            pane = page.locator(self.sel["search"]["results_list"]).first
            if await pane.count() > 0:
                for _ in range(3):
                    await pane.evaluate("el => el.scrollTop += 1500")
                    await asyncio.sleep(0.3)
        except Exception as e:
            print(f"[warn] Card list wait: {e}")
            return

        cards = await page.locator(self.sel["search"]["job_card"]).all()

        jobs_to_scrape_now = []
        for card in cards:
            job_id = await card.get_attribute(self.sel["search"]["job_id_attr"])
            if not job_id:
                continue

            if str(job_id) in self.seen_ids:
                found_at_least_one_duplicate = True
            else:
                jobs_to_scrape_now.append((card, job_id))

        print(
            f"[info] Found {len(jobs_to_scrape_now)} new jobs and"
            f" {len(cards) - len(jobs_to_scrape_now)} old jobs on this page."
        )

        for card, job_id in jobs_to_scrape_now:
            job = await self._scrape_card(card, job_id)
            if job:
                self._page_jobs.append(job)
                self.seen_ids.add(str(job_id))

        if found_at_least_one_duplicate:
            print("[stop] Duplicate detected on this page — no next page.")
            self._repeat_found = True

        if not jobs_to_scrape_now and len(cards) > 0:
            self._repeat_found = True

        # Suspicious empty page or login redirect -> keep markup for debugging
        if (not jobs_to_scrape_now and len(cards) == 0) or self._login_redirect:
            html = await page.content()
            kind = "search_redirect" if self._login_redirect else "search_empty"
            markup.save_snapshot("linkedin", kind, html)

    async def _scrape_card(self, card, job_id: str) -> dict | None:
        try:
            title_el = card.locator(
                "a.job-card-container__link strong, a.job-card-list__title strong, .job-card-list__title strong"
            ).first
            if await title_el.count() > 0:
                title = (await title_el.text_content()).strip()
            else:
                raw_text = await card.inner_text()
                lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
                title = lines[0] if lines else ""

            comp_el = card.locator(
                ".job-card-container__primary-description, .job-card-container__company-name, .artdeco-entity-lockup__subtitle"
            ).first
            company = (await comp_el.text_content()).strip() if await comp_el.count() > 0 else ""

            if not title:
                return None

            print(f"  [ok] {title[:45]} ({company[:20]})")
            return {
                "source": "linkedin",
                "external_id": str(job_id),
                "title": title,
                "company": company,
                "posted_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "description": title,
                "link": f"https://www.linkedin.com/jobs/view/{job_id}/",
                "extra": {},
                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
        except Exception as e:
            print(f"[error] Job {job_id}: {e}")
            return None

    async def parse(self, response: Response):
        for job in self._page_jobs:
            yield job

        # Persist + notify this page's jobs immediately so earlier pages
        # are not lost if a later page hangs.
        for job in self._page_jobs:
            if blocklist.is_blocked(job["source"], job.get("company") or ""):
                db.mark_seen(job["source"], job["external_id"])
                self._blocked_names.append(job.get("company") or "?")
                continue
            db.save_job(job)
            self._new_count += 1

        if self._page_jobs:
            sent = telegram.notify_jobs(db.get_unnotified("linkedin"))
            if sent:
                print(f"[linkedin] Notified {sent} job(s)")

        if self._repeat_found or self._login_redirect:
            return

        match = re.search(r"start=(\d+)", response.url)
        start_val = int(match.group(1)) if match else 0
        next_start = start_val + _PAGE_SIZE

        if next_start >= _MAX_START:
            return

        next_url = (
            re.sub(r"start=\d+", f"start={next_start}", response.url)
            if "start=" in response.url
            else response.url + f"&start={next_start}"
        )
        print(f"[page] \u2192 page {next_start // _PAGE_SIZE + 1}")
        yield Request(
            next_url,
            callback=self.parse,
            sid="stealth",
            page_action=self.deep_scan_page,
        )


def scrape(selectors: dict, cdp_url: str, url: str, seen_ids: set | None = None) -> dict:
    """Run the spider. Returns {'items': [...], 'login_redirect': bool, 'new_count': int, 'blocked_names': list}."""
    spider = LinkedInJobSpider(selectors=selectors, cdp_url=cdp_url, url=url, seen_ids=seen_ids)
    result = spider.start()
    items = list(result.items)
    print(
        f"[spider] {len(items)} item(s) scraped in {result.stats.elapsed_seconds:.1f}s"
    )
    return {
        "items": items,
        "login_redirect": spider._login_redirect,
        "new_count": spider._new_count,
        "blocked_names": spider._blocked_names,
    }
