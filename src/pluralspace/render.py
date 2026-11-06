"""Plain-text rendering helpers: timestamps, Editor.js documents, labels."""

import html
import json
import re
from datetime import datetime, timezone


def _day(ts: str) -> str:
    """Format an API timestamp (UTC) in the system's local timezone."""
    if not ts:
        return "-"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts[:16].replace("T", " ")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def _strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    return html.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ").strip()


def _list_lines(items, style: str, depth: int = 0):
    for i, item in enumerate(items or [], 1):
        if isinstance(item, str):
            item = {"content": item}
        marker = f"{i}." if style == "ordered" else "-"
        yield "  " * depth + f"{marker} {_strip_html(item.get('content', ''))}"
        yield from _list_lines(item.get("items"), style, depth + 1)


def _block_lines(block: dict):
    """Render one Editor.js block as plain-text lines (media become a marker/URL)."""
    kind, data = block.get("type"), block.get("data") or {}
    if kind in ("paragraph", "header"):
        yield _strip_html(data.get("text", ""))
    elif kind == "quote":
        yield f"> {_strip_html(data.get('text', ''))}"
        if data.get("caption"):
            yield f"  — {_strip_html(data['caption'])}"
    elif kind == "list":
        yield from _list_lines(data.get("items"), data.get("style", "unordered"))
    elif kind == "table":
        for row in data.get("content", []):
            yield " | ".join(_strip_html(c) for c in row)
    elif kind == "columns":
        for col in data.get("cols", []):
            for b in col.get("blocks", []):
                yield from _block_lines(b)
    elif kind == "image":
        yield f"[image: {(data.get('file') or {}).get('url', '')}]"
    elif kind == "gallery":
        for img in data.get("images", []):
            yield f"[image: {(img.get('file') or {}).get('url', '')}]"
    elif kind == "delimiter":
        yield "---"


def editorjs_text(value) -> str:
    """Plain text for an Editor.js document (dict or JSON string); "" if empty or not one."""
    if isinstance(value, str):
        if not value.lstrip().startswith("{"):
            return value
        try:
            value = json.loads(value)
        except ValueError:
            return value
    if not isinstance(value, dict) or "blocks" not in value:
        return ""
    lines = [ln for b in value["blocks"] for ln in _block_lines(b)]
    # a document of nothing but delimiters/blank lines is empty
    if not any(ln and ln != "---" for ln in lines):
        return ""
    return "\n".join(ln for ln in lines if ln)


def _field_value(value):
    """Custom field values are a string, a list (padded with "") when multiple, or rich text."""
    if isinstance(value, list):
        return ", ".join(v for v in value if v)
    return editorjs_text(value) if value else ""


def _format_relationship(r: dict) -> str:
    other = r.get("other_member") or {}
    line = f"{r.get('label', '?')}: {other.get('display_label', '(hidden)')}"
    if r.get("cross_system"):
        line += "  [cross-system]"
    if r.get("notes"):
        line += f"  - {r['notes']}"
    return line


def member_flags(
    m: dict, *, fronting: bool = False, custom_label: str = "custom"
) -> list:
    """Status tags for a member, in display order."""
    candidates = [
        ("fronting", fronting and m.get("active_front")),
        (custom_label, m.get("is_custom_front")),
        ("pinned", m.get("is_pinned")),
        ("archived", m.get("is_archived")),
    ]
    return [name for name, on in candidates if on]


def front_member_label(front: dict) -> str:
    """display_label of the member on a front record."""
    return (front.get("member") or {}).get("display_label") or "(hidden)"


def front_type_name(front: dict) -> str:
    return (front.get("front_type") or {}).get("name", "")
