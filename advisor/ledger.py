"""Append-only, event-sourced SQLite ledger for recommendations and outcomes.

No UPDATE or DELETE statements exist anywhere in this module by design: a
recommendation, once appended, is immutable. An outcome row is a separate
append that closes it out. This gives the ledger a clean audit trail and
makes shadow/eval reporting reproducible from raw history alone.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from advisor.schema import Outcome, Recommendation

logger = logging.getLogger(__name__)


class Ledger:
    """Thin SQLite-backed event log. Safe for a single-process CLI/cron use."""

    def __init__(self, db_path: Path = Path("data/ledger.db")) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS recommendations (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outcomes (
                rec_id TEXT PRIMARY KEY,
                closed_at TEXT NOT NULL,
                json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_key TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def append_recommendation(self, rec: Recommendation) -> None:
        """Append a new recommendation. Never overwrites an existing id."""
        self._conn.execute(
            "INSERT INTO recommendations (id, created_at, ticker, json) VALUES (?, ?, ?, ?)",
            (rec.id, rec.created_at.isoformat(), rec.ticker, rec.model_dump_json()),
        )
        self._conn.commit()
        logger.debug("appended recommendation %s (%s)", rec.id, rec.ticker)

    def append_outcome(self, outcome: Outcome) -> None:
        """Append a closure record for a recommendation."""
        self._conn.execute(
            "INSERT INTO outcomes (rec_id, closed_at, json) VALUES (?, ?, ?)",
            (outcome.rec_id, outcome.closed_at.isoformat(), outcome.model_dump_json()),
        )
        self._conn.commit()
        logger.debug("appended outcome for recommendation %s", outcome.rec_id)

    def open_recommendations(self) -> list[Recommendation]:
        """Recommendations with no matching outcome row, excluding holds."""
        rows = self._conn.execute(
            """
            SELECT r.json FROM recommendations r
            LEFT JOIN outcomes o ON o.rec_id = r.id
            WHERE o.rec_id IS NULL
            ORDER BY r.created_at ASC
            """
        ).fetchall()
        recs = [Recommendation.model_validate_json(row[0]) for row in rows]
        return [r for r in recs if r.direction != "hold"]

    def closed(self) -> list[tuple[Recommendation, Outcome]]:
        """All (recommendation, outcome) pairs that have been closed out."""
        rows = self._conn.execute(
            """
            SELECT r.json, o.json FROM recommendations r
            JOIN outcomes o ON o.rec_id = r.id
            ORDER BY o.closed_at ASC
            """
        ).fetchall()
        return [
            (Recommendation.model_validate_json(rec_json), Outcome.model_validate_json(outcome_json))
            for rec_json, outcome_json in rows
        ]

    def tickers_with_rec_on(self, day: date) -> set[str]:
        """Tickers that already have a recommendation created on `day`.

        `created_at` is stored as `datetime.isoformat()` (e.g.
        "2026-08-23T14:03:11.123456+00:00"), which always starts with the
        ISO calendar date, so a LIKE prefix match on `day.isoformat()`
        is sufficient -- no need to parse the column back into a datetime.
        """
        rows = self._conn.execute(
            "SELECT ticker FROM recommendations WHERE created_at LIKE ?",
            (f"{day.isoformat()}%",),
        ).fetchall()
        return {row[0] for row in rows}

    def run_exists(self, run_key: str) -> bool:
        """Whether a pipeline run with this idempotency key already ran."""
        row = self._conn.execute(
            "SELECT 1 FROM runs WHERE run_key = ?", (run_key,)
        ).fetchone()
        return row is not None

    def record_run(self, run_key: str) -> None:
        """Record that a pipeline run with this idempotency key has completed.

        Idempotent latch: a same-day rerun may legitimately call this twice
        for the same key (run.py continues past run_exists() rather than
        early-returning), so a duplicate insert must be a silent no-op
        rather than raise sqlite3.IntegrityError.
        """
        self._conn.execute(
            "INSERT OR IGNORE INTO runs (run_key, created_at) VALUES (?, ?)",
            (run_key, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()
        logger.debug("recorded run %s", run_key)

    def tickers_invalidated_since(self, since: datetime) -> set[str]:
        """Tickers whose Outcome closed by invalidation on/after `since`.

        Outcomes don't carry a ticker column, so this joins to
        `recommendations` on `rec_id` to recover it. Filters to
        `close_reason == "invalidation"` in Python (via the stored Outcome
        json) rather than in SQL, matching the parse-then-filter style
        already used by `closed()` -- no dependency on SQLite's JSON1
        extension. Used by run.py's invalidation-cooldown guard; horizon
        closes are deliberately excluded here.
        """
        rows = self._conn.execute(
            """
            SELECT r.ticker, o.json FROM outcomes o
            JOIN recommendations r ON r.id = o.rec_id
            """
        ).fetchall()
        result: set[str] = set()
        for ticker, outcome_json in rows:
            outcome = Outcome.model_validate_json(outcome_json)
            if outcome.close_reason == "invalidation" and outcome.closed_at >= since:
                result.add(ticker)
        return result

    def get_recommendation(self, rec_id: str) -> Recommendation | None:
        """Fetch a single recommendation by id, or None if it doesn't exist."""
        row = self._conn.execute(
            "SELECT json FROM recommendations WHERE id = ?", (rec_id,)
        ).fetchone()
        if row is None:
            return None
        return Recommendation.model_validate_json(row[0])
