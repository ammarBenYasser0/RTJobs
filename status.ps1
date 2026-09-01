param()

# Move to the script's directory so docker compose finds the yaml file
Set-Location -Path $PSScriptRoot

Write-Host "=== RTJobs Status ===" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/3] Scraper Runs (Last 24 Hours):" -ForegroundColor Yellow

$script1 = @'
import sqlite3
from datetime import datetime, timedelta

try:
    c = sqlite3.connect('/data/rtjobs.db')
    c.row_factory = sqlite3.Row
    try:
        c.execute("ALTER TABLE runs ADD COLUMN url TEXT")
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

    print(f'{"SOURCE":<10} | {"STATUS":<10} | {"JOBS":<5} | {"STARTED":<20} | {"LINK / QUERY":<45} | ERROR')
    print("-" * 115)
    for r in runs:
        url_str = r['url'] or '-'
        if len(url_str) > 45:
            url_str = url_str[:42] + '...'
        error_msg = r['error'] if r['error'] else '-'
        print(f'{r["source"]:<10} | {r["status"]:<10} | {str(r["jobs_found"]):<5} | {str(r["started_at"] or ""):<20} | {url_str:<45} | {error_msg}')
except Exception as e:
    print(f'Error reading DB runs: {e}')
'@

$script1 | docker compose run -T --quiet --rm scraper python

Write-Host ""
Write-Host "[2/3] Jobs Found & Notified per Platform (Last 24 Hours & Total):" -ForegroundColor Yellow

$script2 = @'
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
'@

$script2 | docker compose run -T --quiet --rm scraper python

Write-Host ""
Write-Host "[3/3] Checking Container Health:" -ForegroundColor Yellow
docker ps --format "table {{.Names}}`t{{.Status}}`t{{.RunningFor}}" | Select-String -Pattern "rtjobs|ofelia|NAMES"
Write-Host ""
Write-Host "Tip: Run 'docker logs --tail 50 rtjobs' to see the raw application logs." -ForegroundColor Green

