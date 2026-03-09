#!/usr/bin/env python3
"""
Job Scraper & Auto-Apply Agent — CLI entry point.

Usage examples:
  Scraping:
    python main.py scrape --profile-file profile.json
    python main.py scrape --profile '{"role":"AI Engineer","skills":"Python,ML","experience_years":3,"location":"Remote"}'
    python main.py scrape --profile-file profile.json --sites linkedin naukri
    python main.py scrape --profile-file profile.json --no-headless
    python main.py scrape --profile-file profile.json --output results.json

  Auto-Apply:
    python main.py apply --url "https://example.com/jobs/123/apply" --profile-file user_profile.json
    python main.py apply --url "https://example.com/jobs/123/apply" --profile-file user_profile.json --dry-run
    python main.py apply --url "https://example.com/jobs/123/apply" --profile-file user_profile.json --no-headless
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Job Scraper & Auto-Apply Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="command", help="Command to run")

    # ── scrape subcommand ──
    scrape = sub.add_parser("scrape", help="Scrape job listings from multiple sites")
    scrape_group = scrape.add_mutually_exclusive_group(required=True)
    scrape_group.add_argument("--profile", type=str, help="User profile as a JSON string")
    scrape_group.add_argument("--profile-file", type=str, help="Path to a JSON profile file")
    scrape.add_argument("--sites", nargs="+", choices=["linkedin", "indeed", "naukri"], default=None)
    scrape.add_argument("--max-per-site", type=int, default=25)
    scrape.add_argument("--min-score", type=float, default=0.0)
    scrape.add_argument("--include-promoted", action="store_true")
    scrape.add_argument("--no-headless", action="store_true")
    scrape.add_argument("--output", "-o", type=str, default=None)

    # ── apply subcommand ──
    apply_cmd = sub.add_parser("apply", help="Auto-apply to a job using the multi-agent system")
    apply_cmd.add_argument("--url", required=True, help="Job application page URL")
    apply_cmd.add_argument("--profile-file", required=True, help="Path to user_profile.json")
    apply_cmd.add_argument("--no-headless", action="store_true", help="Show the browser window")
    apply_cmd.add_argument("--dry-run", action="store_true", help="Fill form but don't submit")
    apply_cmd.add_argument(
        "--site", default="apply",
        help="Site name for session reuse (e.g. linkedin, indeed). Default: apply",
    )

    return p


def _run_scrape(args: argparse.Namespace) -> None:
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


def _run_apply(args: argparse.Namespace) -> None:
    path = Path(args.profile_file)
    if not path.exists():
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    from auto_apply.runner import auto_apply

    state = asyncio.run(auto_apply(
        job_url=args.url,
        profile_path=str(path),
        headless=not args.no_headless,
        dry_run=args.dry_run,
        site_name=args.site,
    ))

    sys.exit(0 if state.phase.value == "done" else 1)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "scrape":
        _run_scrape(args)
    elif args.command == "apply":
        _run_apply(args)


if __name__ == "__main__":
    main()
