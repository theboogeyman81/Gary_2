"""
Central config for Gary.

Loads environment variables from .env once, makes them available
as module-level constants. Anywhere in Gary, you can do:

    from config.settings import HA_URL, HA_TOKEN, ENTITY_ID
"""

import os
from dotenv import load_dotenv


# Load .env file from the project root.
load_dotenv()


# Home Assistant
HA_URL = os.getenv("HA_URL", "")
HA_TOKEN = os.getenv("HA_TOKEN", "")
ENTITY_ID = os.getenv("ENTITY_ID", "")


def validate() -> None:
    """Raise an error if required config is missing."""
    missing = []
    if not HA_URL:
        missing.append("HA_URL")
    if not HA_TOKEN:
        missing.append("HA_TOKEN")
    if not ENTITY_ID:
        missing.append("ENTITY_ID")
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")