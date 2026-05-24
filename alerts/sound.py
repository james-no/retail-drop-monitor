"""
Sound alarm alert — plays a loud system sound on your Mac.
Uses afplay, which is built into macOS. Zero dependencies.

The alarm plays repeatedly (default: 5 times) so you can't miss it
even if you're across the room.
"""

import subprocess
import time


# macOS system sounds — change ALARM_SOUND to whichever you prefer
SYSTEM_SOUNDS = {
    "glass": "/System/Library/Sounds/Glass.aiff",
    "sosumi": "/System/Library/Sounds/Sosumi.aiff",
    "ping": "/System/Library/Sounds/Ping.aiff",
    "funk": "/System/Library/Sounds/Funk.aiff",
    "hero": "/System/Library/Sounds/Hero.aiff",      # Loudest/most dramatic
    "basso": "/System/Library/Sounds/Basso.aiff",
}

ALARM_SOUND = SYSTEM_SOUNDS["hero"]   # Change this if you want a different sound
ALARM_REPEATS = 5                      # How many times to play it


def send_alert(result) -> bool:
    """Plays the alarm sound N times. Returns True on success."""
    print(f"  [Sound] 🔊 Playing alarm ({ALARM_REPEATS}x)...")
    success = True
    for i in range(ALARM_REPEATS):
        try:
            subprocess.run(
                ["afplay", ALARM_SOUND],
                check=True,
                capture_output=True,
            )
            if i < ALARM_REPEATS - 1:
                time.sleep(0.3)  # Brief pause between plays
        except subprocess.CalledProcessError as e:
            print(f"  [Sound] ❌ Failed on play {i+1}: {e}")
            success = False
            break
    return success
