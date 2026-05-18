"""
Bot entry point for trustlyDeal bot.
Loads environment variables from .env and runs the bot.
"""
import os
import sys
import asyncio
from pathlib import Path

# Load .env file if it exists
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if not os.environ.get(key):
                    os.environ[key] = value

# Validate required environment variables
required_vars = ["BOT_TOKEN", "ADMIN_ID", "DEALS_CHANNEL_ID"]
missing = [v for v in required_vars if not os.environ.get(v)]
if missing:
    print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
    print(f"Copy .env.example to .env and fill in your values.")
    sys.exit(1)

# Add the attached_assets directory to path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "attached_assets"))

if __name__ == "__main__":
    # Run the bot file directly
    exec(open(os.path.join(os.path.dirname(__file__), "attached_assets", "bot_1778671181152.py"), encoding="utf-8").read())
