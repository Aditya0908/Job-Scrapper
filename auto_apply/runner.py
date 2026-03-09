"""Main orchestration loop for the auto-apply system.

Implements the state machine for LinkedIn Easy Apply:
  INIT -> CLICK_APPLY -> ANALYZE_PAGE -> FILL_FORM -> NAVIGATE_NEXT -> ... -> DONE

Only supports LinkedIn Easy Apply (modal-based forms).
External/company-portal jobs are detected and skipped immediately.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from auto_apply.agents.applier import ApplyAgent
from auto_apply.agents.fixer import FixerAgent
from auto_apply.agents.form_analyzer import FormAnalyzerAgent
from auto_apply.agents.planner import PlannerAgent
from auto_apply.llm import LLMClient
from auto_apply.profile import ApplicantProfile
from auto_apply.state import ApplicationState, Phase
from utils.stealth import StealthBrowser, human_delay

console = Console()

MAX_ITERATIONS = 40

_AUTH_SIGNALS = (
    "login", "signin", "sign-in", "sign_in", "auth", "oauth", "sso",
    "b2clogin", "accounts.google", "account.", "oidc", "saml",
)


async def auto_apply(
    job_url: str,
    profile_path: str,
    headless: bool = True,
    dry_run: bool = False,
    site_name: str = "apply",
) -> ApplicationState:
    """Run the auto-apply agent system on a single job URL.

    Args:
        job_url:      The job application page URL.
        profile_path: Path to the user_profile.json file.
        headless:     Run browser in headless mode.
        dry_run:      If True, stop before actually submitting (review only).
        site_name:    Site name for session reuse (e.g. "linkedin", "indeed").

    Returns:
        Final ApplicationState with logs and status.
    """
    profile = ApplicantProfile.from_file(profile_path)
    state = ApplicationState(job_url=job_url)

    _print_header(profile, job_url, dry_run)

    llm = LLMClient()
    planner = PlannerAgent(llm)
    analyzer = FormAnalyzerAgent(llm)
    applier = ApplyAgent()
    fixer = FixerAgent(llm)

    browser = StealthBrowser(headless=headless)
    await browser.start()
    ctx = await browser.new_context(site_name)
    page = await browser.new_page(ctx)

    try:
        state.log(f"[Runner] Navigating to {job_url}")
        console.print(f"\n[cyan]Navigating to job page...[/cyan]")
        await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
        await human_delay(2.0, 4.0)
        state.page_url = page.url

        # Check if we landed on a login page
        if _is_auth_page(page.url):
            state.log(f"[Runner] Login required at {page.url}")
            console.print(
                "\n[yellow bold]Login required.[/yellow bold]\n"
                "[yellow]Run login_helper.py first to save a LinkedIn session,[/yellow]\n"
                f"[yellow]then re-run with --site {site_name}[/yellow]"
            )
            state.phase = Phase.FAILED
            _print_summary(state)
            await browser.close()
            await llm.close()
            return state

        iteration = 0
        while not state.phase.is_terminal and iteration < MAX_ITERATIONS:
            iteration += 1
            next_phase = await planner.decide_next_phase(state)
            state.phase = next_phase
            _print_phase(state, iteration)

            if next_phase == Phase.CLICK_APPLY:
                page = await _handle_click_apply(page, ctx, applier, state)

            elif next_phase == Phase.ANALYZE_PAGE:
                state = await analyzer.analyze(page, state, profile)

            elif next_phase == Phase.FILL_FORM:
                state = await applier.fill_all_fields(page, state, profile)

            elif next_phase == Phase.HANDLE_ERROR:
                state = await fixer.fix(page, state)

            elif next_phase == Phase.NAVIGATE_NEXT:
                await _handle_navigate_next(page, applier, state, dry_run)

            elif next_phase == Phase.REVIEW:
                _print_review(state)
                if dry_run:
                    state.log("[Runner] Dry run — stopping before submit.")
                    console.print("\n[yellow bold]DRY RUN: Skipping submission.[/yellow bold]")
                    state.phase = Phase.DONE

            elif next_phase == Phase.SUBMIT:
                await _handle_submit(page, applier, state)

            elif next_phase in (Phase.DONE, Phase.FAILED):
                break

        await browser.save_session(ctx, site_name)

    except Exception as e:
        state.phase = Phase.FAILED
        state.log(f"[Runner] Fatal error: {e}")
        console.print(f"\n[red bold]Fatal error: {e}[/red bold]")

    finally:
        await browser.close()
        await llm.close()

    _print_summary(state)
    return state


# ── Phase handlers ──────────────────────────────────────────────────────


async def _handle_click_apply(
    page, ctx, applier: ApplyAgent, state: ApplicationState
):
    """Handle the CLICK_APPLY phase. Returns the page to use going forward."""
    click_count = state.metadata.get("click_apply_count", 0)
    state.metadata["click_apply_count"] = click_count + 1

    console.print("  [cyan]Looking for Apply button...[/cyan]")
    apply_type, active_page = await applier.click_apply_button(page, ctx)

    if apply_type == "external":
        state.log(f"[Runner] External apply detected — not an Easy Apply job.")
        console.print(
            "\n  [yellow bold]This is NOT an Easy Apply job.[/yellow bold]\n"
            f"  [dim]External URL: {active_page.url}[/dim]\n"
            "  [yellow]Only LinkedIn Easy Apply is supported. Skipping.[/yellow]"
        )
        state.phase = Phase.FAILED
        return page

    elif apply_type == "easy_apply":
        state.log("[Runner] Easy Apply detected — waiting for modal...")

        # Wait explicitly for the Easy Apply modal to appear
        modal_found = False
        for sel in [".jobs-easy-apply-modal", ".artdeco-modal", '[role="dialog"]']:
            try:
                await page.wait_for_selector(sel, timeout=8000, state="visible")
                modal_found = True
                state.log(f"[Runner] Modal appeared: {sel}")
                break
            except Exception:
                continue

        if modal_found:
            console.print("  [green]Easy Apply modal opened.[/green]")
        else:
            console.print("  [yellow]Modal not detected — will try to analyze page anyway.[/yellow]")

        await human_delay(1.0, 2.0)
        state.page_url = page.url
        state.metadata["is_external"] = False
        return page

    else:
        state.log("[Runner] No apply button found — assuming already on form page.")
        return page


async def _handle_navigate_next(
    page, applier: ApplyAgent, state: ApplicationState, dry_run: bool
):
    """Handle NAVIGATE_NEXT: find and click the next/review/submit button.

    This is the key handler that makes multi-step forms work. It uses the
    applier's smart button detection to find whatever action button is available,
    then routes to the appropriate next phase.
    """
    state.log("[Runner] Looking for next/submit button...")
    console.print("  [cyan]Clicking next/submit...[/cyan]")

    button_kind, clicked = await applier.click_next_or_submit(page, state)

    if not clicked:
        state.log(
            "[Runner] Could not find Next/Review/Submit button in modal. "
            "Tried: aria-labels, data-easy-apply-next-button, footer primary button, getByRole, CSS."
        )
        console.print("  [red]No Next/Submit button found — will retry.[/red]")
        state.error_count += 1
        state.consecutive_errors += 1
        if state.consecutive_errors >= 3:
            state.phase = Phase.FAILED
            console.print("  [red bold]Giving up after 3 failed attempts to find the button.[/red bold]")
        return

    state.log(f"[Runner] Clicked '{button_kind}' button.")
    console.print(f"  [green]Clicked: {button_kind}[/green]")

    if button_kind == "submit":
        if dry_run:
            state.log("[Runner] Dry run — would have submitted here.")
            console.print("\n[yellow bold]DRY RUN: Would submit here.[/yellow bold]")
            _print_review(state)
            state.phase = Phase.DONE
        else:
            await human_delay(2.0, 4.0)
            state.is_submitted = True
            state.phase = Phase.DONE
            state.log("[Runner] Application submitted!")
            console.print("\n[bold green]Application submitted![/bold green]")

    elif button_kind in ("next", "review"):
        # Wait for new form content to load
        await _wait_for_form_transition(page, state)

        # Save progress from this page
        prev = state.metadata.setdefault("all_form_fields", [])
        prev.extend(state.form_fields)
        total = state.metadata.get("total_fields_filled", 0)
        state.metadata["total_fields_filled"] = total + len(state.filled_fields)
        prev_filled = state.metadata.setdefault("all_filled_selectors", set())
        prev_filled.update(state.filled_fields)

        state.current_page += 1
        state.form_fields = []
        state.filled_fields = set()
        state.consecutive_errors = 0

        # Go back to ANALYZE_PAGE for the new form step
        state.phase = Phase.ANALYZE_PAGE
        state.log(f"[Runner] Advanced to form page {state.current_page}.")


async def _handle_submit(page, applier: ApplyAgent, state: ApplicationState):
    """Handle the SUBMIT phase as a fallback (normally handled by NAVIGATE_NEXT)."""
    state.log("[Runner] Submit phase — trying to find submit button...")
    button_kind, clicked = await applier.click_next_or_submit(page, state)

    if clicked and button_kind == "submit":
        await human_delay(2.0, 4.0)
        state.is_submitted = True
        state.phase = Phase.DONE
        state.log("[Runner] Application submitted!")
        console.print("\n[bold green]Application submitted![/bold green]")
    elif clicked:
        state.log(f"[Runner] Found '{button_kind}' instead of submit — continuing.")
        state.phase = Phase.ANALYZE_PAGE
    else:
        state.log("[Runner] No submit button found.")
        state.error_count += 1


async def _wait_for_form_transition(page, state: ApplicationState):
    """Wait for the form to update after clicking Next/Review."""
    modal_sel = state.metadata.get("modal_selector")

    if modal_sel:
        # For modals: wait for content to change (LinkedIn swaps the form inside the modal)
        try:
            await page.wait_for_timeout(1500)
        except Exception:
            pass
    else:
        # For full-page forms: wait for navigation or DOM update
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

    await human_delay(1.0, 2.5)


# ── Utilities ───────────────────────────────────────────────────────────


def _is_auth_page(url: str) -> bool:
    lower = url.lower()
    return any(sig in lower for sig in _AUTH_SIGNALS)


def _print_header(profile: ApplicantProfile, url: str, dry_run: bool) -> None:
    pi = profile.personal_info
    mode = "[yellow]DRY RUN[/yellow]" if dry_run else "[green]LIVE[/green]"
    console.print(Panel.fit(
        f"[bold]Applicant:[/bold] {pi.first_name} {pi.last_name}\n"
        f"[bold]Email:[/bold] {pi.email}\n"
        f"[bold]Job URL:[/bold] {url}\n"
        f"[bold]Mode:[/bold] {mode}",
        title="Auto-Apply Agent",
        border_style="blue",
    ))


def _print_phase(state: ApplicationState, iteration: int) -> None:
    phase_icons = {
        Phase.CLICK_APPLY: "->",
        Phase.ANALYZE_PAGE: "??",
        Phase.FILL_FORM: "//",
        Phase.HANDLE_ERROR: "!!", 
        Phase.NAVIGATE_NEXT: ">>",
        Phase.REVIEW: "[]",
        Phase.SUBMIT: "=>",
        Phase.DONE: "OK",
        Phase.FAILED: "XX",
    }
    icon = phase_icons.get(state.phase, "  ")
    console.print(
        f"  [{iteration:02d}] {icon} [bold]{state.phase.value.upper()}[/bold]"
        f"  [dim]({state.progress_summary})[/dim]"
    )


def _print_review(state: ApplicationState) -> None:
    all_fields = state.metadata.get("all_form_fields", []) + state.form_fields
    if not all_fields:
        return

    table = Table(title="Form Review (All Pages)", show_lines=True, title_style="bold cyan")
    table.add_column("Field", style="bold", max_width=30)
    table.add_column("Value", max_width=50)
    table.add_column("Status", width=8)

    all_filled = state.metadata.get("all_filled_selectors", set()) | state.filled_fields
    for field in all_fields:
        filled = field.selector in all_filled
        status = "[green]OK[/green]" if filled else "[red]MISS[/red]"
        display_value = field.value[:50] + "..." if len(field.value) > 50 else field.value
        table.add_row(field.label or field.name, display_value, status)

    console.print(table)


def _print_summary(state: ApplicationState) -> None:
    console.print("\n")
    total_filled = state.metadata.get("total_fields_filled", 0) + len(state.filled_fields)

    if state.phase == Phase.DONE and state.is_submitted:
        console.print(Panel.fit(
            "[bold green]Application submitted successfully![/bold green]\n"
            f"Pages completed: {state.current_page}\n"
            f"Fields filled: {total_filled}\n"
            f"Errors encountered: {state.error_count}",
            title="Result",
            border_style="green",
        ))
    elif state.phase == Phase.DONE:
        console.print(Panel.fit(
            "[bold yellow]Dry run completed.[/bold yellow]\n"
            f"Pages analyzed: {state.current_page}\n"
            f"Fields filled: {total_filled}\n"
            f"Errors encountered: {state.error_count}",
            title="Result",
            border_style="yellow",
        ))
    else:
        console.print(Panel.fit(
            "[bold red]Application failed.[/bold red]\n"
            f"Last phase: {state.phase.value}\n"
            f"Errors: {state.error_count}\n"
            f"Last logs:\n" + "\n".join(state.logs[-5:]),
            title="Result",
            border_style="red",
        ))
