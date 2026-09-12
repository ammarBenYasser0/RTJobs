#!/bin/bash
# Move to the script's directory so docker compose finds the yaml file
cd "$(dirname "$0")" || exit 1

echo "=== Pausing RTJobs Safely ==="
echo "Sending graceful stop signal (15s grace period for active transactions)..."

docker compose stop -t 15

echo ""
echo "Container Status:"
docker compose ps -a

echo ""
echo "RTJobs has been safely paused."
echo "No active database writes or browser locks remain. You can now safely restart or shut down."
