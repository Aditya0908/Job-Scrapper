"""State machine definitions for the auto-apply workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Phase(str, Enum):
    """Phases of the auto-apply state machine."""

    INIT = "init"
    CLICK_APPLY = "click_apply"
    ANALYZE_PAGE = "analyze_page"
    FILL_FORM = "fill_form"
    HANDLE_ERROR = "handle_error"
    NAVIGATE_NEXT = "navigate_next"
    REVIEW = "review"
    SUBMIT = "submit"
    DONE = "done"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (Phase.DONE, Phase.FAILED)


class FieldType(str, Enum):
    TEXT = "text"
    EMAIL = "email"
    TEL = "tel"
    URL = "url"
    NUMBER = "number"
    TEXTAREA = "textarea"
    SELECT = "select"
    RADIO = "radio"
    CHECKBOX = "checkbox"
    FILE = "file"
    DATE = "date"
    HIDDEN = "hidden"
    PASSWORD = "password"


@dataclass
class FormField:
    """A single form field extracted from the page."""

    selector: str
    field_type: FieldType
    label: str
    value: str = ""
    options: list[str] = field(default_factory=list)
    required: bool = False
    placeholder: str = ""
    name: str = ""
    current_value: str = ""


@dataclass
class ActionResult:
    """Result of a single browser action."""

    success: bool
    selector: str
    action: str
    error: str = ""


@dataclass
class ApplicationState:
    """Full state of an in-progress job application."""

    job_url: str
    phase: Phase = Phase.INIT
    form_fields: list[FormField] = field(default_factory=list)
    filled_fields: set[str] = field(default_factory=set)
    failed_fields: list[str] = field(default_factory=list)
    action_history: list[ActionResult] = field(default_factory=list)

    current_page: int = 1
    total_pages: int = 1
    page_html: str = ""
    page_url: str = ""

    error_count: int = 0
    max_errors: int = 15
    consecutive_errors: int = 0

    is_submitted: bool = False
    logs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def log(self, msg: str) -> None:
        self.logs.append(msg)

    def record_action(self, result: ActionResult) -> None:
        self.action_history.append(result)
        if result.success:
            self.filled_fields.add(result.selector)
            self.consecutive_errors = 0
        else:
            self.error_count += 1
            self.consecutive_errors += 1

    @property
    def unfilled_fields(self) -> list[FormField]:
        return [f for f in self.form_fields if f.selector not in self.filled_fields]

    @property
    def should_abort(self) -> bool:
        return (
            self.error_count >= self.max_errors
            or self.consecutive_errors >= 5
        )

    @property
    def progress_summary(self) -> str:
        total = len(self.form_fields)
        filled = len(self.filled_fields)
        return (
            f"Page {self.current_page}/{self.total_pages} | "
            f"Fields: {filled}/{total} filled | "
            f"Errors: {self.error_count} | "
            f"Phase: {self.phase.value}"
        )
