"""
config.py
Single source of truth. All paths and credentials imported from here.
"""

import json
import os

from dotenv import load_dotenv

load_dotenv()


def _parse_url_list(val: str | list | None, *defaults: str | list[str]) -> list[str]:
    """Accept a plain URL string, a JSON list of URLs from env, or variable default URLs.
    Single-string values (existing .env files) are returned as a one-element list.
    """
    raw = (val or "").strip() if isinstance(val, str) else ""
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(u).strip() for u in parsed if str(u).strip()]
            if isinstance(parsed, str) and parsed.strip():
                return [parsed.strip()]
        except (ValueError, TypeError):
            pass
        return [raw]

    results: list[str] = []
    for d in defaults:
        if isinstance(d, (list, tuple)):
            for item in d:
                if str(item).strip():
                    results.append(str(item).strip())
        elif isinstance(d, str) and d.strip():
            results.append(d.strip())
    return results

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
LINKEDIN_PROFILE_DIR = os.path.abspath(
    os.environ.get("LINKEDIN_PROFILE_DIR", "./chromeprofile")
)
DATA_DIR = os.environ.get("DATA_DIR", ".")
MARKUP_DIR = os.environ.get("MARKUP_DIR", os.path.join(DATA_DIR, "markup"))

DB_PATH = os.path.join(DATA_DIR, "rtjobs.db")

# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------
HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"

# Remote debugging port so you can attach to the live headful browser
# (chrome://inspect or any CDP client). Docker maps it to localhost.
CHROME_DEBUG_PORT = int(os.environ.get("CHROME_DEBUG_PORT", "9222"))
CHROME_ARGS = [f"--remote-debugging-port={CHROME_DEBUG_PORT}"]

# Kill stray chrome processes before starting (container-only safety net)
KILL_CHROME_ON_START = os.environ.get("KILL_CHROME_ON_START", "false").lower() == "true"

# ---------------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------------
LINKEDIN_ENABLED = os.environ.get("LINKEDIN_ENABLED", "true").lower() == "true"
LINKEDIN_SEARCH_URLS = _parse_url_list(
    os.environ.get("LINKEDIN_SEARCH_URLS") or os.environ.get("LINKEDIN_SEARCH_URL")
)
# Landing page for login: already-logged-in sessions get redirected to the
# feed; logged-out ones get the credential form directly.
LINKEDIN_LOGIN_URL = "https://www.linkedin.com/login"
LINKEDIN_EMAIL = os.environ.get("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.environ.get("LINKEDIN_PASSWORD", "")

# How long (seconds) to keep the browser open waiting for a manual
# checkpoint/2FA solve via CDP before aborting the run.
CHECKPOINT_WAIT_SECONDS = int(os.environ.get("CHECKPOINT_WAIT_SECONDS", "600"))

# ---------------------------------------------------------------------------
# Wuzzuf
# ---------------------------------------------------------------------------
WUZZUF_ENABLED = os.environ.get("WUZZUF_ENABLED", "true").lower() == "true"
WUZZUF_SEARCH_URLS = _parse_url_list(
    os.environ.get("WUZZUF_SEARCH_URLS") or os.environ.get("WUZZUF_SEARCH_URL")
)
WUZZUF_PROFILE_DIR = os.path.abspath(
    os.environ.get("WUZZUF_PROFILE_DIR", "./wuzzufprofile")
)

# ---------------------------------------------------------------------------
# Indeed
# ---------------------------------------------------------------------------
# Disabled by default until the board is verified live (see INDEED.md).
INDEED_ENABLED = os.environ.get("INDEED_ENABLED", "false").lower() == "true"
INDEED_SEARCH_URLS = _parse_url_list(
    os.environ.get("INDEED_SEARCH_URLS") or os.environ.get("INDEED_SEARCH_URL")
)
INDEED_PROFILE_DIR = os.path.abspath(
    os.environ.get("INDEED_PROFILE_DIR", "./indeedprofile")
)

# ---------------------------------------------------------------------------
# Workable
# ---------------------------------------------------------------------------
WORKABLE_ENABLED = os.environ.get("WORKABLE_ENABLED", "false").lower() == "true"
WORKABLE_SEARCH_URLS = _parse_url_list(
    os.environ.get("WORKABLE_SEARCH_URLS") or os.environ.get("WORKABLE_SEARCH_URL")
)
WORKABLE_PROFILE_DIR = os.path.abspath(
    os.environ.get("WORKABLE_PROFILE_DIR", "./workableprofile")
)

# ---------------------------------------------------------------------------
# Tanqeeb
# ---------------------------------------------------------------------------
TANQEEB_ENABLED = os.environ.get("TANQEEB_ENABLED", "false").lower() == "true"
TANQEEB_SEARCH_URLS = _parse_url_list(
    os.environ.get("TANQEEB_SEARCH_URLS") or os.environ.get("TANQEEB_SEARCH_URL")
)
TANQEEB_PROFILE_DIR = os.path.abspath(
    os.environ.get("TANQEEB_PROFILE_DIR", "./tanqeebprofile")
)

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
TELEGRAM_FAILURE_CHAT_ID = os.environ.get(
    "TELEGRAM_FAILURE_CHAT_ID", os.environ.get("TELEGRAM_TEST_ID", "")
)

# ---------------------------------------------------------------------------
# Login retries / cooldown
# ---------------------------------------------------------------------------
MAX_LOGIN_RETRIES = int(os.environ.get("MAX_LOGIN_RETRIES", "3"))
# Cooldown after the 1st, 2nd, 3rd+ consecutive failure.
LOGIN_COOLDOWN_SECONDS = [5 * 60, 15 * 60, 30 * 60]

# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
MAX_JOBS = int(os.environ.get("MAX_JOBS", "10000"))

# ---------------------------------------------------------------------------
# Markup snapshots
# ---------------------------------------------------------------------------
MAX_SNAPSHOTS_PER_KIND = int(os.environ.get("MAX_SNAPSHOTS_PER_KIND", "20"))
