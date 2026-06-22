"""
TQS sub-score descriptors — v19.34.391

The pillar engines emit a 0-100 number per sub-score, which is precise for the
weighting math but opaque to the operator ("VIX 85 — is that good?"). This
module turns each sub-score into a plain-language `display` block:

    { "label": "VIX", "verdict": "Strong", "reading": "VIX 16.6 · calm/normal" }

`verdict` is a colour-mappable band; `reading` surfaces the ACTUAL underlying
value the engine already computed. The raw numeric score is kept untouched for
the engine — this is a presentation layer only.
"""

from typing import Optional, Dict


def verdict_for(score: Optional[float], absent: bool = False) -> str:
    """Score band → plain verdict. `absent=True` overrides to 'No data'."""
    if absent:
        return "No data"
    s = float(score or 0)
    if s >= 85:
        return "Strong"
    if s >= 65:
        return "Favorable"
    if s >= 45:
        return "Neutral"
    if s >= 35:
        return "Caution"
    return "Weak"


def disp(label: str, score: Optional[float], reading: str,
         absent: bool = False) -> Dict[str, str]:
    """Build one sub-score display block."""
    return {
        "label": label,
        "verdict": verdict_for(score, absent),
        "reading": reading,
    }


def humanize(text: str) -> str:
    """snake_case / lower → Title Case words ('range_bound' → 'Range Bound')."""
    return str(text or "").replace("_", " ").strip().title()


_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]


def weekday_name(idx: Optional[int]) -> str:
    try:
        return _WEEKDAYS[int(idx)]
    except (TypeError, ValueError, IndexError):
        return "—"


def vix_descriptor(vix: float) -> str:
    """Plain-language meaning of a VIX level for trend trading."""
    if vix < 12:
        return "very low · complacent, chop risk"
    if vix < 15:
        return "low · calm"
    if vix <= 22:
        return "calm/normal · favorable"
    if vix <= 28:
        return "elevated · trim size"
    if vix <= 35:
        return "high · reduce risk"
    return "extreme · high risk"
