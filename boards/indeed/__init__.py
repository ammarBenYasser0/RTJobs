"""Indeed job board: Cloudflare-gated JSON blob pages, no login, no pagination.

Search pages polled every run; stores direct viewjob link + card snippet.
"""

import signal

from boards.base import JobBoard
from boards.indeed import scraper
from config import (
    CHROME_DEBUG_PORT,
    HEADLESS,
    INDEED_ENABLED,
    INDEED_PROFILE_DIR,
    INDEED_SEARCH_URLS,
    KILL_CHROME_ON_START,
)
from core import db, telegram
from core.browser import (
    cdp_url_for,
    install_cdp_default_context_patch,
    launch_cdp_chrome,
    stop_chrome,
)

class TimeoutException(BaseException):
    pass

def _timeout_handler(signum, frame):
    raise TimeoutException("Board run timed out")

install_cdp_default_context_patch()


class IndeedBoard(JobBoard):
    name = "indeed"
    requires_login = False
    enabled = INDEED_ENABLED

    def run(self) -> int:
        # Same Chrome/CDP model as the other boards: we launch it so the
        # session is live-attachable on the debug port; the spider connects
        # to it. The persistent profile keeps the Cloudflare clearance
        # cookie (a plain-curl session gets a 403 Security Check).
        chrome = launch_cdp_chrome(
            INDEED_PROFILE_DIR, CHROME_DEBUG_PORT, headless=HEADLESS,
            clean_locks=KILL_CHROME_ON_START,
        )

        total_new = 0
        seen_ids = db.load_seen_ids(self.name)

        try:
            for url in INDEED_SEARCH_URLS:
                print(f"[indeed] Starting scrape for URL: {url}")
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
                            f"[indeed] Filtered out {len(blocked_names)} blocked-company"
                            f" job(s): {', '.join(sorted(set(blocked_names)))}"
                        )
                    print(f"[indeed] Saved {new_count} new job(s) for this URL")
                    db.finish_run(run_id, "ok", jobs_found=new_count)
                except TimeoutException:
                    print(f"[indeed] URL timed out after 5 minutes: {url}")
                    db.finish_run(run_id, "timeout", error="5m timeout")
                    telegram.notify_failure(
                        "Indeed URL timed out",
                        f"Search URL timed out after 5 minutes:\n{url}",
                    )
                except Exception as e:
                    print(f"[indeed] Error scraping URL {url}: {e}")
                    db.finish_run(run_id, "error", error=str(e))
                    telegram.notify_failure("Indeed URL failed", f"URL: {url}\nError: {e}")
                finally:
                    if hasattr(signal, "SIGALRM"):
                        signal.alarm(0)
                        if old_handler:
                            signal.signal(signal.SIGALRM, old_handler)

            return total_new

        except Exception as e:
            telegram.notify_failure("Indeed board failed", str(e))
            print(f"[indeed] Run failed: {e}")
            return 0
        finally:
            stop_chrome(chrome)
