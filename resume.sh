#!/bin/bash
# Move to the script's directory so docker compose finds the yaml file
cd "$(dirname "$0")" || exit 1

echo "=== Resuming RTJobs ==="
echo "Starting scheduler and scraper containers..."

docker compose up -d

echo ""
echo "Checking Container Health:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}" | grep -E "rtjobs|ofelia|NAMES"

echo ""
echo "RTJobs has been resumed successfully."
echo "Tip: Run './status.sh' to check recent runs and database status."
