"""Planner Agent — Orchestrator that decides the next phase of the application workflow."""

from __future__ import annotations

from auto_apply.llm import LLMClient
from auto_apply.state import ApplicationState, Phase


class PlannerAgent:
    """Decides the next phase transition in the state machine.

    Uses deterministic heuristics for common transitions and falls back
    to LLM only when the state is ambiguous.
    """

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def decide_next_phase(self, state: ApplicationState) -> Phase:
        """Analyze current state and return the next phase."""

        if state.should_abort:
            state.log("[Planner] Too many errors — aborting.")
            return Phase.FAILED

        if state.phase == Phase.INIT:
            return Phase.CLICK_APPLY

        if state.phase == Phase.CLICK_APPLY:
            return Phase.ANALYZE_PAGE

        if state.phase == Phase.ANALYZE_PAGE:
            if state.form_fields:
                return Phase.FILL_FORM
            click_count = state.metadata.get("click_apply_count", 0)
            if click_count < 3:
                state.log("[Planner] No form fields found — retrying CLICK_APPLY.")
                return Phase.CLICK_APPLY
            state.log("[Planner] No form fields found after multiple attempts.")
            return Phase.FAILED

        if state.phase == Phase.FILL_FORM:
            if state.failed_fields and state.consecutive_errors < 5:
                return Phase.HANDLE_ERROR
            # All fillable fields handled -> navigate/submit
            return Phase.NAVIGATE_NEXT

        if state.phase == Phase.HANDLE_ERROR:
            if state.should_abort:
                return Phase.FAILED
            if state.unfilled_fields:
                return Phase.FILL_FORM
            return Phase.NAVIGATE_NEXT

        if state.phase == Phase.NAVIGATE_NEXT:
            # Runner handles the actual click and sets phase directly
            # If we reach here, it means runner didn't override -> re-analyze
            return Phase.ANALYZE_PAGE

        if state.phase == Phase.REVIEW:
            return Phase.SUBMIT

        if state.phase == Phase.SUBMIT:
            if state.is_submitted:
                return Phase.DONE
            return Phase.FAILED

        return Phase.FAILED
