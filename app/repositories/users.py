from app.db import Database


class UsersRepository:
    def __init__(self, db: Database):
        self.db = db

    def ensure_user(self, telegram_user_id: int) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (telegram_user_id) VALUES (?)",
                (telegram_user_id,),
            )
