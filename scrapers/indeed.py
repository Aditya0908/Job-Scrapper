"""
Indeed Jobs scraper — uses the public search page.

Indeed's search results are accessible without login.
We scrape the HTML result cards directly.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from models import JobPosting, UserProfile
from scrapers.base import BaseScraper
from utils.stealth import human_delay, human_scroll


class IndeedScraper(BaseScraper):
    name = "indeed"

    _BASE = "https://www.indeed.com/jobs"

    def _build_url(self, keyword: str, location: str) -> str:
        return f"{self._BASE}?q={quote_plus(keyword)}&l={quote_plus(location)}"

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
                    await human_scroll(page, times=2)

                    cards = await page.query_selector_all("div.job_seen_beacon")
                    if not cards:
                        cards = await page.query_selector_all(
                            "div.jobsearch-ResultsList > div"
                        )
                    if not cards:
                        cards = await page.query_selector_all("td.resultContent")

                    for card in cards:
                        if len(jobs) >= self.max_results:
                            break
                        try:
                            job = await self._parse_card(card, page)
                            if job:
                                jobs.append(job)
                        except Exception:
                            continue

                    await human_delay(1, 3)

            await self.browser.save_session(ctx, self.name)
        finally:
            await ctx.close()

        return jobs

    async def _parse_card(self, card, page) -> JobPosting | None:
        title_el = await card.query_selector(
            "h2.jobTitle span[title], h2.jobTitle a, a.jcs-JobTitle"
        )
        company_el = await card.query_selector(
            "span[data-testid='company-name'], span.companyName, span.css-1h7lukg"
        )
        location_el = await card.query_selector(
            "div[data-testid='text-location'], div.companyLocation"
        )
        link_el = await card.query_selector(
            "h2.jobTitle a, a.jcs-JobTitle"
        )
        date_el = await card.query_selector("span.date, span.css-qvloho")

        title = ""
        if title_el:
            title = (await title_el.get_attribute("title")) or (await title_el.inner_text())
            title = title.strip()

        company = (await company_el.inner_text()).strip() if company_el else ""
        location = (await location_el.inner_text()).strip() if location_el else ""
        posted = (await date_el.inner_text()).strip() if date_el else ""

        href = ""
        if link_el:
            raw = await link_el.get_attribute("href")
            if raw:
                href = f"https://www.indeed.com{raw}" if raw.startswith("/") else raw

        if not title or not href:
            return None

        full_text = await card.inner_text()
        is_promoted = self._is_promoted(full_text)

        snippet = ""
        snippet_el = await card.query_selector(
            "div.job-snippet, div[class*='job-snippet']"
        )
        if snippet_el:
            snippet = (await snippet_el.inner_text()).strip()

        return JobPosting(
            title=title,
            company=company,
            location=location,
            description=snippet or full_text[:1000],
            apply_url=href,
            source="Indeed",
            posted_date=posted,
            is_promoted=is_promoted,
        )
