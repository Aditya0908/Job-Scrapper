#!/usr/bin/env python3
"""
Job Scraper Agent — CLI entry point.

Usage examples:
    # Run with inline JSON
    python main.py --profile '{"role":"Full Stack Engineer","skills":"Python,React","experience_years":3,"location":"Remote/India"}'

    # Run with a JSON file
    python main.py --profile-file profile.json

    # Only scrape specific sites
    python main.py --profile-file profile.json --sites linkedin naukri

    # Show browser (useful for debugging / first-time login)
    python main.py --profile-file profile.json --no-headless

    # Save results to file
    python main.py --profile-file profile.json --output results.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Job Scraper Agent — find relevant jobs across multiple sites",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--profile",
        type=str,
        help="User profile as a JSON string",
    )
    group.add_argument(
        "--profile-file",
        type=str,
        help="Path to a JSON file containing the user profile",
    )
    p.add_argument(
        "--sites",
        nargs="+",
        choices=["linkedin", "indeed", "naukri"],
        default=None,
        help="Sites to scrape (default: all)",
    )
    p.add_argument(
        "--max-per-site",
        type=int,
        default=25,
        help="Maximum results per site (default: 25)",
    )
    p.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="Minimum fit score to show (0-100, default: 0 = show all)",
    )
    p.add_argument(
        "--include-promoted",
        action="store_true",
        help="Include promoted/sponsored listings (excluded by default)",
    )
    p.add_argument(
        "--no-headless",
        action="store_true",
        help="Show the browser window (useful for debugging)",
    )
    p.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Save results to a JSON file",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if args.profile:
        try:
            profile_data = json.loads(args.profile)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in --profile: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        path = Path(args.profile_file)
        if not path.exists():
            print(f"Error: File not found: {path}", file=sys.stderr)
            sys.exit(1)
        profile_data = json.loads(path.read_text())

    from agent import run_agent

    asyncio.run(run_agent(
        profile_data=profile_data,
        sites=args.sites,
        max_per_site=args.max_per_site,
        min_score=args.min_score,
        headless=not args.no_headless,
        output_file=args.output,
        include_promoted=args.include_promoted,
    ))


if __name__ == "__main__":
    main()
