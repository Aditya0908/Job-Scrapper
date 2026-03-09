"""Applicant profile model for auto-apply form filling."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class PersonalInfo(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: str
    linkedin: str = ""
    portfolio: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    country: str = ""


class Experience(BaseModel):
    company: str
    title: str
    start_date: str
    end_date: str = "Present"
    description: str = ""
    location: str = ""


class Education(BaseModel):
    institution: str
    degree: str
    field_of_study: str = Field(alias="field", default="")
    graduation_year: str = ""
    gpa: str = ""

    model_config = {"populate_by_name": True}


class ApplicantProfile(BaseModel):
    """Full applicant profile used by form-filling agents."""

    personal_info: PersonalInfo
    resume_path: str = ""
    cover_letter_path: str = ""
    experience: list[Experience] = []
    education: list[Education] = []
    skills: list[str] = []
    certifications: list[str] = []
    languages: list[str] = ["English"]
    standard_questions: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> ApplicantProfile:
        p = Path(path)
        if not p.is_absolute():
            p = p.resolve()
        if not p.exists():
            raise FileNotFoundError(f"Profile file not found: {p}")
        data = json.loads(p.read_text())
        return cls(**data)

    def to_context_string(self) -> str:
        """Flatten the profile into a readable string for LLM context."""
        pi = self.personal_info
        lines = [
            "=== APPLICANT PROFILE ===",
            f"Name: {pi.first_name} {pi.last_name}",
            f"Email: {pi.email}",
            f"Phone: {pi.phone}",
        ]
        if pi.linkedin:
            lines.append(f"LinkedIn: {pi.linkedin}")
        if pi.portfolio:
            lines.append(f"Portfolio: {pi.portfolio}")
        if pi.address:
            addr_parts = [pi.address, pi.city, pi.state, pi.zip_code, pi.country]
            lines.append(f"Address: {', '.join(p for p in addr_parts if p)}")

        if self.skills:
            lines.append(f"\nSkills: {', '.join(self.skills)}")
        if self.languages:
            lines.append(f"Languages: {', '.join(self.languages)}")
        if self.certifications:
            lines.append(f"Certifications: {', '.join(self.certifications)}")

        if self.experience:
            lines.append("\n--- Work Experience ---")
            for exp in self.experience:
                lines.append(
                    f"  {exp.title} at {exp.company} ({exp.start_date} - {exp.end_date})"
                )
                if exp.description:
                    lines.append(f"    {exp.description[:200]}")

        if self.education:
            lines.append("\n--- Education ---")
            for edu in self.education:
                lines.append(
                    f"  {edu.degree} in {edu.field_of_study} from {edu.institution}"
                    f" ({edu.graduation_year})"
                )

        if self.standard_questions:
            lines.append("\n--- Pre-answered Questions ---")
            for q, a in self.standard_questions.items():
                lines.append(f"  {q}: {a}")

        lines.append(f"\nResume file: {self.resume_path or 'Not provided'}")
        if self.cover_letter_path:
            lines.append(f"Cover letter file: {self.cover_letter_path}")

        return "\n".join(lines)
