# Monitor Commands

## First-time setup (run once)

```bash
cd ~/Documents/retail-drop-monitor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env   # paste your Discord webhook URL, then Ctrl+X → Y → Enter to save
```

---

## Every time you start the monitor

```bash
cd ~/Documents/retail-drop-monitor
source venv/bin/activate
python monitor.py
```

## Release mode — use this on drop days (Sept 16 for tins/ETB, Oct 2 for bundle)

```bash
cd ~/Documents/retail-drop-monitor
source venv/bin/activate
python monitor.py --release-mode
```

## Test that your Discord alert is working

```bash
python monitor.py --test-alerts
```

---

## Stop the monitor

```
Ctrl+C
```

---

## Auto-start on login (set it and forget it)

```bash
cp ~/Documents/retail-drop-monitor/com.jamesno.retaildropmonitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jamesno.retaildropmonitor.plist
launchctl start com.jamesno.retaildropmonitor
```

## Check if auto-start is running

```bash
launchctl list | grep retaildropmonitor
# You want a PID number in the first column — that means it's alive
```

## Watch the log (if using auto-start)

```bash
tail -f ~/Documents/retail-drop-monitor/monitor.log
```

## Stop and remove auto-start

```bash
launchctl stop com.jamesno.retaildropmonitor
launchctl unload ~/Library/LaunchAgents/com.jamesno.retaildropmonitor.plist
```
