"""
LinkedIn Jobs scraper — works with both the public guest page
AND the authenticated (logged-in) page.

Fix log:
- Primary selector: div.job-card-container--clickable (authenticated page)
- Falls back to public-page selectors if not logged in
- Internal card parsing uses authenticated-page DOM structure
- Added verbose debug logging + page snippet on failure
- Increased scroll/wait for lazy-loaded cards
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import quote_plus

from models import JobPosting, UserProfile
from scrapers.base import BaseScraper
from utils.stealth import human_delay, human_scroll


class LinkedInScraper(BaseScraper):
    name = "linkedin"

    _BASE = "https://www.linkedin.com/jobs/search/"

    def _build_url(self, keyword: str, location: str, exp_codes: list[str] | None = None) -> str:
        params = (
            f"?keywords={quote_plus(keyword)}"
            f"&location={quote_plus(location)}"
            f"&sortBy=DD"        # date descending — freshest first
            f"&position=1&pageNum=0"
        )
        if exp_codes:
            params += f"&f_E={','.join(exp_codes)}"
        return self._BASE + params

    def _is_title_relevant(self, title: str, profile: "UserProfile") -> bool:
        """
        Dynamically check if the job title is relevant to the user's role.
        Works for ANY role in profile.json — no hardcoded lists.

        Domain words from the profile's role (e.g. 'AI Engineer' → ['AI'])
        are matched as WHOLE WORDS in the title to avoid false positives like
        'ai' matching inside 'trainee', 'ml' inside 'email', etc.
        """
        title_lower = title.lower()

        # Build the set of domain terms to look for
        all_terms: set[str] = set()

        # Domain words from the exact profile role
        for w in profile._role_domain_words():
            all_terms.add(w.lower())

        # Domain words from every search keyword variation
        for kw in profile.search_keywords:
            for w in kw.split():
                if w.lower() not in profile._GENERIC_SUFFIXES and len(w) > 1:
                    all_terms.add(w.lower())

        if not all_terms:
            return profile.role.lower() in title_lower

        for term in all_terms:
            # Short terms (≤4 chars, e.g. 'ai', 'ml', 'llm', 'nlp') must match
            # as whole words so 'ai' doesn't match inside 'trainee'/'brain'.
            if len(term) <= 4:
                if re.search(rf"\b{re.escape(term)}\b", title_lower):
                    return True
                # Also match compound acronyms: 'GenAI', 'MLOps', 'AIOps',
                # 'LLMOps' — split title into tokens and check each one.
                for token in re.split(r"[\s\-/|,]", title_lower):
                    if token.startswith(term) or token.endswith(term):
                        # Make sure it's not a false match (e.g. 'ai' in 'trainer')
                        # by requiring the token is short (likely an acronym)
                        if len(token) <= len(term) + 5:
                            return True
            else:
                # Longer terms (e.g. 'machine', 'learning', 'devops') can match
                # as substrings — safe enough at this length.
                if term in title_lower:
                    return True

        return False

    async def scrape(self, profile: UserProfile) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        seen_urls: set[str] = set()
        ctx = await self.browser.new_context(self.name)

        try:
            page = await self.browser.new_page(ctx)

            keywords = profile.search_keywords
            locations = profile.location_queries
            exp_codes = profile.linkedin_experience_codes
            print(f"  [LinkedIn] keywords={keywords}")
            print(f"  [LinkedIn] locations={locations}")
            print(f"  [LinkedIn] experience={profile.experience_years}y ({profile.experience_level.value}) → f_E={exp_codes}")

            for keyword in keywords:
                for loc in locations:
                    if len(jobs) >= self.max_results:
                        break

                    url = self._build_url(keyword, loc, exp_codes)
                    print(f"\n  [LinkedIn] Fetching: {url}")

                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    except Exception as e:
                        print(f"  [LinkedIn] Navigation error: {e}")
                        continue

                    await human_delay(3, 5)
                    await human_scroll(page, times=6)
                    await human_delay(2, 4)

                    current_url = page.url
                    if "login" in current_url or "authwall" in current_url:
                        print(f"  [LinkedIn] Auth wall → {current_url}")
                        continue

                    print(f"  [LinkedIn] Title: {await page.title()}")
                    cards = await self._find_cards(page)
                    print(f"  [LinkedIn] Cards from page: {len(cards)}")

                    accepted = skipped_title = skipped_dup = skipped_exp = 0
                    for card in cards:
                        if len(jobs) >= self.max_results:
                            break
                        try:
                            # ── Step 1: Quick card parse (no click yet) ──────
                            job = await self._parse_card(card)
                            if not job:
                                continue

                            # ── Step 2: Deduplicate ──────────────────────────
                            if job.apply_url in seen_urls:
                                skipped_dup += 1
                                continue

                            # ── Step 3: Title relevance guard (no click yet) ─
                            if not self._is_title_relevant(job.title, profile):
                                skipped_title += 1
                                continue

                            # ── Step 4: Click card → read full JD from panel ─
                            full_desc, exp_required = await self._read_detail_panel(page, card)
                            if full_desc:
                                job.description = full_desc[:2000]
                            if exp_required:
                                job.experience_required = exp_required
                                print(f"    exp_required: '{exp_required}'")

                            # ── Step 5: Experience hard filter ───────────────
                            if exp_required:
                                nums = re.findall(r"\d+", exp_required)
                                if nums:
                                    min_exp = int(nums[0])
                                    overshoot = min_exp - profile.experience_years
                                    if overshoot >= 2:
                                        print(f"    ✗ Exp mismatch: needs {min_exp}yr, profile has {profile.experience_years}yr → skip")
                                        skipped_exp += 1
                                        continue

                            seen_urls.add(job.apply_url)
                            jobs.append(job)
                            accepted += 1
                            print(f"    ✓ {job.title} @ {job.company} [{job.location}] exp='{exp_required or 'unknown'}'")

                        except Exception as exc:
                            print(f"  [LinkedIn] Card error: {exc}")
                            continue

                    print(f"  [LinkedIn] Accepted={accepted} | Irrelevant={skipped_title} | Dup={skipped_dup} | Exp-filtered={skipped_exp}")
                    await human_delay(2, 4)

            await self.browser.save_session(ctx, self.name)

        finally:
            await ctx.close()

        print(f"\n  [LinkedIn] Total scraped: {len(jobs)}")
        return jobs

    async def _read_detail_panel(self, page, card) -> tuple[str, str]:
        """
        Click the job card to open LinkedIn's right-side detail panel,
        then extract the full job description text from it.
        Returns (full_description_text, experience_required_string).
        Full JD is needed because experience requirements are only shown there.
        """
        try:
            await card.click()
            # Wait for the detail panel to load
            await asyncio.sleep(2)

            # Description panel selectors (authenticated LinkedIn)
            desc_selectors = [
                "div.jobs-description-content__text",
                "div.jobs-description__content",
                "article.jobs-description__container",
                "div.job-view-layout",
                "div.jobs-search__job-details--container",
            ]
            desc_text = ""
            for sel in desc_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        desc_text = (await el.inner_text()).strip()
                        if desc_text:
                            break
                except Exception:
                    continue

            exp_required = ""
            if desc_text:
                exp_match = re.search(
                    r"(\d+\s*[\+\-]\s*\d*|\d+)\s*(?:to\s*\d+\s*)?"
                    r"(?:\+\s*)?(?:years?|yrs?)"
                    r"(?:\s*(?:of\s+)?(?:professional\s+)?(?:relevant\s+)?(?:total\s+)?experience)?",
                    desc_text,
                    re.IGNORECASE,
                )
                if exp_match:
                    exp_required = exp_match.group(0).strip()

            return desc_text, exp_required

        except Exception as e:
            print(f"    [detail panel] error: {e}")
            return "", ""


    async def _find_cards(self, page) -> list:
        """
        Try selector strategies in order.
        Authenticated page → div.job-card-container--clickable
        Public/guest page  → ul.jobs-search__results-list > li
        """
        strategies = [
            # ---- Authenticated (logged-in) LinkedIn ----
            ("div.job-card-container--clickable", None),
            ("div[data-job-id]", None),
            # ---- Public / guest LinkedIn ----
            ("ul.jobs-search__results-list", "li"),
            ("div.base-search-card", None),
            ("div.base-card", None),
            # ---- Broad fallbacks ----
            ("li[class*='jobs-search-results']", None),
        ]

        for parent_sel, child_sel in strategies:
            try:
                if child_sel:
                    sel = f"{parent_sel} > {child_sel}"
                else:
                    sel = parent_sel
                els = await page.query_selector_all(sel)
                if els:
                    print(f"  [LinkedIn] ✓ Selector '{sel}' → {len(els)} cards")
                    return els
            except Exception:
                continue

        # Nothing matched — print a snippet to help debug
        try:
            snippet = (await page.inner_text("body"))[:400].replace("\n", " ")
            print(f"  [LinkedIn] ✗ No cards. Body snippet: {snippet}")
        except Exception:
            pass

        return []

    async def _parse_card(self, card) -> JobPosting | None:
        # ── Title ──────────────────────────────────────────────────────────
        title = ""
        for sel in [
            "a.job-card-list__title--link",       # authenticated
            "a.job-card-container__link",          # authenticated alt
            "h3.base-search-card__title",          # public
            "h3",
            "span.sr-only",
        ]:
            el = await card.query_selector(sel)
            if el:
                raw = (await el.inner_text()).strip()
                # Strip the " with verification" aria suffix at the end
                title = raw.split(" with verification")[0].strip()
                if title:
                    break

        # ── Company ────────────────────────────────────────────────────────
        company = ""
        for sel in [
            "div.artdeco-entity-lockup__subtitle span",  # authenticated
            "h4.base-search-card__subtitle",              # public
            "a.hidden-nested-link",
            "[class*='subtitle'] span",
        ]:
            el = await card.query_selector(sel)
            if el:
                company = (await el.inner_text()).strip()
                if company:
                    break

        # ── Location ───────────────────────────────────────────────────────
        location = ""
        for sel in [
            "ul.job-card-container__metadata-wrapper li span",  # authenticated
            "span.job-search-card__location",                   # public
            "[class*='metadata'] li",
            "[class*='location']",
        ]:
            el = await card.query_selector(sel)
            if el:
                location = (await el.inner_text()).strip()
                if location:
                    break

        # ── Link ───────────────────────────────────────────────────────────
        href = ""
        for sel in [
            "a.job-card-list__title--link",   # authenticated
            "a.job-card-container__link",
            "a.base-card__full-link",          # public
            "a[href*='/jobs/view/']",
            "a",
        ]:
            el = await card.query_selector(sel)
            if el:
                href = (await el.get_attribute("href")) or ""
                if href:
                    break

        # ── Date ───────────────────────────────────────────────────────────
        date_el = await card.query_selector("time")
        posted = (await date_el.inner_text()).strip() if date_el else ""

        if not title or not href:
            return None

        # Build full apply URL
        apply_url = href
        if href.startswith("/"):
            apply_url = "https://www.linkedin.com" + href
        apply_url = apply_url.split("?")[0]

        full_text = await card.inner_text()
        is_promoted = self._is_promoted(full_text)

        # ── Experience requirement (mined from card text) ───────────────────
        # Matches: "3+ years", "2-4 years", "minimum 3 years of experience", etc.
        exp_required = ""
        exp_match = re.search(
            r"(\d+\s*[\+\-]\s*\d*|\d+)\s*(?:to\s*\d+\s*)?"
            r"(?:\+\s*)?(?:years?|yrs?)"
            r"(?:\s*(?:of\s+)?(?:professional\s+)?(?:relevant\s+)?experience)?",
            full_text,
            re.IGNORECASE,
        )
        if exp_match:
            exp_required = exp_match.group(0).strip()

        return JobPosting(
            title=title,
            company=company,
            location=location,
            description=full_text[:1000],
            apply_url=apply_url,
            source="LinkedIn",
            posted_date=posted,
            is_promoted=is_promoted,
            experience_required=exp_required,
        )
