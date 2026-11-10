"""Reconciliation: upstream rows in, rows dropped by reason, rows out, per table."""

from __future__ import annotations

import pandas as pd

COLUMNS = ["season", "table", "line", "reason", "rows"]


class ReconciliationError(RuntimeError):
    """A table's counts do not add up."""


class Reconciliation:
    """Collects one block of lines per processed table for a season.

    Lines: `rows_in` (upstream rows read), `dropped` (one per reason, zero counts
    included so a reader sees the reason was checked), `rows_out`, and `info`
    (counts that explain rows kept, not dropped).
    """

    def __init__(self, season: str) -> None:
        self.season = season
        self._rows: list[tuple[str, str, str, str, int]] = []

    def add(
        self,
        table: str,
        rows_in: int,
        dropped: dict[str, int],
        rows_out: int,
        info: dict[str, int] | None = None,
    ) -> None:
        """Record a table; raise if rows in minus dropped is not rows out."""
        if rows_in - sum(dropped.values()) != rows_out:
            raise ReconciliationError(
                f"{self.season} {table}: {rows_in} in - {sum(dropped.values())} dropped "
                f"!= {rows_out} out"
            )
        add = self._rows.append
        add((self.season, table, "rows_in", "", rows_in))
        for reason, n in dropped.items():
            add((self.season, table, "dropped", reason, n))
        add((self.season, table, "rows_out", "", rows_out))
        for reason, n in (info or {}).items():
            add((self.season, table, "info", reason, n))

    def frame(self) -> pd.DataFrame:
        """The reconciliation as a long table."""
        return pd.DataFrame(self._rows, columns=COLUMNS)
