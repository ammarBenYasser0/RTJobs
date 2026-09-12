# RTJobs

Automated job-board scraper that monitors **LinkedIn**, **Wuzzuf**, **Indeed**, **Workable**, and **Tanqeeb** on a schedule, saves every new posting to a local SQLite database, and sends instant Telegram notifications — new jobs on one channel, failures/alerts on another.

Runs in Docker with a real headful Chrome browser (virtual display via Xvfb), scheduled every 15 minutes via [ofelia](https://github.com/mcuadros/ofelia). You can attach to the live browser session over CDP (`localhost:9222`) to watch scrapes in real time or manually solve LinkedIn 2FA challenges.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Telegram Setup](#2-telegram-setup)
3. [Clone & Configure](#3-clone--configure)
4. [Environment Variables](#4-environment-variables)
5. [Docker Setup & First Run](#5-docker-setup--first-run)
6. [Daily Operations](#6-daily-operations)
7. [Live Browser Access (CDP)](#7-live-browser-access-cdp)
8. [LinkedIn Login Behavior](#8-linkedin-login-behavior)
9. [Blocking Companies](#9-blocking-companies)
10. [Customizing Search Queries](#10-customizing-search-queries)
11. [When a Site Changes (Markup Resilience)](#11-when-a-site-changes-markup-resilience)
12. [Adding a New Board](#12-adding-a-new-board)
13. [Running Locally (Without Docker)](#13-running-locally-without-docker)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Prerequisites

Before starting, make sure you have:

- **Docker Desktop** installed and running
  - [Download for Windows](https://docs.docker.com/desktop/install/windows-install/)
  - [Download for macOS](https://docs.docker.com/desktop/install/mac-install/)
  - [Download for Linux](https://docs.docker.com/desktop/install/linux/)
- **A Telegram account** (for receiving job notifications)
- **A LinkedIn account** (email + password) for LinkedIn scraping
- **Git** (to clone this repository)

> **Windows users:** Enable **"Start Docker Desktop when you sign in"** in Docker Desktop → Settings → General so the scraper auto-resumes after reboots.

---

## 2. Telegram Setup

RTJobs sends notifications to two separate Telegram channels/groups:

- **Jobs channel** — one message per new job posting found
- **Alerts channel** — login failures, checkpoints, crashes, and errors

You need a **Telegram bot** and the **chat IDs** of both channels.

### Step 1: Create a Telegram Bot

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot` and follow the prompts:
   - Give it a display name (e.g. `RTJobs Notifier`)
   - Give it a username (e.g. `rtjobs_notify_bot`)
3. BotFather will reply with your **bot token** — it looks like:

   ```
   7123456789:AAH1bCdE2fGhIjKlMnOpQrStUvWxYz
   ```
4. **Save this token** — you'll need it as `TELEGRAM_TOKEN` in your `.env`.

### Step 2: Create Your Channels or Groups

You need two channels (or groups, or even two separate chats with the bot):

1. **Jobs channel** — where new job postings will be sent.
2. **Alerts channel** — where failure notifications and errors go.

> **Tip:** You can use the same chat for both if you prefer, but separating them keeps job notifications clean and uncluttered.

**To create a channel:**

1. In Telegram, tap the hamburger menu → **New Channel**.
2. Name it (e.g. `RTJobs - New Listings`), set it as Public or Private.
3. **Add your bot as an admin** of the channel (Channel Settings → Administrators → Add Admin → search for your bot's username).

Repeat for the alerts channel.

### Step 3: Get Chat IDs

The easiest way:

1. **For channels:** Forward a message from each channel to **@userinfobot** — it will reply with the chat ID (a negative number like `-1001234567890`).
2. **For groups:** Add **@userinfobot** to the group, then type any message — it will reply with the chat ID.
3. **For a direct chat with the bot:** Send any message to your bot, then visit:

   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```

   Look for `"chat":{"id": ...}` in the JSON response.

**Save both chat IDs** — you'll need them as `TELEGRAM_CHAT_ID` (jobs) and `TELEGRAM_TEST_ID` (alerts).

---

## 3. Clone & Configure

```bash
git clone https://github.com/ammarBenYasser0/RTJobs
cd RTJobs
```

Create a `.env` file in the project root:

```bash
# On Linux/macOS:
cp .env.example .env    # if an example file exists, or:
touch .env

# On Windows (PowerShell):
New-Item .env
```

Then fill it in — see the next section.

---

## 4. Environment Variables

Edit `.env` with a text editor. Here's a complete reference:

```env
# ──────────────────────────────────────────────────────
# REQUIRED — the scraper won't start without these
# ──────────────────────────────────────────────────────

# Telegram bot token (from @BotFather)
TELEGRAM_TOKEN=7123456789:AAH1bCdE2fGhIjKlMnOpQrStUvWxYz

# Chat ID for job notifications
TELEGRAM_CHAT_ID=-1001234567890

# Chat ID for failure/error alerts
TELEGRAM_TEST_ID=-1009876543210

# LinkedIn credentials
LINKEDIN_EMAIL=your.email@example.com
LINKEDIN_PASSWORD=your_password_here

# ──────────────────────────────────────────────────────
# BOARD TOGGLES — enable/disable each scraper
# ──────────────────────────────────────────────────────

LINKEDIN_ENABLED=true
WUZZUF_ENABLED=true
INDEED_ENABLED=true
WORKABLE_ENABLED=false
TANQEEB_ENABLED=false

# ──────────────────────────────────────────────────────
# SEARCH URLS — what queries each board runs
# (plain URL string OR a JSON array for multiple queries)
# ──────────────────────────────────────────────────────

# LinkedIn example (single URL):
LINKEDIN_SEARCH_URLS=https://www.linkedin.com/jobs/search/?keywords=frontend+developer&location=Egypt

# Wuzzuf example (JSON array for multiple queries — MUST be a single line):
WUZZUF_SEARCH_URLS=["https://wuzzuf.net/search/jobs/?q=frontend+developer"]

# Indeed:
INDEED_SEARCH_URLS=["https://eg.indeed.com/jobs?q=frontend+developer", "https://sa.indeed.com/jobs?q=frontend+developer"]

# Workable:
WORKABLE_SEARCH_URLS=["https://apply.workable.com/search/egypt/", "https://apply.workable.com/search/saudi-arabia/"]

# Tanqeeb:
TANQEEB_SEARCH_URLS=["https://egypt.tanqeeb.com/en/jobs/search?q=frontend", "https://saudi.tanqeeb.com/en/jobs/search?q=frontend"]

# ──────────────────────────────────────────────────────
# OPTIONAL — defaults are fine for most setups
# ──────────────────────────────────────────────────────

# Override the failure alert channel (wins over TELEGRAM_TEST_ID):
# TELEGRAM_FAILURE_CHAT_ID=-1009876543210

# Browser settings (Docker overrides these via compose):
# HEADLESS=false
# DATA_DIR=.
# CHROME_DEBUG_PORT=9222
# KILL_CHROME_ON_START=false

# LinkedIn login resilience:
# CHECKPOINT_WAIT_SECONDS=600   # seconds to wait for manual 2FA solve
# MAX_LOGIN_RETRIES=3           # failures before cooldown + profile wipe

# Database:
# MAX_JOBS=10000

# Snapshot pruning:
# MAX_SNAPSHOTS_PER_KIND=20
```

> **⚠️ Important:** Search URL arrays **must be on a single line** in `.env`. Docker's env-file parser splits on newlines and would truncate multi-line values.

> **⚠️ Important:** Never commit `.env` — it contains secrets. It is already in `.gitignore`.

---

## 5. Docker Setup & First Run

### Build and start

```bash
docker compose up -d --build
```

This will:

1. Build the `rtjobs-scraper` image (Python 3.13 + real Chrome + Xvfb).
2. Start the **scraper** container (`rtjobs`) — runs one scrape cycle immediately.
3. Start the **scheduler** container (`ofelia`) — triggers the scraper every 15 minutes automatically.

### Watch the first run

```bash
docker compose logs -f scraper
```

You should see output like:

```
[main] Running board: linkedin
[login] Opening login page (redirects to feed if active)
[login] Session already active.
[linkedin] Scraping page 1...
[linkedin] Found 5 new job(s)
[main] Running board: wuzzuf
...
[main] Done. New jobs this run: 12
```

### Verify Telegram

Check your Telegram jobs channel — you should see job postings arriving as formatted messages.

### Check status anytime

```bash
# Linux/macOS:
./status.sh

# Windows (PowerShell):
.\status.ps1

# Windows (double-click):
status.cmd
```

This shows recent runs, jobs found per platform, and container health.

---

## 6. Daily Operations

### Pause before shutdown/restart

If you're shutting down or restarting your computer, gracefully pause first:

```bash
# Linux/macOS:
./pause.sh

# Windows (PowerShell):
.\pause.ps1

# Windows (double-click):
pause.cmd
```

This sends a graceful stop signal with a 15-second grace period for any active database writes or network requests to finish cleanly.

### Resume after reboot

```bash
# Linux/macOS:
./resume.sh

# Windows (PowerShell):
.\resume.ps1

# Windows (double-click):
resume.cmd
```

### What happens on an abrupt shutdown?

RTJobs is designed to handle unexpected shutdowns safely:

- **No data loss:** Jobs are saved to SQLite and sent to Telegram **incrementally per page**, not at the end of a run. If power cuts mid-scrape, already-found jobs are already persisted.
- **Auto-healing Chrome locks:** Stale `SingletonLock` files from a killed Chrome are automatically cleaned up on the next start (`KILL_CHROME_ON_START=true` in Docker).
- **Scheduler recovery:** If `ofelia` was running with `restart: unless-stopped` and Docker Desktop auto-starts on login, the scheduler will resume automatically after a reboot — no manual intervention needed.

### Auto-start on boot (recommended)

1. Open **Docker Desktop** → Settings → General → enable **"Start Docker Desktop when you sign in"**.
2. The `ofelia` scheduler container has `restart: unless-stopped`, so it will automatically start when Docker starts — as long as you haven't explicitly stopped it with `docker compose stop` or `docker compose down`.

---

## 7. Live Browser Access (CDP)

While a scrape is running, you can watch the real Chrome browser live:

1. Open `http://localhost:9222` in your browser, or use `chrome://inspect` → "Configure" → add `localhost:9222`.
2. You'll see the live browser tab — you can watch, click, type, and interact with it.
3. This is also how you **manually solve LinkedIn 2FA challenges** (see below).

Verify CDP is reachable:

```bash
curl http://localhost:9222/json/version
```

> **Note:** The CDP endpoint is only available while a scrape run is active (Chrome starts and stops with each run).

---

## 8. LinkedIn Login Behavior

| State                 | What happens                                                                                                                                                    |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Session active**    | Scrapes directly (no login needed)                                                                                                                              |
| **Login page**        | Auto-fills credentials with human-like typing, submits                                                                                                          |
| **Checkpoint / 2FA**  | Sends an alert to your failure channel, pauses for up to `CHECKPOINT_WAIT_SECONDS` (default: 10 min) — connect via CDP (`localhost:9222`) and solve it manually |
| **Repeated failures** | Escalating cooldowns (5m → 15m → 30m), then profile wipe for a fresh login                                                                                      |

To manually clear a stuck cooldown:

```bash
python main.py --reset-login
```

---

## 9. Blocking Companies

Edit `markup/blocked_companies.json` (bind-mounted — no rebuild needed):

```json
{
  "*":        ["Blocks across all sources"],
  "linkedin": ["Spammy Recruiter Inc"],
  "wuzzuf":   ["Another Company"]
}
```

- Matching is **case-insensitive substring** — `"alignerr"` also blocks `"Alignerr Inc."`.
- Blocked jobs are marked as seen (never re-scraped) but never saved or notified.
- The file is bind-mounted into Docker, so edits take effect on the next run without rebuilding.

---

## 10. Customizing Search Queries

Each board supports one or more search URLs. Set them in `.env` as a **plain URL** or a **JSON array** (must be a single line):

```env
# Single query:
LINKEDIN_SEARCH_URLS=https://www.linkedin.com/jobs/search/?keywords=react&location=Egypt

# Multiple queries (JSON array, single line):
INDEED_SEARCH_URLS=["https://eg.indeed.com/jobs?q=frontend", "https://sa.indeed.com/jobs?q=react"]
```

Each query runs in sequence with its own 5-minute timeout, reusing the board's single Chrome instance and persistent profile.

After changing `.env`, restart the scraper:

```bash
docker compose down && docker compose up -d
```

---

## 11. When a Site Changes (Markup Resilience)

- Every CSS selector lives in `markup/<site>/selectors.json` — fix selectors there, no code changes needed.
- Snapshots are saved automatically for login failures, checkpoints, empty search pages, and login-redirects — sanitized and pruned to 20 per kind under `markup/<site>/snapshots/`.
- Reference HTML files in `markup/<site>/` are optimized captures of real markup — use them to re-derive selectors offline.

---

## 12. Adding a New Board

1. Create `boards/<site>/scraper.py` — subclass `JobBoard` from `boards/base.py` with a `name` and `run()` method that returns the number of new jobs saved.
2. Create `markup/<site>/selectors.json` with the CSS selectors for the site.
3. Register in the `BOARDS` list in `main.py`; keep `enabled = False` until ready.

Job dict shape everywhere:

```python
{
    "source": "sitename",
    "external_id": "unique-id",
    "title": "Job Title",
    "company": "Company Name",
    "posted_at": "2026-01-15 14:30",
    "description": "Job description text...",
    "link": "https://...",
    "extra": {"career_level": "...", "salary": "..."},
    "scraped_at": "2026-01-15 15:00"
}
```

---

## 13. Running Locally (Without Docker)

If you prefer running without Docker (visible Chrome window on your desktop):

```bash
# Create virtual environment (first time only)
python -m venv .venv

# Activate it
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
scrapling install              # installs browser dependencies (first time)

# Run
python main.py
```

A Chrome window will open, log into LinkedIn (or reuse the saved session), scrape all enabled boards, and post new jobs to Telegram.

---

## 14. Troubleshooting

| Symptom                                        | Fix                                                                                                                                                                       |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `curl localhost:9222` fails                    | CDP is only up during active scrape runs. Wait for the next scheduled run, or trigger one manually: `docker start rtjobs`                                                 |
| No Telegram notifications                      | Verify `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`. Make sure the bot is an **admin** of the channel.                                                               |
| No failure alerts                              | Check `TELEGRAM_TEST_ID` / `TELEGRAM_FAILURE_CHAT_ID` — the bot must be able to post there too.                                                                           |
| Stuck "blocked" login state                    | `python main.py --reset-login` or run inside the container: `docker compose run --rm scraper python main.py --reset-login`                                                |
| Chrome won't start in container                | Profile lock from a crash. `KILL_CHROME_ON_START=true` handles it automatically. If stuck: `docker compose down && docker compose up -d`                                  |
| `Page.goto: Timeout ... waiting until "load"`  | Already handled — navigations wait for `domcontentloaded` instead of `load` (some sites have hanging trackers). If it recurs, check `core/browser.py`.                    |
| Login keeps failing after a site change        | Check the newest snapshot in `markup/linkedin/snapshots/login_failure/` and update `markup/linkedin/selectors.json`.                                                      |
| Containers stopped after reboot                | Enable Docker Desktop auto-start (Settings → General → "Start Docker Desktop when you sign in"). The `ofelia` scheduler has `restart: unless-stopped` so it auto-resumes. |
| Docker build fails with `invalid file request` | Stale Chrome sockets in profile dirs. Already handled by `.dockerignore` excluding `*profile/`. If it recurs: delete local `*profile/` directories and rebuild.           |

---

## Architecture

```
main.py                  orchestrator; BOARDS list; --reset-login
config.py                ALL env config (single source of truth)
core/
  db.py                  SQLite: jobs, seen_ids, runs, login_state
  telegram.py            job notifications (jobs channel) / failure alerts
  markup.py              sanitized HTML snapshots → markup/<site>/snapshots/<kind>/
  login_state.py         LinkedIn retry counter + escalating cooldown
  browser.py             Chrome lifecycle, CDP, load-event patch
  human.py               random human-like delays
  blocklist.py           company blocklist filtering
boards/
  base.py                JobBoard ABC + load_board_selectors()
  linkedin/              login.py (state machine) + scraper.py (Spider)
  wuzzuf/                scraper.py (Spider, solve_cloudflare=True)
  indeed/                scraper.py (Spider, solve_cloudflare=True)
  workable/              scraper.py (Spider, solve_cloudflare=True) — JSON blobs
  tanqeeb/               scraper.py (Spider) — DOM rendered cards
markup/<site>/
  selectors.json         ALL CSS selectors per site (edit here, not in code)
  snapshots/<kind>/      dated HTML snapshots (auto-pruned to 20/kind)
  blocked_companies.json company blocklist (bind-mounted, live-editable)
status.sh / .ps1 / .cmd   CLI dashboard: recent runs, today's jobs, health
pause.sh / .ps1 / .cmd    graceful stop before shutdown/restart
resume.sh / .ps1 / .cmd   resume scheduler and scraper
```
