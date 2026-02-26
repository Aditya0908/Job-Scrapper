"""
Stealth browser engine — wraps Playwright with anti-detection measures.

Strategy:
  1. Persistent browser context (reuses cookies/sessions from manual login)
  2. Randomised fingerprints (viewport, user-agent, locale, timezone)
  3. Human-like delays between actions
  4. Stealth JS patches injected on every page (hides webdriver flag, etc.)
"""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from typing import Optional

from fake_useragent import UserAgent
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)

_STEALTH_JS = """
() => {
    // Hide webdriver flag
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // Spoof plugins length
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });

    // Spoof languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en'],
    });

    // Remove chrome automation indicators
    window.chrome = { runtime: {} };

    // Spoof permissions
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
}
"""

STORAGE_DIR = Path.home() / ".job_scraper" / "sessions"

VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1920, "height": 1080},
    {"width": 1280, "height": 720},
]

TIMEZONES = [
    "Asia/Kolkata",
    "America/New_York",
    "Europe/London",
    "America/Los_Angeles",
]


def _random_viewport() -> dict:
    return random.choice(VIEWPORTS)


async def human_delay(low: float = 0.8, high: float = 2.5) -> None:
    await asyncio.sleep(random.uniform(low, high))


async def human_type(page: Page, selector: str, text: str) -> None:
    """Type text character-by-character with random inter-key delays."""
    await page.click(selector)
    await human_delay(0.3, 0.6)
    for ch in text:
        await page.keyboard.type(ch, delay=random.randint(40, 150))
    await human_delay(0.2, 0.5)


async def human_scroll(page: Page, times: int = 3) -> None:
    for _ in range(times):
        delta = random.randint(300, 700)
        await page.mouse.wheel(0, delta)
        await human_delay(0.5, 1.5)


class StealthBrowser:
    """Manages a stealth Playwright browser with persistent sessions."""

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._pw = None
        self._browser: Optional[Browser] = None
        self._ua = UserAgent(browsers=["chrome", "edge"])

    async def start(self) -> None:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self._headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

    async def new_context(self, site_name: str) -> BrowserContext:
        """Create a context with stealth settings; reuses saved session if available."""
        vp = _random_viewport()
        ua = self._ua.random

        storage_path = STORAGE_DIR / f"{site_name}.json"
        storage_state = None
        if storage_path.exists():
            storage_state = str(storage_path)

        ctx = await self._browser.new_context(
            viewport=vp,
            user_agent=ua,
            locale="en-US",
            timezone_id=random.choice(TIMEZONES),
            storage_state=storage_state,
            java_script_enabled=True,
        )
        return ctx

    async def new_page(self, ctx: BrowserContext) -> Page:
        page = await ctx.new_page()
        await page.add_init_script(_STEALTH_JS)
        return page

    async def save_session(self, ctx: BrowserContext, site_name: str) -> None:
        storage_path = STORAGE_DIR / f"{site_name}.json"
        state = await ctx.storage_state()
        storage_path.write_text(json.dumps(state))

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
