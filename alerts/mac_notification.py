"""
macOS native notification alert.
Uses osascript — zero dependencies, works out of the box on any Mac.
The notification appears in the top-right corner and stays in Notification Center.
"""

import subprocess


def send_alert(result) -> bool:
    """Sends a native macOS notification. Returns True on success."""
    title = f"🚨 {result.retailer} — IN STOCK"
    subtitle = result.product_name
    body = f"${result.price:.2f}" if result.price else "Tap to open product page"

    script = (
        f'display notification "{body}" '
        f'with title "{title}" '
        f'subtitle "{subtitle}" '
        f'sound name "Glass"'
    )

    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
        )
        print(f"  [Mac Notification] ✅ Sent")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [Mac Notification] ❌ Failed: {e.stderr.decode()}")
        return False
