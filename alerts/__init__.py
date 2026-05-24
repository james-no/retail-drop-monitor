from . import discord_webhook, mac_notification, twilio_sms, sound


def fire_all(result) -> None:
    """Fire every alert channel when a product is in stock."""
    print(f"\n🚨 ALERT FIRING — {result.retailer}: {result.product_name}")
    discord_webhook.send_alert(result)
    mac_notification.send_alert(result)
    twilio_sms.send_alert(result)
    sound.send_alert(result)
