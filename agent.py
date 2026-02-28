"""
Orchestrator agent — ties together scraping, matching, and output.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from models import JobPosting, UserProfile
from scrapers.indeed import IndeedScraper
from scrapers.linkedin import LinkedInScraper
from scrapers.naukri import NaukriScraper
from utils.matcher import score_jobs
from utils.stealth import StealthBrowser

console = Console()

ALL_SCRAPERS = {
    "linkedin": LinkedInScraper,
    "indeed": IndeedScraper,
    "naukri": NaukriScraper,
}


async def _scrape_site(scraper_cls, browser, profile, max_results):
    name = scraper_cls.name if hasattr(scraper_cls, "name") else scraper_cls.__name__
    console.print(f"  [cyan]Searching {name}...[/cyan]")
    scraper = scraper_cls(browser, max_results=max_results)
    try:
        results = await scraper.scrape(profile)
        console.print(f"  [green]Found {len(results)} jobs on {name}[/green]")
        return results
    except Exception as e:
        console.print(f"  [red]Error on {name}: {e}[/red]")
        return []


async def run_agent(
    profile_data: dict,
    sites: list[str] | None = None,
    max_per_site: int = 25,
    min_score: float = 0.0,
    headless: bool = True,
    output_file: str | None = None,
    include_promoted: bool = False,
) -> list[JobPosting]:
    """
    Main entry point.

    Args:
        profile_data: User profile as a dict (parsed from JSON).
        sites: Which sites to scrape (default: all).
        max_per_site: Max results per site.
        min_score: Minimum fit score to include in final output.
        headless: Run browser headlessly (set False for debugging).
        output_file: Optional path to write JSON results.
    """
    profile = UserProfile.from_dict(profile_data)

    console.print(Panel.fit(
        f"[bold]Role:[/bold] {profile.role}\n"
        f"[bold]Skills:[/bold] {', '.join(profile.skills)}\n"
        f"[bold]Experience:[/bold] {profile.experience_years}y ({profile.experience_level.value})\n"
        f"[bold]Location:[/bold] {profile.location} (remote={'yes' if profile.remote_ok else 'no'})\n"
        f"[bold]Search keywords:[/bold] {profile.search_keywords}",
        title="User Profile",
        border_style="blue",
    ))

    chosen = sites or list(ALL_SCRAPERS.keys())
    scrapers = [ALL_SCRAPERS[s] for s in chosen if s in ALL_SCRAPERS]

    browser = StealthBrowser(headless=headless)
    await browser.start()

    console.print("\n[bold yellow]Scraping job sites...[/bold yellow]")
    all_jobs: list[JobPosting] = []

    tasks = [
        _scrape_site(cls, browser, profile, max_per_site)
        for cls in scrapers
    ]
    results = await asyncio.gather(*tasks)
    for batch in results:
        all_jobs.extend(batch)

    await browser.close()

    console.print(f"\n[bold]Total raw results:[/bold] {len(all_jobs)}")

    if not all_jobs:
        console.print("[red]No jobs scraped at all. Possible causes:[/red]")
        console.print("  [yellow]1.[/yellow] LinkedIn is showing an auth-wall (run with [bold]--no-headless[/bold] to log in)")
        console.print("  [yellow]2.[/yellow] CSS selectors changed — check debug output above")
        console.print("  [yellow]3.[/yellow] Network issue or rate limiting")
        return []

    console.print("[bold yellow]Scoring & filtering...[/bold yellow]")
    scored = score_jobs(profile, all_jobs)

    promoted_count = sum(1 for j in scored if j.is_promoted)
    if include_promoted:
        relevant = [j for j in scored if j.fit_score >= min_score]
    else:
        relevant = [j for j in scored if j.fit_score >= min_score and not j.is_promoted]

    low_score_count = len(scored) - len(relevant) - (0 if include_promoted else promoted_count)
    console.print(
        f"[dim]Scraped {len(scored)} total | "
        f"{promoted_count} promoted ({'included' if include_promoted else 'excluded'}) | "
        f"{low_score_count} below score {min_score} | "
        f"{len(relevant)} shown[/dim]"
    )

    _print_results(relevant)

    if output_file:
        _save_results(relevant, output_file)

    return relevant


def _print_results(jobs: list[JobPosting]) -> None:
    if not jobs:
        console.print("\n[red]No relevant jobs found. Try broadening your search.[/red]")
        return

    table = Table(
        title=f"\nTop {len(jobs)} Matching Jobs",
        show_lines=True,
        title_style="bold green",
    )
    table.add_column("Score", style="bold cyan", width=6, justify="right")
    table.add_column("Title", style="bold", max_width=35)
    table.add_column("Company", max_width=20)
    table.add_column("Location", max_width=18)
    table.add_column("Source", width=10)
    table.add_column("Why", max_width=40)

    for job in jobs[:30]:
        score_color = "green" if job.fit_score >= 60 else "yellow" if job.fit_score >= 40 else "red"
        table.add_row(
            f"[{score_color}]{job.fit_score}[/{score_color}]",
            job.title,
            job.company,
            job.location,
            job.source,
            "; ".join(job.match_reasons) if job.match_reasons else "-",
        )

    console.print(table)

    console.print("\n[bold]Apply URLs:[/bold]")
    for i, job in enumerate(jobs[:30], 1):
        console.print(f"  {i}. [link={job.apply_url}]{job.apply_url}[/link]")


def _save_results(jobs: list[JobPosting], path: str) -> None:
    from dataclasses import asdict
    data = [asdict(j) for j in jobs]
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))
    console.print(f"\n[green]Results saved to {path}[/green]")
