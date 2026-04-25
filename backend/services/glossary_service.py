"""
Glossary Service
================

Single-source-of-truth bridge between the frontend's
`/app/frontend/src/data/glossaryData.js` (already used by the
GlossaryDrawer, ⌘K help mode, press-? overlay, and tour overlays) and
the backend.

Why parse the JS file instead of duplicating the data in Python?
The glossary is content, not code. Maintaining a parallel Python copy
would mean every doc edit drifts in two places. The frontend's JS
remains canonical; this service tolerantly extracts the entries we
need — id, term, category, shortDef, fullDef, relatedTerms, tags —
using a hand-written parser that understands template literals.

The parsed result is cached in module memory so we only pay the cost
once at startup. A `reload_glossary()` helper exists for hot edits.

Public surface:
    load_glossary() -> {"categories": [...], "entries": [...]}
    find_terms(query, limit=8) -> [entry, ...]
    get_term(term_id) -> entry | None
    glossary_for_chat(max_chars=4000) -> str   # compact prompt block
"""
from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)

# Resolve the frontend file relative to this service. The repo layout is:
#   /app/backend/services/glossary_service.py
#   /app/frontend/src/data/glossaryData.js
GLOSSARY_PATH = Path(
    os.environ.get(
        "GLOSSARY_DATA_PATH",
        "/app/frontend/src/data/glossaryData.js",
    )
)


# ---------------------------------------------------------------------------
# Tolerant JS-object parser
# ---------------------------------------------------------------------------
#
# We don't need a full JS AST. The glossary file follows a strict shape:
#   const glossaryData = { categories: [...], entries: [...] };
# Inside each entry we look for:
#   id: 'string',
#   term: 'string',
#   category: 'string',
#   shortDef: 'string' | "string",
#   fullDef: `template literal can span lines`,
#   relatedTerms: ['a', 'b'],
#   tags: ['a', 'b'],
# Order doesn't matter, and not every field is required.

def _split_top_level_objects(blob: str) -> List[str]:
    """Split a JS array body like `{...}, {...}, {...}` into individual
    object source strings, respecting nested braces/brackets and string
    literals (single, double, backtick).
    """
    out: List[str] = []
    depth = 0
    in_str: Optional[str] = None  # current quote char or None
    escape = False
    start: Optional[int] = None
    for i, ch in enumerate(blob):
        if escape:
            escape = False
            continue
        if in_str:
            if ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
            continue
        if ch in ("'", '"', "`"):
            in_str = ch
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                out.append(blob[start:i + 1])
                start = None
    return out


_FIELD_RE = re.compile(
    r"""(?xs)
    (?P<key>[A-Za-z_][A-Za-z0-9_]*)
    \s*:\s*
    (?:
        '(?P<sq>(?:\\.|[^'\\])*)'
      | "(?P<dq>(?:\\.|[^"\\])*)"
      | `(?P<bt>(?:\\.|[^`\\])*)`
      | \[(?P<arr>(?:\\.|[^\[\]])*)\]
    )
    """
)


def _unescape(s: str) -> str:
    """Translate JS string escapes that matter for our text content."""
    return (
        s
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\'", "'")
        .replace('\\"', '"')
        .replace("\\`", "`")
        .replace("\\\\", "\\")
    )


def _parse_string_array(arr_body: str) -> List[str]:
    """Pull quoted strings out of a single-level array body."""
    items = []
    for m in re.finditer(r"""'((?:\\.|[^'\\])*)'|"((?:\\.|[^"\\])*)\"""", arr_body):
        items.append(_unescape(m.group(1) if m.group(1) is not None else m.group(2)))
    return items


def _parse_object(src: str) -> Dict[str, Any]:
    obj: Dict[str, Any] = {}
    for m in _FIELD_RE.finditer(src):
        key = m.group("key")
        if m.group("sq") is not None:
            obj[key] = _unescape(m.group("sq"))
        elif m.group("dq") is not None:
            obj[key] = _unescape(m.group("dq"))
        elif m.group("bt") is not None:
            obj[key] = _unescape(m.group("bt"))
        elif m.group("arr") is not None:
            obj[key] = _parse_string_array(m.group("arr"))
    return obj


