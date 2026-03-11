import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.types import FSInputFile

from app.clients.deadlock_api import DeadlockApiClient, DeadlockApiError, DeadlockApiNotFoundError, DeadlockApiTemporaryError
from app.keyboards.inline import report_actions_keyboard
from app.models import MatchSummary, TrackedPlayer
from app.repositories.matches import MatchesRepository, ReportsRepository
from app.repositories.players import TrackedPlayersRepository
from app.services.analytics import AnalyticsService
from app.services.cards import CardRenderer

logger = logging.getLogger(__name__)


class PollingService:
    def __init__(
        self,
        bot: Bot,
        api: DeadlockApiClient,
        players_repo: TrackedPlayersRepository,
        matches_repo: MatchesRepository,
        reports_repo: ReportsRepository,
        analytics: AnalyticsService,
        cards: CardRenderer,
        poll_interval_seconds: int,
    ):
        self.bot = bot
        self.api = api
        self.players_repo = players_repo
        self.matches_repo = matches_repo
        self.reports_repo = reports_repo
        self.analytics = analytics
        self.cards = cards
        self.poll_interval_seconds = poll_interval_seconds
        self._warned_keys: set[str] = set()

    async def run_forever(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception:
                logger.exception("Критическая ошибка цикла polling")
            await asyncio.sleep(self.poll_interval_seconds)

    async def _tick(self) -> None:
        tracked = self.players_repo.get_all_enabled_for_polling()
        for player in tracked:
            await self._process_player(player)

    def _warn_once(self, key: str, message: str, *args: object) -> None:
        if key in self._warned_keys:
            return
        self._warned_keys.add(key)
        logger.warning(message, *args)

    async def _process_player(self, tracked: TrackedPlayer) -> None:
        try:
            recent = await self.api.get_player_recent_matches(tracked.player_id)
        except DeadlockApiNotFoundError:
            self._warn_once(f"notfound:{tracked.player_id}", "Игрок %s не найден в Deadlock API", tracked.player_id)
            return
        except DeadlockApiTemporaryError:
            logger.warning("Временная ошибка API и нет кэша match-history для игрока %s, пропускаем тик", tracked.player_id)
            return
        except DeadlockApiError:
            logger.exception("Ошибка API для игрока %s", tracked.player_id)
            return

        if not recent:
            return

        matches_ordered = list(reversed(recent))
        for raw in matches_ordered:
            match_id = str(raw.get("match_id") or raw.get("id") or "")
            if not match_id:
                continue
            if self.reports_repo.was_sent(tracked.telegram_user_id, tracked.player_id, match_id):
                continue

            parsed = self.api.parse_match_for_player(raw, tracked.player_id)
            summary = MatchSummary(
                match_id=parsed["match_id"] or match_id,
                match_datetime=datetime.fromisoformat(parsed["match_datetime"].replace("Z", "+00:00")),
                hero_name=parsed["hero_name"],
                is_win=parsed["is_win"],
                hero_id=parsed.get("hero_id"),
                kills=parsed["kills"],
                deaths=parsed["deaths"],
                assists=parsed["assists"],
                souls=parsed["souls"],
                damage=parsed["damage"],
                duration_seconds=parsed["duration_seconds"],
                items=parsed["items"],
                team_damage_rank=parsed.get("team_damage_rank"),
                team_souls_rank=parsed.get("team_souls_rank"),
                raw_payload=parsed.get("raw_payload"),
            )
            self.matches_repo.cache_match(match_id, parsed.get("raw_payload") or raw, parsed)
            self.matches_repo.store_player_match_history(tracked.player_id, summary)

            recent_matches = self.matches_repo.get_recent_player_matches(tracked.player_id, 20)
            hero_history = self.matches_repo.get_recent_player_matches(tracked.player_id, 20, hero_name=summary.hero_name)
            week_matches = self.matches_repo.get_recent_player_matches(tracked.player_id, 100)
            analytics = self.analytics.analyze(summary, recent_matches, hero_history, week_matches)
            card_path = await self.cards.render(tracked.display_name, summary, analytics)

            title = (f'<a href="{tracked.steam_profile_url}">{tracked.display_name}</a>' if tracked.steam_profile_url else f"<b>{tracked.display_name}</b>")
            caption = (
                f"{title} • <b>{summary.hero_name}</b>\n"
                f"Результат: <b>{'Победа' if summary.is_win else 'Поражение'}</b>\n"
                f"K/D/A: <code>{summary.kills}/{summary.deaths}/{summary.assists}</code> | "
                f"Souls: <code>{summary.souls}</code> | Damage: <code>{summary.damage}</code>"
            )

            await self.bot.send_photo(
                chat_id=tracked.telegram_user_id,
                photo=FSInputFile(card_path),
                caption=caption,
                parse_mode="HTML",
                reply_markup=report_actions_keyboard(tracked.player_id, summary.match_id),
            )

            self.reports_repo.mark_sent(tracked.telegram_user_id, tracked.player_id, match_id)
            self.players_repo.update_last_seen_match(tracked.id, match_id)
            self.players_repo.update_last_sent_match(tracked.id, match_id)
