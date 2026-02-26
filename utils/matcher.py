"""
Job Fit Matching Engine — 100% local, zero API costs.

Scoring is a weighted blend of:
  1. TF-IDF cosine similarity between profile text and job description  (50%)
  2. Skill keyword overlap ratio                                        (30%)
  3. Experience-level alignment                                         (10%)
  4. Location match                                                     (10%)

Promoted/sponsored listings get a penalty so they sink to the bottom.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

if TYPE_CHECKING:
    from models import JobPosting, UserProfile

W_TFIDF = 0.50
W_SKILL = 0.30
W_EXP = 0.10
W_LOC = 0.10
PROMO_PENALTY = 0.30


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", text.lower())


def _skill_overlap(profile_skills: list[str], job_text: str) -> float:
    if not profile_skills:
        return 0.0
    job_lower = job_text.lower()
    matched = sum(1 for s in profile_skills if s.lower() in job_lower)
    return matched / len(profile_skills)


def _experience_score(profile_years: int, job_exp_text: str) -> float:
    """Return 1.0 if the profile experience falls within the job's stated range."""
    nums = re.findall(r"\d+", job_exp_text)
    if not nums:
        return 0.5  # no info — neutral
    low = int(nums[0])
    high = int(nums[-1]) if len(nums) > 1 else low + 3
    if low <= profile_years <= high:
        return 1.0
    distance = min(abs(profile_years - low), abs(profile_years - high))
    return max(0.0, 1.0 - distance * 0.15)


def _location_score(profile_loc: str, job_loc: str, remote_ok: bool) -> float:
    pl = profile_loc.lower()
    jl = job_loc.lower()
    if "remote" in jl:
        return 1.0 if remote_ok else 0.7
    if pl in jl or jl in pl:
        return 1.0
    common = set(pl.split()) & set(jl.split())
    return 0.6 if common else 0.2


def score_jobs(
    profile: "UserProfile",
    jobs: list["JobPosting"],
) -> list["JobPosting"]:
    """Score and sort jobs by fit. Mutates each job's fit_score and match_reasons."""
    if not jobs:
        return jobs

    profile_text = _normalise(
        f"{profile.role} {' '.join(profile.skills)} "
        f"{profile.experience_years} years {profile.location}"
    )
    job_texts = [_normalise(j.summary_text) for j in jobs]

    corpus = [profile_text] + job_texts
    vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
    tfidf_matrix = vectorizer.fit_transform(corpus)
    sims = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()

    for i, job in enumerate(jobs):
        reasons: list[str] = []

        tfidf_score = float(sims[i])
        skill_score = _skill_overlap(profile.skills, job.description)
        exp_score = _experience_score(profile.experience_years, job.experience_required)
        loc_score = _location_score(profile.location, job.location, profile.remote_ok)

        raw = (
            W_TFIDF * tfidf_score
            + W_SKILL * skill_score
            + W_EXP * exp_score
            + W_LOC * loc_score
        )

        if tfidf_score > 0.3:
            reasons.append(f"Strong JD match ({tfidf_score:.0%})")
        if skill_score >= 0.5:
            matched = [s for s in profile.skills if s.lower() in job.description.lower()]
            reasons.append(f"Skills: {', '.join(matched[:5])}")
        if exp_score >= 0.8:
            reasons.append("Experience aligns")
        if loc_score >= 0.8:
            reasons.append("Location fits")

        if job.is_promoted:
            raw = max(0.0, raw - PROMO_PENALTY)
            reasons.append("Promoted listing (penalised)")

        job.fit_score = round(raw * 100, 1)
        job.match_reasons = reasons

    jobs.sort(key=lambda j: j.fit_score, reverse=True)
    return jobs
