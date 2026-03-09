#!/usr/bin/env python3
"""
One-command runner for LinkedIn Easy Apply.
Run from the project root. Uses user_profile.json (or user_profile.example.json if missing).

Usage:
  python run_apply.py                                    # prompts for URL or uses default
  python run_apply.py "https://linkedin.com/jobs/view/4380681259/"
  python run_apply.py --dry-run                          # fill but don't submit
  python run_apply.py --dry-run "https://linkedin.com/jobs/view/4380681259/"
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Run from script directory (project root)
PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# Profile path: user_profile.json if present, else user_profile.example.json
PROFILE_FILE = PROJECT_ROOT / "user_profile.json"
if not PROFILE_FILE.exists():
    PROFILE_FILE = PROJECT_ROOT / "user_profile.example.json"
if not PROFILE_FILE.exists():
    print("Error: No user_profile.json or user_profile.example.json found.", file=sys.stderr)
    sys.exit(1)

# Require LLM API key for form mapping
if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("OPENROUTER_API_KEY"):
    print("Error: Set GEMINI_API_KEY or OPENROUTER_API_KEY in .env", file=sys.stderr)
    print("  cp .env.example .env   then edit .env and add your API key.", file=sys.stderr)
    sys.exit(1)

DEFAULT_EASY_APPLY_URL = "https://www.linkedin.com/jobs/view/4380681259/"


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]

    url = (args[0] if args else "").strip()
    if not url or not url.startswith("http"):
        url = os.environ.get("APPLY_URL", DEFAULT_EASY_APPLY_URL)
        if not args:
            print(f"Using URL: {url}")
            print("(Set APPLY_URL or pass URL as first argument to change.)\n")

    from auto_apply.runner import auto_apply

    state = asyncio.run(auto_apply(
        job_url=url,
        profile_path=str(PROFILE_FILE),
        headless=False,
        dry_run=dry_run,
        site_name="linkedin",
    ))

    sys.exit(0 if state.phase.value == "done" else 1)


if __name__ == "__main__":
    main()
