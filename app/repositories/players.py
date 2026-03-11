from app.db import Database
from app.models import TrackedPlayer


class TrackedPlayersRepository:
    def __init__(self, db: Database):
        self.db = db

    def add_player(self, telegram_user_id: int, player_id: str, display_name: str, steam_profile_url: str | None = None) -> bool:
        with self.db.connection() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO tracked_players
                (telegram_user_id, player_id, display_name, steam_profile_url, is_enabled, auto_reports_enabled)
                VALUES (?, ?, ?, ?, 1, 1)
                """,
                (telegram_user_id, player_id, display_name, steam_profile_url),
            )
            return cur.rowcount > 0

    def list_players(self, telegram_user_id: int) -> list[TrackedPlayer]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM tracked_players WHERE telegram_user_id = ? ORDER BY created_at DESC",
                (telegram_user_id,),
            ).fetchall()
        return [TrackedPlayer(**dict(r)) for r in rows]

    def remove_player(self, telegram_user_id: int, player_id: str) -> bool:
        with self.db.connection() as conn:
            cur = conn.execute(
                "DELETE FROM tracked_players WHERE telegram_user_id = ? AND player_id = ?",
                (telegram_user_id, player_id),
            )
            return cur.rowcount > 0

    def set_auto_reports(self, telegram_user_id: int, player_id: str, enabled: bool) -> bool:
        with self.db.connection() as conn:
            cur = conn.execute(
                """
                UPDATE tracked_players
                SET auto_reports_enabled = ?
                WHERE telegram_user_id = ? AND player_id = ?
                """,
                (1 if enabled else 0, telegram_user_id, player_id),
            )
            return cur.rowcount > 0

    def get_all_enabled_for_polling(self) -> list[TrackedPlayer]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tracked_players
                WHERE is_enabled = 1 AND auto_reports_enabled = 1
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [TrackedPlayer(**dict(r)) for r in rows]

    def update_last_seen_match(self, tracked_player_id: int, match_id: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE tracked_players SET last_seen_match_id = ? WHERE id = ?",
                (match_id, tracked_player_id),
            )

    def update_last_sent_match(self, tracked_player_id: int, match_id: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE tracked_players SET last_sent_match_id = ? WHERE id = ?",
                (match_id, tracked_player_id),
            )
