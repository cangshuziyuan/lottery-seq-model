import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("LOTTERY_DB", ROOT / "data" / "lottery.db"))


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS draws (
                game TEXT NOT NULL,
                issue TEXT NOT NULL,
                draw_date TEXT NOT NULL,
                numbers TEXT NOT NULL,
                sales INTEGER,
                pool INTEGER,
                PRIMARY KEY (game, issue)
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reports (
                game TEXT NOT NULL,
                kind TEXT NOT NULL,
                signature TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (game, kind)
            );
            CREATE TABLE IF NOT EXISTS predictions (
                game TEXT NOT NULL,
                based_on_issue TEXT NOT NULL,
                target_issue TEXT NOT NULL,
                model TEXT NOT NULL,
                ticket_index INTEGER NOT NULL,
                ticket TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (game, based_on_issue, model, ticket_index)
            );
            """
        )


def upsert_draws(game: str, rows: list[dict]) -> int:
    init_db()
    with connect() as conn:
        before = conn.total_changes
        conn.executemany(
            """
            INSERT INTO draws(game, issue, draw_date, numbers, sales, pool)
            VALUES(:game, :issue, :draw_date, :numbers, :sales, :pool)
            ON CONFLICT(game, issue) DO UPDATE SET
                draw_date=excluded.draw_date,
                numbers=excluded.numbers,
                sales=excluded.sales,
                pool=excluded.pool
            """,
            [
                {
                    "game": game,
                    "issue": row["issue"],
                    "draw_date": row["date"],
                    "numbers": json.dumps(row["numbers"], ensure_ascii=False),
                    "sales": row.get("sales"),
                    "pool": row.get("pool"),
                }
                for row in rows
            ],
        )
        return conn.total_changes - before


def issue_set(game: str) -> set[str]:
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT issue FROM draws WHERE game=?", (game,)).fetchall()
    return {row["issue"] for row in rows}


def load_draws(game: str) -> list[dict]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT issue, draw_date, numbers, sales, pool FROM draws WHERE game=? ORDER BY issue",
            (game,),
        ).fetchall()
    return [
        {
            "issue": row["issue"],
            "date": row["draw_date"],
            "numbers": json.loads(row["numbers"]),
            "sales": row["sales"],
            "pool": row["pool"],
        }
        for row in rows
    ]


def save_predictions(game: str, based_on: str, target: str, models: list[dict], source: str = "live") -> int:
    """保存每期每个模型的预测号码。回填记录不覆盖实盘记录。"""
    init_db()
    rows = [
        (
            game,
            based_on,
            target,
            item["model"],
            index,
            json.dumps(ticket, ensure_ascii=False),
            source,
            datetime.now().isoformat(timespec="seconds"),
        )
        for item in models
        for index, ticket in enumerate(item["tickets"])
    ]
    conflict = "DO NOTHING" if source == "backfill" else """DO UPDATE SET
                target_issue=excluded.target_issue,
                ticket=excluded.ticket,
                source=excluded.source,
                created_at=excluded.created_at
            """
    with connect() as conn:
        before = conn.total_changes
        conn.executemany(
            f"""
            INSERT INTO predictions(game, based_on_issue, target_issue, model, ticket_index, ticket, source, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game, based_on_issue, model, ticket_index) {conflict}
            """,
            rows,
        )
        return conn.total_changes - before


def load_predictions(game: str) -> list[dict]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT based_on_issue, target_issue, model, ticket_index, ticket, source, created_at
            FROM predictions WHERE game=? ORDER BY based_on_issue, model, ticket_index
            """,
            (game,),
        ).fetchall()
    return [
        {
            "based_on": row["based_on_issue"],
            "target_issue": row["target_issue"],
            "model": row["model"],
            "ticket": json.loads(row["ticket"]),
            "source": row["source"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def set_meta(key: str, value: str) -> None:
    init_db()
    with connect() as conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def cached_report(game: str, kind: str, signature: str):
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT payload FROM reports WHERE game=? AND kind=? AND signature=?",
            (game, kind, signature),
        ).fetchone()
    return json.loads(row["payload"]) if row else None


def save_report(game: str, kind: str, signature: str, payload: dict) -> None:
    init_db()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO reports(game, kind, signature, payload) VALUES(?, ?, ?, ?)
            ON CONFLICT(game, kind) DO UPDATE SET signature=excluded.signature, payload=excluded.payload
            """,
            (game, kind, signature, json.dumps(payload, ensure_ascii=False)),
        )


def get_meta(key: str) -> str | None:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None