def _slice_array_body(src: str, key: str) -> Optional[str]:
    """Return the body of a top-level `key: [ ... ]` block."""
    # Find `key:`
    i = src.find(f"{key}:")
    if i < 0:
        i = src.find(f"{key} :")
        if i < 0:
            return None
    # Find first `[` after the key
    j = src.find("[", i)
    if j < 0:
        return None
    # Walk forward respecting nesting to find the matching `]`.
    depth = 0
    in_str: Optional[str] = None
    escape = False
    for k in range(j, len(src)):
        ch = src[k]
        if escape:
            escape = False
            continue
        if in_str:
            if ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
            continue
        if ch in ("'", '"', "`"):
            in_str = ch
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return src[j + 1:k]
    return None


def _parse_glossary_file(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    text = path.read_text(encoding="utf-8")
    cats_body = _slice_array_body(text, "categories") or ""
    entries_body = _slice_array_body(text, "entries") or ""
    categories = [_parse_object(s) for s in _split_top_level_objects(cats_body)]
    entries = [_parse_object(s) for s in _split_top_level_objects(entries_body)]
    return {"categories": categories, "entries": entries}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_glossary() -> Dict[str, List[Dict[str, Any]]]:
    """Parse and cache the glossary file. Returns {} on failure."""
    try:
        if not GLOSSARY_PATH.exists():
            logger.warning(f"Glossary file not found at {GLOSSARY_PATH}")
            return {"categories": [], "entries": []}
        data = _parse_glossary_file(GLOSSARY_PATH)
        logger.info(
            f"Glossary loaded — {len(data.get('categories', []))} categories, "
            f"{len(data.get('entries', []))} entries"
        )
        return data
    except Exception as e:
        logger.error(f"Failed to parse glossary: {e}", exc_info=True)
        return {"categories": [], "entries": []}


def reload_glossary() -> Dict[str, List[Dict[str, Any]]]:
    """Force a re-parse (use after editing the JS file)."""
    load_glossary.cache_clear()
    return load_glossary()


def get_term(term_id: str) -> Optional[Dict[str, Any]]:
    if not term_id:
        return None
    for e in load_glossary().get("entries", []):
        if e.get("id") == term_id:
            return e
    return None


def find_terms(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Return up to `limit` entries matching `query` against term, id,
    shortDef, or any tag. Empty query returns the first `limit` entries."""
    entries = load_glossary().get("entries", [])
    if not query:
        return entries[:limit]
    q = query.lower()

    def _match(e: Dict[str, Any]) -> bool:
        if q in (e.get("term") or "").lower():
            return True
        if q in (e.get("id") or "").lower():
            return True
        if q in (e.get("shortDef") or "").lower():
            return True
        return any(q in (t or "").lower() for t in (e.get("tags") or []))

    return [e for e in entries if _match(e)][:limit]


def glossary_for_chat(max_chars: int = 4000) -> str:
    """Compact one-line-per-term block injected into the chat system
    prompt so the AI can quote definitions verbatim. Format:

        - Backfill Readiness: Single GREEN/YELLOW/RED verdict answering …
        - ⌘K Command Palette: Press ⌘K (Mac) or Ctrl+K to open a global …

    Truncates to `max_chars` to stay inside the LLM context budget.
    """
    entries = load_glossary().get("entries", [])
    if not entries:
        return ""
    parts = ["APP GLOSSARY (verbatim definitions — quote these when asked):"]
    for e in entries:
        line = f"- {e.get('term', '')}: {e.get('shortDef', '')}"
        # collapse whitespace and trim
        line = re.sub(r"\s+", " ", line).strip()
        parts.append(line)
    block = "\n".join(parts)
    if len(block) > max_chars:
        block = block[:max_chars - 3] + "..."
    return block
