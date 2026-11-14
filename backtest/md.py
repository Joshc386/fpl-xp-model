"""Markdown table helpers for the backtest reports."""

from __future__ import annotations

import math
from collections.abc import Sequence


def fmt(v: object, nd: int = 3) -> str:
    """A cell: floats to `nd` decimals, NaN and None as a dash."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "-"
    if isinstance(v, bool):
        return "pass" if v else "FAIL"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def table(header: Sequence[str], rows: Sequence[Sequence[object]], nd: int = 3) -> str:
    """A markdown table."""
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(fmt(c, nd) for c in r) + " |" for r in rows]
    return "\n".join(lines)
