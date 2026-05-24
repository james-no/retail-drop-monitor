"""
Twilio SMS alert — texts your iPhone directly.

Setup (free account works fine for personal use):
  1. Sign up at https://www.twilio.com (free trial gives you ~$15 credit)
  2. Get a free Twilio phone number
  3. Set in .env:
       TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxx
       TWILIO_AUTH_TOKEN=your_auth_token
       TWILIO_FROM_NUMBER=+12065550100    (your Twilio number)
       TWILIO_TO_NUMBER=+13605550100      (your real iPhone number)

Free trial note: Twilio free accounts can only text verified numbers.
Verify your iPhone number in the Twilio console under "Verified Caller IDs".
"""

import os

try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False


def send_alert(result) -> bool:
    """Sends an SMS to your phone. Returns True on success."""
    if not TWILIO_AVAILABLE:
        print("  [SMS] Skipped — twilio package not installed (pip install twilio)")
        return False

    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_num = os.getenv("TWILIO_FROM_NUMBER")
    to_num = os.getenv("TWILIO_TO_NUMBER")

    if not all([sid, token, from_num, to_num]):
        print("  [SMS] Skipped — Twilio credentials not fully set in .env")
        return False

    price_str = f"${result.price:.2f}" if result.price else "check price"
    body = (
        f"🚨 DROP ALERT\n"
        f"{result.retailer}: {result.product_name}\n"
        f"Price: {price_str}\n"
        f"{result.url}"
    )

    try:
        client = TwilioClient(sid, token)
        message = client.messages.create(body=body, from_=from_num, to=to_num)
        print(f"  [SMS] ✅ Sent (SID: {message.sid})")
        return True
    except Exception as e:
        print(f"  [SMS] ❌ Failed: {e}")
        return False
