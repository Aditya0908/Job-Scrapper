from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Optional


class ExperienceLevel(str, Enum):
    ENTRY = "entry"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"

    @classmethod
    def from_years(cls, years: int) -> "ExperienceLevel":
        if years <= 1:
            return cls.ENTRY
        if years <= 4:
            return cls.MID
        if years <= 8:
            return cls.SENIOR
        return cls.LEAD


@dataclass
class UserProfile:
    skills: list[str]
    experience_years: int
    role: str
    location: str
    remote_ok: bool = True
    search_locations: Optional[list[str]] = field(default=None)

    @property
    def experience_level(self) -> ExperienceLevel:
        return ExperienceLevel.from_years(self.experience_years)

    # Generic job-title suffix words that carry no domain meaning
    _GENERIC_SUFFIXES: ClassVar[frozenset[str]] = frozenset({
        "engineer", "developer", "specialist", "analyst", "manager",
        "architect", "lead", "head", "director", "officer", "associate",
        "consultant", "intern", "trainee", "researcher", "expert",
        "professional", "executive", "coordinator", "advisor",
    })

    # When the role suffix is one of these, swap with the others for extra reach
    _SUFFIX_SWAPS: ClassVar[list[str]] = ["Engineer", "Developer", "Specialist"]

    # Common acronym → full form mappings (role-agnostic)
    _ACRONYM_EXPAND: ClassVar[dict[str, str]] = {
        "ai": "Artificial Intelligence",
        "ml": "Machine Learning",
        "llm": "Large Language Model",
        "nlp": "Natural Language Processing",
        "cv":  "Computer Vision",
        "dl":  "Deep Learning",
        "sre": "Site Reliability Engineer",
        "qa":  "Quality Assurance",
        "bi":  "Business Intelligence",
        "rpa": "Robotic Process Automation",
    }

    def _role_domain_words(self) -> list[str]:
        """
        Strip generic suffix words from the role to get the domain-specific core.
        e.g. 'AI Engineer' → ['AI']
             'Machine Learning Engineer' → ['Machine', 'Learning']
             'Product Manager' → ['Product']
             'DevOps' → ['DevOps']
        """
        words = self.role.split()
        domain = [w for w in words if w.lower() not in self._GENERIC_SUFFIXES]
        return domain if domain else words  # fallback: use all words

    @property
    def search_keywords(self) -> list[str]:
        """
        Dynamically generate role synonyms from the profile role.
        Works for ANY role — no hardcoded role names.
        Strategy:
          1. Start with the exact role string from the profile
          2. Swap the role suffix (Engineer ↔ Developer ↔ Specialist)
          3. Expand known acronyms in the domain words (AI → Artificial Intelligence)
        """
        keywords: list[str] = [self.role]
        words = self.role.split()

        # --- Suffix swap: Engineer ↔ Developer ↔ Specialist ---
        if words:
            suffix = words[-1]
            prefix_parts = words[:-1]
            if suffix in self._SUFFIX_SWAPS and prefix_parts:
                prefix = " ".join(prefix_parts)
                for swap in self._SUFFIX_SWAPS:
                    if swap != suffix:
                        candidate = f"{prefix} {swap}"
                        if candidate not in keywords:
                            keywords.append(candidate)

        # --- Acronym expansion in domain words ---
        domain = self._role_domain_words()
        for word in domain:
            expanded = self._ACRONYM_EXPAND.get(word.lower())
            if expanded:
                # Build the full role with acronym replaced by expansion
                new_role = self.role.replace(word, expanded)
                if new_role not in keywords:
                    keywords.append(new_role)

        return keywords

    @property
    def linkedin_experience_codes(self) -> list[str]:
        """
        LinkedIn f_E URL parameter values:
          1 = Internship  (0 exp, student)
          2 = Entry level (0-2 yrs)
          3 = Associate   (2-5 yrs)
          4 = Mid-Senior  (5+ yrs)
          5 = Director
        """
        years = self.experience_years
        if years == 0:
            return ["1", "2"]       # true fresh grad / no exp → include intern
        elif years <= 2:
            return ["2"]            # 1-2 yrs → Entry Level only
        elif years <= 5:
            return ["2", "3"]       # 3-5 yrs → Entry + Associate
        elif years <= 9:
            return ["3", "4"]       # 6-9 yrs → Associate + Mid-Senior
        else:
            return ["4", "5"]       # 10+ yrs → Mid-Senior + Director

    @property
    def location_queries(self) -> list[str]:
        """
        If `search_locations` is set in profile.json → use those directly.
        City-level searches (Bengaluru, Hyderabad) return real results on LinkedIn;
        country-level searches (India) cause LinkedIn to pad with algo-recommended
        unrelated jobs.
        Falls back to parsing the `location` string if search_locations is not set.
        """
        if self.search_locations:
            return [loc.strip() for loc in self.search_locations if loc.strip()]

        # Legacy: auto-parse location string
        locations = []
        raw = self.location.strip()
        parts = [p.strip() for p in re.split(r"[/,]", raw) if p.strip()]
        for part in parts:
            if part.lower() == "remote":
                if "Remote" not in locations:
                    locations.append("Remote")
            else:
                if part not in locations:
                    locations.append(part)
        if self.remote_ok and "Remote" not in locations:
            locations.insert(0, "Remote")
        return locations if locations else ["Remote"]

    @classmethod
    def from_dict(cls, data: dict) -> "UserProfile":
        skills_raw = data.get("skills") or data.get("Skills") or []
        if isinstance(skills_raw, str):
            skills_raw = [s.strip() for s in skills_raw.split(",")]

        role = data.get("role") or data.get("Role") or ""
        location = data.get("location") or data.get("Location") or "Remote"

        exp_raw = data.get("experience_years") or data.get("Experience") or 0
        if isinstance(exp_raw, str):
            import re
            nums = re.findall(r"\d+", exp_raw)
            exp_raw = int(nums[0]) if nums else 0

        # remote_ok is True if "remote" appears anywhere in the location string
        remote_ok = "remote" in location.lower()

        search_locations_raw = data.get("search_locations") or data.get("Search_locations")

        return cls(
            skills=skills_raw,
            experience_years=int(exp_raw),
            role=role,
            location=location,
            remote_ok=remote_ok,
            search_locations=search_locations_raw,
        )


@dataclass
class JobPosting:
    title: str
    company: str
    location: str
    description: str
    apply_url: str
    source: str
    experience_required: str = ""
    salary: str = ""
    posted_date: str = ""
    is_promoted: bool = False
    fit_score: float = 0.0
    match_reasons: list[str] = field(default_factory=list)

    @property
    def summary_text(self) -> str:
        return f"{self.title} {self.company} {self.description} {self.location}"
