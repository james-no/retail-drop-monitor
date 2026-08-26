#!/bin/bash
LOG=/Users/jamesno/Documents/retail-drop-monitor/launchd_debug.log
echo "--- Launch attempt $(date) ---" >> "$LOG"
echo "PATH: $PATH" >> "$LOG"

export PATH=/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin

PYTHON=/Users/jamesno/Documents/retail-drop-monitor/venv/bin/python3
echo "Python binary: $PYTHON" >> "$LOG"
echo "Python exists: $(test -f $PYTHON && echo yes || echo no)" >> "$LOG"
echo "Python version: $($PYTHON --version 2>&1)" >> "$LOG"

cd /Users/jamesno/Documents/retail-drop-monitor
echo "Testing imports..." >> "$LOG"
$PYTHON -c "import retailers; import alerts" >> "$LOG" 2>&1
echo "Import exit code: $?" >> "$LOG"

echo "Starting monitor..." >> "$LOG"
exec $PYTHON /Users/jamesno/Documents/retail-drop-monitor/monitor.py >> "$LOG" 2>&1
