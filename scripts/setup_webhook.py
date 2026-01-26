import requests
import os
from dotenv import load_dotenv

load_dotenv()

def setup_webhook():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    
    # This should be your public URL (e.g. from Coolify)
    base_url = input("Enter your public App URL (e.g. https://brain.mujagent.cz): ").strip()
    if not base_url.startswith("http"):
        print("Invalid URL")
        return

    # Auto-append endpoint if not present
    if "/api/v1/telegram/webhook" not in base_url:
        webhook_url = f"{base_url.rstrip('/')}/api/v1/telegram/webhook"
    else:
        webhook_url = base_url
    
    url = f"https://api.telegram.org/bot{token}/setWebhook"
    payload = {
        "url": webhook_url,
        "secret_token": secret
    }
    
    print(f"Setting webhook to: {webhook_url}...")
    response = requests.post(url, json=payload)
    print(response.json())

if __name__ == "__main__":
    setup_webhook()
