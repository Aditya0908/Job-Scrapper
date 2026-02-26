from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


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

    @property
    def experience_level(self) -> ExperienceLevel:
        return ExperienceLevel.from_years(self.experience_years)

    @property
    def search_keywords(self) -> list[str]:
        """Generate search keyword combinations from the profile."""
        keywords = [self.role]
        top_skills = self.skills[:3]
        if top_skills:
            keywords.append(f"{self.role} {' '.join(top_skills)}")
        for skill in top_skills:
            keywords.append(f"{skill} {self.role}")
        return keywords

    @property
    def location_queries(self) -> list[str]:
        locations = []
        if self.remote_ok:
            locations.append("Remote")
        loc = self.location.strip()
        if loc.lower() not in ("remote", ""):
            locations.append(loc)
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

        remote_ok = "remote" in location.lower()

        return cls(
            skills=skills_raw,
            experience_years=int(exp_raw),
            role=role,
            location=location,
            remote_ok=remote_ok,
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
