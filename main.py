"""
Bot entry point for trustlyDeal bot.
Loads environment variables from .env and runs the bot.
"""
import os
import sys
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

# Determine project root directory
BASE_DIR = Path(__file__).parent

# Possible locations for the bot source file (in order of priority)
bot_candidates = [
    BASE_DIR / "attached_assets" / "bot_1778671181152.py",
    BASE_DIR / "bot_1778671181152.py",
    BASE_DIR / "bot.py",
]

bot_path = None
for candidate in bot_candidates:
    if candidate.exists():
        bot_path = candidate
        break

if bot_path is None:
    print("ERROR: Bot source file not found!")
    print("Searched in:")
    for c in bot_candidates:
        print(f"  - {c}")
    print("\nMake sure the bot file is in the repository.")
    print("Checklist:")
    print("  1. Run: git add attached_assets/")
    print("  2. Run: git commit -m 'Add bot source files'")
    print("  3. Run: git push")
    sys.exit(1)

# Add the attached_assets directory to path so imports work
sys.path.insert(0, str(BASE_DIR / "attached_assets"))

if __name__ == "__main__":
    print(f"Starting bot from: {bot_path}")
    # Read file with BOM-safe encoding, then exec
    with open(bot_path, encoding="utf-8-sig") as f:
        bot_code = f.read()
    exec_globals = {"__file__": str(bot_path), "__name__": "__main__"}
    exec(bot_code, exec_globals)
