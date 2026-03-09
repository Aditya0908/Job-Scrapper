"""Form-Understanding Agent — The 'Brain' that maps HTML fields to profile data via LLM.

Scopes extraction to the active modal/dialog when present (critical for LinkedIn
Easy Apply where the full page has hundreds of irrelevant elements).
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from auto_apply.html_cleaner import clean_html, extract_form_fields
from auto_apply.llm import LLMClient
from auto_apply.state import ApplicationState, FieldType, FormField

if TYPE_CHECKING:
    from auto_apply.profile import ApplicantProfile
    from playwright.async_api import Page

_MODAL_SELECTORS = [
    ".jobs-easy-apply-modal",
    ".artdeco-modal",
    '[role="dialog"]',
    ".modal.show",
    ".modal.is-open",
]

_SYSTEM = """\
You are a Form-Understanding Agent. Your job is to analyze HTML form fields and determine
what value from the applicant's profile should fill each field.

RULES:
1. Match each field to the most appropriate value from the applicant profile.
2. For text/email/tel/url fields: provide the exact value to type.
3. For select fields: pick the closest matching option from the available options list.
   Return the EXACT option text or value.
4. For radio/checkbox fields: pick "true" or "false" (whether it should be checked).
5. For file fields: provide "resume" if it's a resume upload, "cover_letter" if cover letter,
   or "skip" if unclear.
6. For textarea fields (like "Why do you want this job?"): generate a concise, professional
   2-3 sentence response using the applicant's profile context.
7. If a field cannot be mapped to any profile data, set value to "SKIP".
8. For date fields, use YYYY-MM-DD format.
9. For standard questions (sponsorship, notice period, salary, etc.), use the pre-answered values.
10. If a field already has a value (current_value is non-empty) and looks correct, set value to "SKIP"
    to avoid overwriting pre-filled data.

Respond with ONLY a JSON array of objects:
[
  {"selector": "<css_selector>", "value": "<value_to_fill>", "action": "<type|select|check|upload|skip>"},
  ...
]

