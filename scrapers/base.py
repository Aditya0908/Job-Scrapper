from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import JobPosting, UserProfile
    from utils.stealth import StealthBrowser


class BaseScraper(abc.ABC):
    """Every job-site scraper inherits from this."""

    name: str = "base"

    def __init__(self, browser: "StealthBrowser", max_results: int = 25):
        self.browser = browser
        self.max_results = max_results

    @abc.abstractmethod
    async def scrape(self, profile: "UserProfile") -> list["JobPosting"]:
        ...

    @staticmethod
    def _is_promoted(text: str) -> bool:
        promo_signals = [
            "promoted",
            "sponsored",
            "featured",
            "ad ",
            "advertisement",
        ]
        lower = text.lower()
        return any(s in lower for s in promo_signals)
