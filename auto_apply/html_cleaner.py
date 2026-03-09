"""HTML cleaning and form field extraction for the Form-Understanding Agent."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag


_REMOVE_TAGS = {"script", "style", "noscript", "svg", "path", "meta", "link", "head"}
_FORM_TAGS = {"input", "select", "textarea", "button"}
_MAX_HTML_LENGTH = 30_000


def clean_html(raw_html: str) -> str:
    """Strip non-essential elements and return a compact, form-focused HTML string."""
    soup = BeautifulSoup(raw_html, "html.parser")

    for tag in soup.find_all(_REMOVE_TAGS):
        tag.decompose()

    for tag in soup.find_all(True):
        if isinstance(tag, Tag):
            keep_attrs = {
                "id", "name", "class", "type", "value", "placeholder",
                "for", "href", "action", "method", "required", "aria-label",
                "aria-labelledby", "aria-describedby", "data-testid",
                "role", "checked", "selected", "disabled", "multiple",
                "accept", "maxlength", "min", "max", "pattern", "step",
            }
            attrs = dict(tag.attrs)
            for attr in attrs:
                if attr not in keep_attrs:
                    del tag[attr]

    cleaned = soup.prettify()
    if len(cleaned) > _MAX_HTML_LENGTH:
        cleaned = _extract_form_regions(soup)

    return cleaned


def _extract_form_regions(soup: BeautifulSoup) -> str:
    """When the page is too large, extract only form-related regions."""
    parts: list[str] = []

    forms = soup.find_all("form")
    if forms:
        for form in forms:
            parts.append(str(form))
    else:
        for tag in soup.find_all(_FORM_TAGS):
            parent = tag.parent
            depth = 0
            while parent and parent.name not in ("body", "[document]") and depth < 4:
                parent = parent.parent
                depth += 1
            if parent and parent.name not in ("body", "[document]"):
                parts.append(str(parent))
            else:
                parts.append(str(tag))

    result = "\n".join(parts)
    if len(result) > _MAX_HTML_LENGTH:
        result = result[:_MAX_HTML_LENGTH]
    return result


def _build_selector(tag: Tag) -> str:
    """Build a robust CSS selector for a form element."""
    if tag.get("id"):
        return f"#{tag['id']}"

    if tag.get("name"):
        tag_name = tag.name
        name = tag["name"]
        sel = f'{tag_name}[name="{name}"]'
        input_type = tag.get("type")
        if input_type:
            sel = f'{tag_name}[name="{name}"][type="{input_type}"]'
        return sel

    if tag.get("data-testid"):
        return f'[data-testid="{tag["data-testid"]}"]'

    if tag.get("aria-label"):
        return f'[aria-label="{tag["aria-label"]}"]'

    if tag.get("placeholder"):
        return f'{tag.name}[placeholder="{tag["placeholder"]}"]'

    parts = [tag.name]
    if tag.get("type"):
        parts.append(f'[type="{tag["type"]}"]')
    classes = tag.get("class", [])
    if classes:
        parts.append("." + ".".join(classes[:2]))
    return "".join(parts)


def _find_label(tag: Tag, soup: BeautifulSoup) -> str:
    """Find the human-readable label for a form element."""
    tag_id = tag.get("id")
    if tag_id:
        label = soup.find("label", attrs={"for": tag_id})
        if label:
            return label.get_text(strip=True)

    parent = tag.parent
    if parent and parent.name == "label":
        text = parent.get_text(strip=True)
        return text

    if tag.get("aria-label"):
        return tag["aria-label"]

    if tag.get("placeholder"):
        return tag["placeholder"]

    if tag.get("name"):
        name = tag["name"]
        return re.sub(r"[_\-\[\]]+", " ", name).strip().title()

    prev = tag.find_previous_sibling()
    if prev and prev.name in ("label", "span", "div", "p"):
        text = prev.get_text(strip=True)
        if text and len(text) < 100:
            return text

    return ""


def _get_field_type(tag: Tag) -> str:
    """Determine the logical field type."""
    if tag.name == "textarea":
        return "textarea"
    if tag.name == "select":
        return "select"
    if tag.name == "input":
        return tag.get("type", "text").lower()
    return "text"


def _get_options(tag: Tag) -> list[str]:
    """Extract options from select or datalist elements."""
    if tag.name == "select":
        return [
            opt.get_text(strip=True)
            for opt in tag.find_all("option")
            if opt.get_text(strip=True)
        ]

    list_id = tag.get("list")
    if list_id:
        soup = tag.find_parent()
        if soup:
            datalist = soup.find("datalist", id=list_id)
            if datalist:
                return [
                    opt.get("value", opt.get_text(strip=True))
                    for opt in datalist.find_all("option")
                ]
    return []


def extract_form_fields(raw_html: str) -> list[dict]:
    """Extract all form fields from HTML with their metadata.

    Returns a list of dicts with keys:
        selector, field_type, label, required, placeholder, name, options, current_value
    """
    soup = BeautifulSoup(raw_html, "html.parser")

    for tag in soup.find_all(_REMOVE_TAGS):
        tag.decompose()

    fields: list[dict] = []
    seen_selectors: set[str] = set()

    form_elements = soup.find_all(_FORM_TAGS - {"button"})

    for tag in form_elements:
        field_type = _get_field_type(tag)

        if field_type in ("hidden", "submit", "button", "image", "reset"):
            continue

        selector = _build_selector(tag)
        if selector in seen_selectors:
            continue
        seen_selectors.add(selector)

        label = _find_label(tag, soup)
        options = _get_options(tag)
        current_value = tag.get("value", "")
        if tag.name == "textarea":
            current_value = tag.get_text(strip=True)

        is_required = (
            tag.has_attr("required")
            or "required" in tag.get("class", [])
            or "*" in label
        )

        fields.append({
            "selector": selector,
            "field_type": field_type,
            "label": label,
            "required": is_required,
            "placeholder": tag.get("placeholder", ""),
            "name": tag.get("name", ""),
            "options": options,
            "current_value": current_value,
        })

    return fields


def detect_apply_button(raw_html: str) -> str | None:
    """Detect an 'Apply' / 'Easy Apply' button on a job listing page.

    Returns a CSS selector for the apply button, or None if not found.
    """
    soup = BeautifulSoup(raw_html, "html.parser")

    # LinkedIn-specific: look for the Easy Apply / Apply button by class
    for cls_pattern in ("jobs-apply-button", "jobs-s-apply"):
        btn = soup.find(["button", "a"], class_=lambda c: c and cls_pattern in " ".join(c) if isinstance(c, list) else cls_pattern in (c or ""))
        if btn:
            sel = _build_selector(btn)
            if sel:
                return sel

    # Generic: scan all buttons and links for apply-related text
    _APPLY_KEYWORDS = ("easy apply", "apply now", "apply on", "apply", "submit application")
    _IGNORE_KEYWORDS = ("set alert", "save", "share", "sign in", "join now")

    candidates = soup.find_all(["button", "a"])
    for el in candidates:
        text = el.get_text(strip=True).lower()
        aria = (el.get("aria-label") or "").lower()
        combined = f"{text} {aria}"

        # Skip non-apply buttons
        if any(kw in combined for kw in _IGNORE_KEYWORDS):
            continue

        if any(kw in combined for kw in _APPLY_KEYWORDS):
            sel = _build_selector(el)
            if sel:
                return sel

    return None