IMPORTANT: Only output valid JSON, no markdown fences or extra text.
"""


class FormAnalyzerAgent:
    """Analyzes the current page and maps form fields to profile values."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def analyze(
        self,
        page: "Page",
        state: ApplicationState,
        profile: "ApplicantProfile",
    ) -> ApplicationState:
        """Scrape the page HTML, extract fields, and use LLM to map values."""

        state.log("[FormAnalyzer] Fetching page HTML...")

        # Detect and scope to modal if present
        modal_selector = await self._detect_modal(page)
        state.metadata["modal_selector"] = modal_selector

        raw_html = await self._get_scoped_html(page, modal_selector)
        if raw_html is None:
            state.form_fields = []
            return state

        state.page_html = raw_html
        state.page_url = page.url

        extracted = extract_form_fields(raw_html)
        if not extracted:
            state.log("[FormAnalyzer] No form fields found on page.")
            state.form_fields = []
            return state

        state.log(f"[FormAnalyzer] Extracted {len(extracted)} form fields.")

        if modal_selector:
            state.log(f"[FormAnalyzer] Scoped to modal: {modal_selector}")

        cleaned = clean_html(raw_html)
        field_mappings = await self._map_fields_via_llm(extracted, cleaned, profile, state)

        form_fields: list[FormField] = []
        for ext, mapping in zip(extracted, field_mappings):
            value = mapping.get("value", "SKIP") if mapping else "SKIP"
            action = mapping.get("action", "skip") if mapping else "skip"

            if value == "SKIP" or action == "skip":
                if ext.get("required"):
                    state.log(
                        f"[FormAnalyzer] WARNING: Required field '{ext['label']}' has no mapping."
                    )
                continue

            try:
                ft = FieldType(ext["field_type"])
            except ValueError:
                ft = FieldType.TEXT

            form_fields.append(FormField(
                selector=ext["selector"],
                field_type=ft,
                label=ext["label"],
                value=value,
                options=ext.get("options", []),
                required=ext.get("required", False),
                placeholder=ext.get("placeholder", ""),
                name=ext.get("name", ""),
                current_value=ext.get("current_value", ""),
            ))

        state.form_fields = form_fields
        state.log(f"[FormAnalyzer] Mapped {len(form_fields)} fields for filling.")
        return state

    async def _detect_modal(self, page: "Page") -> str | None:
        """Check if a modal/dialog is open and return its selector."""
        for sel in _MODAL_SELECTORS:
            try:
                loc = page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible():
                    return sel
            except Exception:
                continue
        return None

    async def _get_scoped_html(self, page: "Page", modal_selector: str | None) -> str | None:
        """Get HTML from the modal if present, otherwise from the full page."""
        for attempt in range(3):
            try:
                if modal_selector:
                    loc = page.locator(modal_selector).first
                    return await loc.inner_html()
                else:
                    return await page.content()
            except Exception as e:
                if "navigating" in str(e).lower() and attempt < 2:
                    await asyncio.sleep(2)
                else:
                    return None
        return None

    async def _map_fields_via_llm(
        self,
        fields: list[dict],
        cleaned_html: str,
        profile: "ApplicantProfile",
        state: ApplicationState,
    ) -> list[dict | None]:
        """Ask the LLM to map extracted fields to profile values."""
        fields_summary = json.dumps(fields, indent=2, default=str)

        prompt = (
            f"=== APPLICANT PROFILE ===\n"
            f"{profile.to_context_string()}\n\n"
            f"=== FORM FIELDS (extracted) ===\n"
            f"{fields_summary}\n\n"
            f"=== CLEANED PAGE HTML (for context) ===\n"
            f"{cleaned_html[:8000]}\n\n"
            f"Map each field to the appropriate profile value. "
            f"Return a JSON array with one entry per field (same order as the fields above)."
        )

        try:
            result = await self.llm.generate_json(prompt, system=_SYSTEM)
            if isinstance(result, list):
                while len(result) < len(fields):
                    result.append(None)
                return result[: len(fields)]
            state.log("[FormAnalyzer] LLM returned unexpected format, using fallback.")
            return self._fallback_mapping(fields, profile)
        except Exception as e:
            state.log(f"[FormAnalyzer] LLM mapping failed: {e}")
            return self._fallback_mapping(fields, profile)

    def _fallback_mapping(
        self, fields: list[dict], profile: "ApplicantProfile"
    ) -> list[dict | None]:
        """Rule-based fallback when LLM is unavailable."""
        pi = profile.personal_info
        keyword_map = {
            "first_name": pi.first_name,
            "firstname": pi.first_name,
            "first name": pi.first_name,
            "fname": pi.first_name,
            "given name": pi.first_name,
            "last_name": pi.last_name,
            "lastname": pi.last_name,
            "last name": pi.last_name,
            "lname": pi.last_name,
            "family name": pi.last_name,
            "surname": pi.last_name,
            "email": pi.email,
            "e-mail": pi.email,
            "phone": pi.phone,
            "telephone": pi.phone,
            "mobile": pi.phone,
            "cell": pi.phone,
            "linkedin": pi.linkedin,
            "portfolio": pi.portfolio,
            "website": pi.portfolio,
            "city": pi.city,
            "state": pi.state,
            "zip": pi.zip_code,
            "postal": pi.zip_code,
            "country": pi.country,
        }

        results: list[dict | None] = []
        for f in fields:
            label_lower = f.get("label", "").lower()
            name_lower = f.get("name", "").lower()
            placeholder_lower = f.get("placeholder", "").lower()
            combined = f"{label_lower} {name_lower} {placeholder_lower}"

            matched = None
            for keyword, value in keyword_map.items():
                if keyword in combined and value:
                    action = "type"
                    if f["field_type"] == "select":
                        action = "select"
                    elif f["field_type"] in ("radio", "checkbox"):
                        action = "check"
                    elif f["field_type"] == "file":
                        action = "upload"
                    matched = {"selector": f["selector"], "value": value, "action": action}
                    break

            if not matched and f["field_type"] == "file":
                if profile.resume_path:
                    matched = {"selector": f["selector"], "value": "resume", "action": "upload"}

            if not matched and f.get("current_value"):
                matched = {"selector": f["selector"], "value": "SKIP", "action": "skip"}

            results.append(matched)

        return results
