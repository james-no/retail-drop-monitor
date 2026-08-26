"""
Sound alarm alert — plays a loud system sound on your Mac.
Uses afplay, which is built into macOS. Zero dependencies.

Runs in a background thread so the main monitor loop keeps checking
other products while the alarm is playing.
"""

import subprocess
import threading
import time


SYSTEM_SOUNDS = {
    "glass": "/System/Library/Sounds/Glass.aiff",
    "sosumi": "/System/Library/Sounds/Sosumi.aiff",
    "ping": "/System/Library/Sounds/Ping.aiff",
    "funk": "/System/Library/Sounds/Funk.aiff",
    "hero": "/System/Library/Sounds/Hero.aiff",
    "basso": "/System/Library/Sounds/Basso.aiff",
}

ALARM_SOUND = SYSTEM_SOUNDS["hero"]
ALARM_REPEATS = 5


def _play():
    for i in range(ALARM_REPEATS):
        try:
            subprocess.run(["afplay", ALARM_SOUND], check=True, capture_output=True)
            if i < ALARM_REPEATS - 1:
                time.sleep(0.3)
        except subprocess.CalledProcessError:
            break


def send_alert(result) -> bool:
    """Plays the alarm sound in a background thread so the monitor loop isn't blocked."""
    print(f"  [Sound] 🔊 Playing alarm ({ALARM_REPEATS}x)...")
    threading.Thread(target=_play, daemon=True).start()
    return True
