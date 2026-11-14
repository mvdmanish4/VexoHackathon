#!/bin/sh
# Runs the Helen server and restarts it if it stops (for example after the band was lost).
#   ./run.sh 46        (your band number)
cd "$(dirname "$0")"
mkdir -p logs
while true; do
    .venv/bin/python -m helen.main "$@" 2>&1 | tee -a logs/taps.log
    echo "$(date +%H:%M:%S) server stopped, starting again in 2 s (Ctrl+C twice to quit)" | tee -a logs/taps.log
    sleep 2
done
