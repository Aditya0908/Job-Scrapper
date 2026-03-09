"""Apply Agent — The 'Hands' that execute browser actions to fill forms.

Uses Playwright's native locator API for robust element finding and interaction,
with special handling for LinkedIn Easy Apply modals and external career portals.
"""

from __future__ import annotations

import platform
import random
from pathlib import Path
from typing import TYPE_CHECKING

from auto_apply.state import ActionResult, ApplicationState, FieldType, FormField
from utils.stealth import human_delay

if TYPE_CHECKING:
    from auto_apply.profile import ApplicantProfile
    from playwright.async_api import BrowserContext, Page

_IS_MAC = platform.system() == "Darwin"
_SELECT_ALL_KEY = "Meta+A" if _IS_MAC else "Control+A"


class ApplyAgent:
    """Executes physical browser actions: typing, clicking, selecting, uploading."""

    # ── High-level actions ──────────────────────────────────────────────

    async def click_apply_button(
        self, page: "Page", ctx: "BrowserContext"
    ) -> tuple[str, "Page"]:
        """Find and click the Apply / Easy Apply button on a job listing page.

        Returns:
            (apply_type, active_page)
            apply_type: "easy_apply" | "external" | "not_found"
            active_page: the page to use for subsequent operations
                         (may be a new tab for external apply)
        """
        pages_before = set(ctx.pages)

        # Strategy 1: LinkedIn-specific button class
        li_btn = page.locator("button.jobs-apply-button")
        if await li_btn.count() > 0:
            await li_btn.first.click()
            return await self._resolve_after_apply_click(page, ctx, pages_before)

        # Strategy 2: role-based with fuzzy text matching
        for label in ["Easy Apply", "Apply Now", "Apply on company website", "Apply"]:
            btn = page.get_by_role("button", name=label, exact=False)
            if await btn.count() > 0:
                await btn.first.click()
                return await self._resolve_after_apply_click(page, ctx, pages_before)

        # Strategy 3: link-based apply buttons (some sites use <a>)
        for label in ["Apply", "Apply Now"]:
            link = page.get_by_role("link", name=label, exact=False)
            if await link.count() > 0:
                await link.first.click()
                return await self._resolve_after_apply_click(page, ctx, pages_before)

        return "not_found", page

    async def click_next_or_submit(
        self, page: "Page", state: ApplicationState
    ) -> tuple[str, bool]:
        """Find and click the next navigation button inside the current form.

        Uses a waterfall of strategies: LinkedIn data-attribute -> role-based ->
        text-based -> CSS patterns.

        Returns:
            (button_kind, success)
            button_kind: "next" | "review" | "submit" | "not_found"
        """
        modal_sel = state.metadata.get("modal_selector")
        scope = page.locator(modal_sel) if modal_sel else page

        # Strategy 1: LinkedIn Easy Apply data attribute (covers Next/Review/Submit)
        ea_btn = scope.locator("[data-easy-apply-next-button]")
        if await ea_btn.count() > 0:
            btn = ea_btn.first
            text = (await btn.text_content() or "").strip().lower()
            try:
                await btn.scroll_into_view_if_needed()
                await human_delay(0.3, 0.6)
                await btn.click()
                await human_delay(1.0, 2.5)
                kind = _classify_button_text(text)
                return kind, True
            except Exception:
                pass

        # Strategy 2: role=button with known names
        button_names = [
            ("Submit application", "submit"),
            ("Submit", "submit"),
            ("Apply", "submit"),
            ("Finish", "submit"),
            ("Send application", "submit"),
            ("Review your application", "review"),
            ("Review", "review"),
            ("Next", "next"),
            ("Continue", "next"),
            ("Save and continue", "next"),
            ("Proceed", "next"),
        ]
        for name, kind in button_names:
            btn = scope.get_by_role("button", name=name, exact=False)
            if await btn.count() > 0:
                first = btn.first
                if await first.is_visible():
                    try:
                        await first.scroll_into_view_if_needed()
                        await human_delay(0.2, 0.5)
                        await first.click()
                        await human_delay(1.0, 2.5)
                        return kind, True
                    except Exception:
                        continue

        # Strategy 3: CSS patterns for common ATS systems (Lever, Greenhouse, etc.)
        css_patterns = [
            ('button[type="submit"]', "submit"),
            ('input[type="submit"]', "submit"),
            ("button.btn-primary", None),
            ("button.artdeco-button--primary", None),
            (".application-form button[type='submit']", "submit"),
        ]
        for sel, kind in css_patterns:
            btn = scope.locator(sel)
            if await btn.count() > 0:
                first = btn.first
                if await first.is_visible():
                    text = (await first.text_content() or "").strip().lower()
                    resolved_kind = kind or _classify_button_text(text)
                    try:
                        await first.scroll_into_view_if_needed()
                        await human_delay(0.2, 0.5)
                        await first.click()
                        await human_delay(1.0, 2.5)
                        return resolved_kind, True
                    except Exception:
                        continue

        # Strategy 4: Broad text-based search as last resort
        for text_pattern, kind in [("submit", "submit"), ("next", "next"), ("continue", "next")]:
            btn = scope.locator(f"button:has-text('{text_pattern}')")
            if await btn.count() > 0:
                first = btn.first
                if await first.is_visible():
                    try:
                        await first.click()
                        await human_delay(1.0, 2.5)
                        return kind, True
                    except Exception:
                        continue

        return "not_found", False

    async def fill_all_fields(
        self,
        page: "Page",
        state: ApplicationState,
        profile: "ApplicantProfile",
    ) -> ApplicationState:
        """Fill all unfilled form fields on the current page."""
        unfilled = state.unfilled_fields
        state.log(f"[ApplyAgent] Filling {len(unfilled)} fields...")
        state.failed_fields = []

        for field in unfilled:
            result = await self._fill_field(page, field, profile, state)
            state.record_action(result)
            if not result.success:
                state.failed_fields.append(field.selector)
                state.log(
                    f"[ApplyAgent] FAILED: {field.label} ({field.selector}) — {result.error}"
                )
            else:
                state.log(f"[ApplyAgent] Filled: {field.label}")
            await human_delay(0.3, 0.8)

        return state

    async def click_button(self, page: "Page", selector: str) -> bool:
        """Click a button by selector string (legacy/generic fallback)."""
        try:
            loc = page.locator(selector)
            if await loc.count() > 0:
                await loc.first.scroll_into_view_if_needed()
                await human_delay(0.2, 0.4)
                await loc.first.click()
                await human_delay(1.0, 2.5)
                return True
        except Exception:
            pass

        try:
            await page.locator(selector).first.evaluate("node => node.click()")
            await human_delay(1.0, 2.5)
            return True
        except Exception:
            return False

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _resolve_after_apply_click(
        self, page: "Page", ctx: "BrowserContext", pages_before: set
    ) -> tuple[str, "Page"]:
        """After clicking apply, detect whether a modal or new tab appeared."""
        await human_delay(2.0, 4.0)

        new_pages = set(ctx.pages) - pages_before
        if new_pages:
            new_page = new_pages.pop()
            try:
                await new_page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            await human_delay(1.5, 3.0)
            return "external", new_page

        # No new tab -- expect an Easy Apply modal or same-page form
        modal_appeared = False
        for sel in [".jobs-easy-apply-modal", ".artdeco-modal", '[role="dialog"]']:
            if await page.locator(sel).count() > 0:
                modal_appeared = True
                break

        if not modal_appeared:
            try:
                await page.wait_for_selector(
                    '.jobs-easy-apply-modal, .artdeco-modal, [role="dialog"]',
                    timeout=8000,
                )
            except Exception:
                pass

        return "easy_apply", page

    async def _fill_field(
        self,
        page: "Page",
        field: FormField,
        profile: "ApplicantProfile",
        state: ApplicationState,
    ) -> ActionResult:
        """Fill a single form field based on its type."""
        modal_sel = state.metadata.get("modal_selector")
        scope = page.locator(modal_sel) if modal_sel else page

        try:
            if field.field_type == FieldType.FILE:
                return await self._handle_file_upload(scope, page, field, profile)
            elif field.field_type == FieldType.SELECT:
                return await self._handle_select(scope, field)
            elif field.field_type in (FieldType.RADIO, FieldType.CHECKBOX):
                return await self._handle_check(scope, field)
            elif field.field_type == FieldType.TEXTAREA:
                return await self._handle_textarea(scope, page, field)
            else:
                return await self._handle_text_input(scope, page, field)
        except Exception as e:
            return ActionResult(False, field.selector, "fill", str(e))

    async def _find_element(self, scope, page: "Page", selector: str):
        """Find an element within the scope, with fallbacks."""
        try:
            loc = scope.locator(selector)
            if await loc.count() > 0:
                el = loc.first
                if await el.is_visible():
                    return el
        except Exception:
            pass

        try:
            el = await page.wait_for_selector(selector, timeout=3000, state="visible")
            return el
        except Exception:
            pass

        try:
            return await page.query_selector(selector)
        except Exception:
            return None

    async def _handle_text_input(self, scope, page: "Page", field: FormField) -> ActionResult:
        el = await self._find_element(scope, page, field.selector)
        if not el:
            return ActionResult(False, field.selector, "type", "Element not found")

        try:
            await el.click()
            await human_delay(0.1, 0.3)
            await page.keyboard.press(_SELECT_ALL_KEY)
            await page.keyboard.press("Backspace")
            await human_delay(0.1, 0.2)
            await el.type(field.value, delay=random.randint(30, 100))
            await human_delay(0.2, 0.5)
            return ActionResult(True, field.selector, "type")
        except Exception:
            try:
                await el.fill(field.value)
                return ActionResult(True, field.selector, "fill")
            except Exception as e:
                return ActionResult(False, field.selector, "type", str(e))

    async def _handle_textarea(self, scope, page: "Page", field: FormField) -> ActionResult:
        el = await self._find_element(scope, page, field.selector)
        if not el:
            return ActionResult(False, field.selector, "type", "Textarea not found")

        try:
            await el.click()
            await human_delay(0.2, 0.4)
            await el.fill("")
            await el.type(field.value, delay=random.randint(15, 60))
            await human_delay(0.3, 0.6)
            return ActionResult(True, field.selector, "type")
        except Exception as e:
            return ActionResult(False, field.selector, "type", str(e))

    async def _handle_select(self, scope, field: FormField) -> ActionResult:
        try:
            loc = scope.locator(field.selector)
            if await loc.count() == 0:
                return ActionResult(False, field.selector, "select", "Select not found")
            el = loc.first

            options = await el.locator("option").all()
            best_match = None
            value_lower = field.value.lower()

            for opt in options:
                text = (await opt.text_content() or "").strip()
                val = await opt.get_attribute("value") or ""
                if text.lower() == value_lower or val.lower() == value_lower:
                    best_match = val or text
                    break

            if not best_match:
                for opt in options:
                    text = (await opt.text_content() or "").strip()
                    val = await opt.get_attribute("value") or ""
                    if value_lower in text.lower() or value_lower in val.lower():
                        best_match = val or text
                        break

            if not best_match and options:
                for opt in options:
                    val = await opt.get_attribute("value") or ""
                    text = (await opt.text_content() or "").strip()
                    if val and val.strip() and text.strip():
                        best_match = val
                        break

            if best_match:
                await el.select_option(value=best_match)
                await human_delay(0.3, 0.7)
                return ActionResult(True, field.selector, "select")
            else:
                return ActionResult(
                    False, field.selector, "select",
                    f"No matching option for '{field.value}'",
                )
        except Exception as e:
            return ActionResult(False, field.selector, "select", str(e))

    async def _handle_check(self, scope, field: FormField) -> ActionResult:
        try:
            loc = scope.locator(field.selector)
            if await loc.count() == 0:
                return ActionResult(False, field.selector, "check", "Element not found")
            el = loc.first

            should_check = field.value.lower() in ("true", "yes", "1", "checked")
            is_checked = await el.is_checked()

            if should_check != is_checked:
                await el.click()
                await human_delay(0.2, 0.5)

            return ActionResult(True, field.selector, "check")
        except Exception as e:
            return ActionResult(False, field.selector, "check", str(e))

    async def _handle_file_upload(
        self, scope, page: "Page", field: FormField, profile: "ApplicantProfile"
    ) -> ActionResult:
        if field.value == "resume":
            file_path = profile.resume_path
        elif field.value == "cover_letter":
            file_path = profile.cover_letter_path
        else:
            file_path = field.value

        if not file_path or not Path(file_path).exists():
            return ActionResult(
                False, field.selector, "upload", f"File not found: {file_path}"
            )

        try:
            loc = scope.locator(field.selector)
            if await loc.count() == 0:
                loc = page.locator(field.selector)
            if await loc.count() == 0:
                return ActionResult(False, field.selector, "upload", "File input not found")

            await loc.first.set_input_files(str(Path(file_path).resolve()))
            await human_delay(1.0, 2.0)
            return ActionResult(True, field.selector, "upload")
        except Exception as e:
            return ActionResult(False, field.selector, "upload", str(e))


def _classify_button_text(text: str) -> str:
    """Classify button text into next/review/submit."""
    t = text.lower()
    if any(w in t for w in ("submit", "apply", "finish", "send")):
        return "submit"
    if "review" in t:
        return "review"
    return "next"
