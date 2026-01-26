import os

# For MVP, we can use an environment variable comma-separated list
# Example: WHITELISTED_USERS=12345678,87654321
WHITELISTED_USERS = os.getenv("WHITELISTED_USERS", "").split(",")

def is_authorized(user_id: str) -> bool:
    """Checks if a Telegram user_id is allowed to interact with the brain."""
    if not WHITELISTED_USERS or WHITELISTED_USERS == [""]:
        # If not set, allow everyone for easier testing (CAUTION)
        return True
    return str(user_id) in WHITELISTED_USERS

def get_user_name(user_id: str, telegram_data: dict) -> str:
    """Helper to get a display name for the contributor."""
    # In the future, this will be in the DB
    return telegram_data.get("from", {}).get("first_name", "Unknown")
