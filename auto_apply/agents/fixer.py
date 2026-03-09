"""Error Recovery Agent — The 'Fixer' that resolves browser errors, pop-ups, and validation issues."""

from __future__ import annotations

from typing import TYPE_CHECKING

from auto_apply.html_cleaner import clean_html
from auto_apply.llm import LLMClient
from auto_apply.state import ActionResult, ApplicationState
from utils.stealth import human_delay

if TYPE_CHECKING:
    from playwright.async_api import Page

_SYSTEM = """\
You are the Error Recovery Agent in a job application automation system.
You analyze DOM state and error messages to suggest fixes for failed form interactions.

When analyzing errors, suggest ONE of these recovery actions:
- dismiss_overlay: A pop-up, modal, or overlay is blocking the form. Provide a selector to close it.
- scroll_to: The element is not visible. Provide the selector to scroll to.
- iframe_switch: The form is inside an iframe. Provide the iframe selector.
- retry_with_js: Direct interaction failed. Provide JavaScript code to fill the field.
- clear_and_retry: The field has stale/wrong value. Clear it first, then retry.
- use_alternative_selector: The original selector failed. Provide an alternative selector.
- accept_cookies: A cookie banner is blocking. Provide the accept button selector.
- skip: The field cannot be recovered; skip it.

Respond with ONLY valid JSON:
{"action": "<action_type>", "selector": "<target_selector>", "js_code": "<optional JS>", "reason": "<brief explanation>"}
"""


class FixerAgent:
    """Diagnoses and fixes errors during form filling."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def fix(self, page: "Page", state: ApplicationState) -> ApplicationState:
        """Attempt to fix all current errors."""
        state.log(f"[Fixer] Attempting recovery for {len(state.failed_fields)} failed fields...")

        await self._dismiss_common_overlays(page, state)

        remaining_failures: list[str] = []
        for selector in state.failed_fields:
            fixed = await self._attempt_fix(page, selector, state)
            if not fixed:
                remaining_failures.append(selector)

        state.failed_fields = remaining_failures
        if remaining_failures:
            state.log(f"[Fixer] {len(remaining_failures)} fields still failing after recovery.")
        else:
            state.log("[Fixer] All errors resolved.")

        return state

    async def _dismiss_common_overlays(self, page: "Page", state: ApplicationState) -> None:
        """Try to dismiss common overlays: cookie banners, modals, chat widgets."""
        overlay_selectors = [
            '[class*="cookie"] button[class*="accept"]',
            '[class*="cookie"] button[class*="agree"]',
            '[id*="cookie"] button',
            '[class*="consent"] button[class*="accept"]',
            'button[class*="close-modal"]',
            '[class*="modal"] button[class*="close"]',
            '[class*="overlay"] button[class*="close"]',
            '[class*="popup"] button[class*="close"]',
            '[aria-label="Close"]',
            '[aria-label="close"]',
            'button[class*="dismiss"]',
        ]

        for sel in overlay_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    state.log(f"[Fixer] Dismissed overlay: {sel}")
                    await human_delay(0.5, 1.0)
            except Exception:
                continue

    async def _attempt_fix(
        self, page: "Page", selector: str, state: ApplicationState
    ) -> bool:
        """Use LLM to diagnose and fix a specific failed field."""
        last_error = ""
        for action in reversed(state.action_history):
            if action.selector == selector and not action.success:
                last_error = action.error
                break

        field_info = None
        for f in state.form_fields:
            if f.selector == selector:
                field_info = f
                break

        if not field_info:
            return False

        region_html = await self._get_element_region(page, selector)

        prompt = (
            f"Failed to interact with form field:\n"
            f"  Selector: {selector}\n"
            f"  Field type: {field_info.field_type.value}\n"
            f"  Label: {field_info.label}\n"
            f"  Value to fill: {field_info.value}\n"
            f"  Error: {last_error}\n\n"
            f"Surrounding HTML:\n{region_html[:3000]}\n\n"
            f"Suggest a recovery action."
        )

        try:
            fix = await self.llm.generate_json(prompt, system=_SYSTEM)
        except Exception as e:
            state.log(f"[Fixer] LLM analysis failed: {e}")
            return False

        action = fix.get("action", "skip")
        reason = fix.get("reason", "")
        state.log(f"[Fixer] Diagnosis for '{field_info.label}': {action} — {reason}")

        return await self._execute_fix(page, fix, field_info, state)

    async def _execute_fix(
        self, page: "Page", fix: dict, field, state: ApplicationState
    ) -> bool:
        """Execute the LLM-suggested fix action."""
        action = fix.get("action", "skip")
        target_sel = fix.get("selector", field.selector)

        try:
            if action == "dismiss_overlay":
                el = await page.query_selector(target_sel)
                if el:
                    await el.click()
                    await human_delay(0.5, 1.0)
                    state.log(f"[Fixer] Dismissed overlay: {target_sel}")
                    state.filled_fields.discard(field.selector)
                    return True

            elif action == "scroll_to":
                await page.evaluate(
                    f'document.querySelector("{_escape_js(target_sel)}")?.scrollIntoView({{behavior:"smooth",block:"center"}})'
                )
                await human_delay(0.5, 1.0)
                state.filled_fields.discard(field.selector)
                return True

            elif action == "iframe_switch":
                frames = page.frames
                for frame in frames:
                    try:
                        el = await frame.query_selector(field.selector)
                        if el:
                            await el.fill(field.value)
                            state.record_action(
                                ActionResult(True, field.selector, "fill_iframe")
                            )
                            return True
                    except Exception:
                        continue

            elif action == "retry_with_js":
                js_code = fix.get("js_code", "")
                if js_code:
                    await page.evaluate(js_code)
                    await human_delay(0.3, 0.6)
                    state.record_action(
                        ActionResult(True, field.selector, "js_fill")
                    )
                    return True

            elif action == "clear_and_retry":
                el = await page.query_selector(field.selector)
                if el:
                    await el.fill("")
                    await human_delay(0.2, 0.4)
                    await el.type(field.value, delay=50)
                    state.record_action(
                        ActionResult(True, field.selector, "clear_retry")
                    )
                    return True

            elif action == "use_alternative_selector":
                alt_sel = fix.get("selector", "")
                if alt_sel:
                    el = await page.query_selector(alt_sel)
                    if el:
                        await el.fill(field.value)
                        state.record_action(
                            ActionResult(True, field.selector, "alt_selector")
                        )
                        return True

            elif action == "accept_cookies":
                el = await page.query_selector(target_sel)
                if el:
                    await el.click()
                    await human_delay(0.5, 1.0)
                    state.filled_fields.discard(field.selector)
                    return True

            elif action == "skip":
                state.log(f"[Fixer] Skipping unrecoverable field: {field.label}")
                state.filled_fields.add(field.selector)
                return True

        except Exception as e:
            state.log(f"[Fixer] Fix execution failed: {e}")

        return False

    async def _get_element_region(self, page: "Page", selector: str) -> str:
        """Get the HTML around a specific element for context."""
        try:
            html = await page.evaluate(f"""() => {{
                const el = document.querySelector("{_escape_js(selector)}");
                if (!el) return "<element not found>";
                let parent = el.parentElement;
                for (let i = 0; i < 3 && parent && parent.tagName !== 'BODY'; i++) {{
                    parent = parent.parentElement;
                }}
                return (parent || el).outerHTML;
            }}""")
            return clean_html(html) if html else "<no HTML>"
        except Exception:
            return "<failed to extract HTML>"


def _escape_js(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')
