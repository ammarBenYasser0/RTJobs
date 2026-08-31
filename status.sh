#!/bin/bash
# Simple script to check the status of RTJobs

echo "=== RTJobs Status ==="
echo ""

echo "[1/3] Recent Scraper Runs (Last 5):"
docker compose run --quiet --rm scraper python -c "
import sqlite3
try:
    c = sqlite3.connect('/data/rtjobs.db')
    runs = c.execute('SELECT source, status, jobs_found, error, started_at, finished_at FROM runs ORDER BY id DESC LIMIT 5').fetchall()
    print(f'{'SOURCE':<10} | {'STATUS':<10} | {'JOBS':<5} | {'STARTED':<20} | {'FINISHED':<20} | ERROR')
    print('-' * 95)
    for r in runs:
        error_msg = r[3] if r[3] else '-'
        print(f'{r[0]:<10} | {r[1]:<10} | {str(r[2]):<5} | {str(r[4]):<20} | {str(r[5]):<20} | {error_msg}')
except Exception as e:
    print('Error reading DB. Make sure the container is running and the DB is initialized.')
"

echo ""
echo "[2/3] Total Jobs Found & Notified:"
docker compose run --quiet --rm scraper python -c "
import sqlite3
try:
    c = sqlite3.connect('/data/rtjobs.db')
    jobs = c.execute('SELECT source, count(*) FROM jobs GROUP BY source').fetchall()
    for j in jobs:
        print(f'- {j[0]}: {j[1]} total jobs')
except Exception:
    pass
"

echo ""
echo "[3/3] Checking Container Health:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}" | grep -E "rtjobs|ofelia|NAMES"
echo ""
echo "Tip: Run 'docker logs --tail 50 rtjobs' to see the raw application logs."
