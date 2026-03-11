import json
from datetime import datetime
from typing import Any

from app.db import Database
from app.models import MatchSummary


class MatchesRepository:
    def __init__(self, db: Database):
        self.db = db

    def cache_match(self, match_id: str, raw_payload: dict[str, Any], parsed_payload: dict[str, Any]) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO matches_cache (match_id, raw_payload_json, parsed_payload_json)
                VALUES (?, ?, ?)
                """,
                (match_id, json.dumps(raw_payload, ensure_ascii=False), json.dumps(parsed_payload, ensure_ascii=False)),
            )

    def get_cached_match(self, match_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT parsed_payload_json FROM matches_cache WHERE match_id = ?",
                (match_id,),
            ).fetchone()
        if not row:
            return None
        return json.loads(row["parsed_payload_json"])

    def store_player_match_history(self, player_id: str, match: MatchSummary) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO player_match_history
                (player_id, match_id, match_datetime, hero_name, is_win, kills, deaths, assists, souls, damage, raw_payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    player_id,
                    match.match_id,
                    match.match_datetime.isoformat(),
                    match.hero_name,
                    1 if match.is_win else 0,
                    match.kills,
                    match.deaths,
                    match.assists,
                    match.souls,
                    match.damage,
                    json.dumps(match.raw_payload or {}, ensure_ascii=False),
                ),
            )

    def get_recent_player_matches(self, player_id: str, limit: int = 20, hero_name: str | None = None) -> list[MatchSummary]:
        query = """
            SELECT * FROM player_match_history
            WHERE player_id = ?
        """
        params: list[Any] = [player_id]
        if hero_name:
            query += " AND hero_name = ?"
            params.append(hero_name)
        query += " ORDER BY match_datetime DESC LIMIT ?"
        params.append(limit)

        with self.db.connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        summaries: list[MatchSummary] = []
        for row in rows:
            summaries.append(
                MatchSummary(
                    match_id=row["match_id"],
                    match_datetime=datetime.fromisoformat(row["match_datetime"]),
                    hero_name=row["hero_name"],
                    is_win=bool(row["is_win"]),
                    kills=row["kills"],
                    deaths=row["deaths"],
                    assists=row["assists"],
                    souls=row["souls"],
                    damage=row["damage"],
                    duration_seconds=0,
                    items=[],
                    raw_payload=json.loads(row["raw_payload_json"]),
                )
            )
        return summaries


class ReportsRepository:
    def __init__(self, db: Database):
        self.db = db

    def was_sent(self, telegram_user_id: int, player_id: str, match_id: str) -> bool:
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM sent_reports
                WHERE telegram_user_id = ? AND player_id = ? AND match_id = ?
                """,
                (telegram_user_id, player_id, match_id),
            ).fetchone()
        return row is not None

    def mark_sent(self, telegram_user_id: int, player_id: str, match_id: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO sent_reports (telegram_user_id, player_id, match_id)
                VALUES (?, ?, ?)
                """,
                (telegram_user_id, player_id, match_id),
            )
