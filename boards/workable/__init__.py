"""Workable job board: JSON blob pages, no login, no pagination.

Search pages polled every run; stores direct job link + requirements & description.
"""

import signal

from boards.base import JobBoard
from boards.workable import scraper
from config import (
    CHROME_DEBUG_PORT,
    HEADLESS,
    KILL_CHROME_ON_START,
    WORKABLE_ENABLED,
    WORKABLE_PROFILE_DIR,
    WORKABLE_SEARCH_URLS,
)
from core import db, telegram
from core.browser import (
    cdp_url_for,
    install_cdp_default_context_patch,
    launch_cdp_chrome,
    stop_chrome,
)


def _timeout_handler(signum, frame):
    print("[workable] Hard timeout (5m) reached — terminating process to avoid container hang.")
    try:
        from core import telegram

        telegram.notify_failure(
            "Workable run timed out",
            "The Workable scraper exceeded the 5-minute timeout and was forcefully terminated to prevent hanging.",
        )
    except Exception:
        pass
    import os

    os._exit(1)


install_cdp_default_context_patch()


class WorkableBoard(JobBoard):
    name = "workable"
    requires_login = False
    enabled = WORKABLE_ENABLED

    def run(self) -> int:
        chrome = launch_cdp_chrome(
            WORKABLE_PROFILE_DIR,
            CHROME_DEBUG_PORT,
            headless=HEADLESS,
            clean_locks=KILL_CHROME_ON_START,
        )

        total_new = 0
        seen_ids = db.load_seen_ids(self.name)

        try:
            for url in WORKABLE_SEARCH_URLS:
                print(f"[workable] Starting scrape for URL: {url}")
                run_id = db.start_run(self.name, url=url)
                old_handler = None
                if hasattr(signal, "SIGALRM"):
                    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
                    signal.alarm(300)

                try:
                    result = scraper.scrape(
                        self.selectors,
                        cdp_url=cdp_url_for(CHROME_DEBUG_PORT),
                        url=url,
                        seen_ids=seen_ids,
                    )

                    new_count = result["new_count"]
                    blocked_names = result["blocked_names"]
                    total_new += new_count

                    if blocked_names:
                        print(
                            f"[workable] Filtered out {len(blocked_names)} blocked-company"
                            f" job(s): {', '.join(sorted(set(blocked_names)))}"
                        )
                    print(f"[workable] Saved {new_count} new job(s) for this URL")
                    db.finish_run(run_id, "ok", jobs_found=new_count)

                except Exception as e:
                    print(f"[workable] Error scraping URL {url}: {e}")
                    db.finish_run(run_id, "error", error=str(e))
                    telegram.notify_failure("Workable URL failed", f"URL: {url}\nError: {e}")
                finally:
                    if hasattr(signal, "SIGALRM"):
                        signal.alarm(0)
                        if old_handler:
                            signal.signal(signal.SIGALRM, old_handler)

            return total_new

        except Exception as e:
            telegram.notify_failure("Workable board failed", str(e))
            print(f"[workable] Run failed: {e}")
            return 0
        finally:
            stop_chrome(chrome)
