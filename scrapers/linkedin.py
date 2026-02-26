"""
LinkedIn Jobs scraper — uses the *public* guest job search endpoint.

LinkedIn's /jobs/search/ page works without login for basic searches.
We avoid the authenticated feed entirely so no account is at risk.
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus

from models import JobPosting, UserProfile
from scrapers.base import BaseScraper
from utils.stealth import human_delay, human_scroll


class LinkedInScraper(BaseScraper):
    name = "linkedin"

    _BASE = "https://www.linkedin.com/jobs/search/"

    def _build_url(self, keyword: str, location: str) -> str:
        params = (
            f"?keywords={quote_plus(keyword)}"
            f"&location={quote_plus(location)}"
            f"&trk=public_jobs_jobs-search-bar_search-submit"
            f"&position=1&pageNum=0"
        )
        return self._BASE + params

    async def scrape(self, profile: UserProfile) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        ctx = await self.browser.new_context(self.name)

        try:
            page = await self.browser.new_page(ctx)

            for keyword in profile.search_keywords[:2]:
                for loc in profile.location_queries[:2]:
                    if len(jobs) >= self.max_results:
                        break

                    url = self._build_url(keyword, loc)
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    await human_delay(2, 4)
                    await human_scroll(page, times=3)

                    cards = await page.query_selector_all(
                        "ul.jobs-search__results-list > li"
                    )
                    if not cards:
                        cards = await page.query_selector_all(
                            "div.base-search-card"
                        )

                    for card in cards:
                        if len(jobs) >= self.max_results:
                            break
                        try:
                            job = await self._parse_card(card)
                            if job:
                                jobs.append(job)
                        except Exception:
                            continue

                    await human_delay(1, 3)

            await self.browser.save_session(ctx, self.name)
        finally:
            await ctx.close()

        return jobs

    async def _parse_card(self, card) -> JobPosting | None:
        title_el = await card.query_selector(
            "h3.base-search-card__title, span.sr-only"
        )
        company_el = await card.query_selector(
            "h4.base-search-card__subtitle, a.hidden-nested-link"
        )
        location_el = await card.query_selector(
            "span.job-search-card__location"
        )
        link_el = await card.query_selector("a.base-card__full-link, a")
        date_el = await card.query_selector("time")

        title = (await title_el.inner_text()).strip() if title_el else ""
        company = (await company_el.inner_text()).strip() if company_el else ""
        location = (await location_el.inner_text()).strip() if location_el else ""
        href = await link_el.get_attribute("href") if link_el else ""
        posted = (await date_el.inner_text()).strip() if date_el else ""

        if not title or not href:
            return None

        full_text = await card.inner_text()
        is_promoted = self._is_promoted(full_text)

        return JobPosting(
            title=title,
            company=company,
            location=location,
            description=full_text[:1000],
            apply_url=href.split("?")[0] if href else "",
            source="LinkedIn",
            posted_date=posted,
            is_promoted=is_promoted,
        )
