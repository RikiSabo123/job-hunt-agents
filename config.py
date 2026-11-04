"""Everything you may want to tweak lives here."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE = Path(__file__).parent
# Your CV text. In GitHub Actions it comes from the PROFILE_MD secret, so it never sits in the repo.
_profile_file = BASE / "profile.md"
PROFILE = os.getenv("PROFILE_MD") or (
    _profile_file if _profile_file.exists() else BASE / "profile.example.md"
).read_text(encoding="utf-8")

CRITERIA = {
    "seniority": "junior / entry-level / graduate / 0-2 years of experience",
    "roles": [
        "Full Stack (TypeScript, Node.js, React)",
        "Backend (Node.js, Python, Java, C#)",
        "Frontend (React, Next.js)",
        "AI / ML / MLOps / AI Engineer",
        "QA / Automation",
    ],
    "locations": [
        "Modi'in and surroundings (Modi'in, Modi'in Illit, Shoham, Airport City, Lod)",
        "Jerusalem and surroundings",
        "Center of Israel (Tel Aviv, Petah Tikva, Ramat Gan, Herzliya, Rehovot, Bnei Brak...)",
        "Hybrid or remote anywhere in Israel",
    ],
    "freshness_days": 3,
}

MIN_FIT_SCORE = int(os.getenv("MIN_FIT_SCORE", 7))      # matcher score needed to go on
MAX_CVS_PER_RUN = int(os.getenv("MAX_CVS_PER_RUN", 3))  # keeps cost under control
MAX_BOSS_STEPS = int(os.getenv("MAX_BOSS_STEPS", 40))   # safety limit for the manager loop

# Sending
MY_EMAIL = os.getenv("MY_EMAIL", "")
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() != "false"  # true = save email to outbox/, don't send

OUT_DIR = BASE / "output"
OUTBOX = BASE / "outbox"
OUT_DIR.mkdir(exist_ok=True)
OUTBOX.mkdir(exist_ok=True)
