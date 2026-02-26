"""
Naukri.com scraper — uses the public search page.

Naukri search results are publicly accessible.
URL pattern: https://www.naukri.com/<keyword>-jobs-in-<location>
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus

from models import JobPosting, UserProfile
from scrapers.base import BaseScraper
from utils.stealth import human_delay, human_scroll

_EXP_MAP = {
    "entry": (0, 2),
    "mid": (2, 5),
    "senior": (5, 10),
    "lead": (8, 15),
}


class NaukriScraper(BaseScraper):
    name = "naukri"

    _BASE = "https://www.naukri.com/jobs-in-india"
    _SEARCH = "https://www.naukri.com/{keyword}-jobs-in-{location}"

    def _build_url(self, keyword: str, location: str, exp_range: tuple[int, int]) -> str:
        kw_slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")
        loc_slug = re.sub(r"[^a-z0-9]+", "-", location.lower()).strip("-")

        if loc_slug and loc_slug != "remote":
            url = f"https://www.naukri.com/{kw_slug}-jobs-in-{loc_slug}"
        else:
            url = f"https://www.naukri.com/{kw_slug}-jobs"

        url += f"?experience={exp_range[0]}"
        return url

    async def scrape(self, profile: UserProfile) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        ctx = await self.browser.new_context(self.name)
        exp_range = _EXP_MAP.get(profile.experience_level.value, (0, 5))

        try:
            page = await self.browser.new_page(ctx)

            for keyword in profile.search_keywords[:2]:
                for loc in profile.location_queries[:2]:
                    if len(jobs) >= self.max_results:
                        break

                    url = self._build_url(keyword, loc, exp_range)
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    await human_delay(2, 5)
                    await human_scroll(page, times=4)

                    cards = await page.query_selector_all("article.jobTuple")
                    if not cards:
                        cards = await page.query_selector_all(
                            "div.srp-jobtuple-wrapper, div.cust-job-tuple"
                        )
                    if not cards:
                        cards = await page.query_selector_all(
                            "div[class*='jobTuple'], div[class*='job-tuple']"
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
            "a.title, a[class*='title'], a.jobTitle"
        )
        company_el = await card.query_selector(
            "a.subTitle, a[class*='comp-name'], span.comp-name, a.comp-name"
        )
        location_el = await card.query_selector(
            "span.locWdth, span[class*='loc'], li.location, span.loc-wrap, span.ni-job-tuple-icon-srp-location"
        )
        exp_el = await card.query_selector(
            "span.expwdth, span[class*='exp'], li.experience, span.ni-job-tuple-icon-srp-experience"
        )
        salary_el = await card.query_selector(
            "span.sal, span[class*='sal'], li.salary, span.ni-job-tuple-icon-srp-rupee"
        )

        title = (await title_el.inner_text()).strip() if title_el else ""
        href = (await title_el.get_attribute("href")) if title_el else ""
        company = (await company_el.inner_text()).strip() if company_el else ""
        location = (await location_el.inner_text()).strip() if location_el else ""
        exp_text = (await exp_el.inner_text()).strip() if exp_el else ""
        salary = (await salary_el.inner_text()).strip() if salary_el else ""

        if not title or not href:
            return None

        full_text = await card.inner_text()
        is_promoted = self._is_promoted(full_text)

        desc_el = await card.query_selector(
            "div.job-description, div[class*='job-desc'], span.job-desc"
        )
        desc = (await desc_el.inner_text()).strip() if desc_el else full_text[:1000]

        return JobPosting(
            title=title,
            company=company,
            location=location,
            description=desc,
            apply_url=href,
            source="Naukri",
            experience_required=exp_text,
            salary=salary,
            is_promoted=is_promoted,
        )
