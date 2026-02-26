#!/usr/bin/env python3
"""
One-time login helper — opens a visible browser so you can log in manually.

After you log in, the session cookies are saved to ~/.job_scraper/sessions/
and reused by the scraper agent. This way:
  - Your credentials are never stored in code or config.
  - The agent reuses your real session, looking like a normal user.

Usage:
    python login_helper.py linkedin
    python login_helper.py naukri
    python login_helper.py indeed
"""

from __future__ import annotations

import asyncio
import sys

from rich.console import Console

from utils.stealth import StealthBrowser

console = Console()

SITE_URLS = {
    "linkedin": "https://www.linkedin.com/login",
    "indeed": "https://secure.indeed.com/auth",
    "naukri": "https://www.naukri.com/nlogin/login",
}


async def login_flow(site: str) -> None:
    if site not in SITE_URLS:
        console.print(f"[red]Unknown site: {site}. Choose from: {', '.join(SITE_URLS)}[/red]")
        return

    console.print(f"\n[bold cyan]Opening {site} login page...[/bold cyan]")
    console.print("[dim]Log in normally in the browser window that opens.[/dim]")
    console.print("[dim]When you're done and see your dashboard, come back here and press Enter.[/dim]\n")

    browser = StealthBrowser(headless=False)
    await browser.start()

    ctx = await browser.new_context(site)
    page = await browser.new_page(ctx)
    await page.goto(SITE_URLS[site], wait_until="domcontentloaded")

    input("Press Enter after you've logged in successfully...")

    await browser.save_session(ctx, site)
    console.print(f"[green]Session saved for {site}![/green]")

    await ctx.close()
    await browser.close()


def main() -> None:
    if len(sys.argv) < 2:
        console.print("[yellow]Usage: python login_helper.py <site>[/yellow]")
        console.print(f"Available sites: {', '.join(SITE_URLS)}")
        sys.exit(1)

    site = sys.argv[1].lower()
    asyncio.run(login_flow(site))


if __name__ == "__main__":
    main()
