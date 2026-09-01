"""Indeed job board: Cloudflare-gated JSON blob pages, no login, no pagination.

Single sort=date search page polled every run (see INDEED.md); job keys get
a follow-up /viewjob?jk= fetch for the full description.
"""

from boards.base import JobBoard
from boards.indeed import scraper
from config import (
    CHROME_DEBUG_PORT,
    HEADLESS,
    INDEED_ENABLED,
    INDEED_PROFILE_DIR,
    KILL_CHROME_ON_START,
)
from core import blocklist, db, telegram
from core.browser import (
    cdp_url_for,
    install_cdp_default_context_patch,
    launch_cdp_chrome,
    stop_chrome,
)
import signal

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
        run_id = db.start_run(self.name)

        # Same Chrome/CDP model as the other boards: we launch it so the
        # session is live-attachable on the debug port; the spider connects
        # to it. The persistent profile keeps the Cloudflare clearance
        # cookie (a plain-curl session gets a 403 Security Check).
        chrome = launch_cdp_chrome(
            INDEED_PROFILE_DIR, CHROME_DEBUG_PORT, headless=HEADLESS,
            clean_locks=KILL_CHROME_ON_START,
        )

        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(300)

        try:
            result = scraper.scrape(self.selectors, cdp_url=cdp_url_for(CHROME_DEBUG_PORT))

            new_count = result["new_count"]
            blocked_names = result["blocked_names"]

            if blocked_names:
                print(
                    f"[indeed] Filtered out {len(blocked_names)} blocked-company"
                    f" job(s): {', '.join(sorted(set(blocked_names)))}"
                )
            print(f"[indeed] Saved {new_count} new job(s)")

            db.finish_run(run_id, "ok", jobs_found=new_count)
            return new_count

        except TimeoutException:
            print("[indeed] Run timed out after 5 minutes.")
            db.finish_run(run_id, "timeout")
            telegram.notify_failure(
                "Indeed board timed out",
                "The spider hung for more than 5 minutes and was killed."
            )
            return 0
        except Exception as e:
            db.finish_run(run_id, "error", error=str(e))
            telegram.notify_failure("Indeed board failed", str(e))
            print(f"[indeed] Run failed: {e}")
            return 0
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
            stop_chrome(chrome)
