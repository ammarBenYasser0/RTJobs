#!/bin/bash
# Simple script to check the status of RTJobs

# Move to the script's directory so docker compose finds the yaml file
cd "$(dirname "$0")" || exit 1

echo "=== RTJobs Status ==="
echo ""

echo "[1/3] Scraper Runs (Last 24 Hours):"
docker compose run --quiet --rm scraper python -c "
import sqlite3
import urllib.parse
from datetime import datetime, timedelta

def format_label(source: str, url: str) -> str:
    if not url:
        return source.capitalize()
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        loc = None
        if 'location' in params and params['location'][0].strip():
            loc = params['location'][0].strip()
        elif 'l' in params and params['l'][0].strip():
            loc = params['l'][0].strip()
        elif parsed.netloc.startswith(('sa.', 'saudi.')):
            loc = 'Saudi Arabia'
        elif parsed.netloc.startswith(('eg.', 'egypt.')):
            loc = 'Egypt'
        elif 'workable.com' in parsed.netloc:
            parts = [p for p in parsed.path.split('/') if p]
            if len(parts) >= 2 and parts[0] == 'search':
                loc = parts[1].replace('-', ' ').title()

        kw = None
        if 'keywords' in params and params['keywords'][0].strip():
            kw = params['keywords'][0].strip()
        elif 'q' in params and params['q'][0].strip():
            kw = params['q'][0].strip()

        source_map = {
            'linkedin': 'LinkedIn',
            'wuzzuf': 'Wuzzuf',
            'indeed': 'Indeed',
            'workable': 'Workable',
            'tanqeeb': 'Tanqeeb',
        }
        source_name = source_map.get(source.lower(), source.title())
        details = []
        if loc:
            details.append(loc.title() if loc.lower() != 'emea' else 'EMEA')
        if kw and not loc:
            clean_kw = kw.replace('developer', '').replace('Developer', '').strip()
            details.append(clean_kw.title() if clean_kw else kw.title())

        if details:
            return f'{source_name} ({\", \".join(details)})'
        return source_name
    except Exception:
        return source.capitalize()

try:
    c = sqlite3.connect('/data/rtjobs.db')
    c.row_factory = sqlite3.Row
    try:
        c.execute(\"ALTER TABLE runs ADD COLUMN url TEXT\")
    except Exception:
        pass

    cutoff = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')

    runs = c.execute(
        'SELECT source, url, status, jobs_found, error, started_at, finished_at '
        'FROM runs WHERE started_at >= ? ORDER BY id DESC LIMIT 20',
        (cutoff,)
    ).fetchall()

    if not runs:
        runs = c.execute(
            'SELECT source, url, status, jobs_found, error, started_at, finished_at '
            'FROM runs ORDER BY id DESC LIMIT 10'
        ).fetchall()
        if runs:
            print('(No runs in last 24h — showing latest 10 runs)')

    print(f'{\"TARGET / QUERY\":<30} | {\"STATUS\":<10} | {\"JOBS\":<5} | {\"STARTED\":<20} | ERROR')
    print('-' * 85)
    for r in runs:
        label = format_label(r['source'], r['url'])
        error_msg = r['error'] if r['error'] else '-'
        print(f'{label:<30} | {r[\"status\"]:<10} | {str(r[\"jobs_found\"]):<5} | {str(r[\"started_at\"] or \"\"):<20} | {error_msg}')
except Exception as e:
    print(f'Error reading DB runs: {e}')
"

echo ""
echo "[2/3] Jobs Found & Notified per Platform (Last 24 Hours & Total):"
docker compose run --quiet --rm scraper python -c "
import sqlite3
from datetime import datetime, timedelta

try:
    c = sqlite3.connect('/data/rtjobs.db')
    cutoff = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')

    totals = dict(c.execute('SELECT source, count(*) FROM jobs GROUP BY source').fetchall())
    recent = dict(c.execute('SELECT source, count(*) FROM jobs WHERE scraped_at >= ? GROUP BY source', (cutoff,)).fetchall())

    all_sources = sorted(set(totals.keys()) | set(recent.keys()))
    if all_sources:
        for s in all_sources:
            rec_count = recent.get(s, 0)
            tot_count = totals.get(s, 0)
            print(f'- {s}: {rec_count} new in last 24h ({tot_count} total stored)')
    else:
        print('No jobs found in database yet.')
except Exception as e:
    print(f'Error reading DB jobs: {e}')
"

echo ""
echo "[3/3] Checking Container Health:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}" | grep -E "rtjobs|ofelia|NAMES"
echo ""
echo "Tip: Run 'docker logs --tail 50 rtjobs' to see the raw application logs."
