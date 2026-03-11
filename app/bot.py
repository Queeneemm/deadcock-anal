import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.clients.assets import AssetsClient
from app.clients.deadlock_api import DeadlockApiClient, RateLimiter
from app.config import get_settings
from app.db import Database
from app.handlers.players import router as players_router
from app.handlers.players import setup_players_dependencies
from app.handlers.reports import router as reports_router
from app.handlers.reports import setup_reports_dependencies
from app.handlers.start import router as start_router
from app.repositories.matches import MatchesRepository, ReportsRepository
from app.repositories.players import TrackedPlayersRepository
from app.repositories.users import UsersRepository
from app.services.analytics import AnalyticsService
from app.services.cards import CardRenderer
from app.services.polling import PollingService
from app.utils.logging import setup_logging


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    db = Database(settings.database_url)
    db.init()

    rate_limiter = RateLimiter(interval_seconds=1.0)
    api = DeadlockApiClient(settings.deadlock_api_base_url, settings.request_timeout_seconds, rate_limiter)
    assets = AssetsClient(settings.deadlock_assets_base_url, settings.asset_cache_dir, settings.request_timeout_seconds)

    users_repo = UsersRepository(db)
    players_repo = TrackedPlayersRepository(db)
    matches_repo = MatchesRepository(db)
    reports_repo = ReportsRepository(db)
    analytics_service = AnalyticsService()
    card_renderer = CardRenderer(assets, settings.card_output_dir)

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    setup_players_dependencies(users_repo, players_repo, api)
    setup_reports_dependencies(bot, api, players_repo, matches_repo, analytics_service, card_renderer)

    dp.include_router(start_router)
    dp.include_router(players_router)
    dp.include_router(reports_router)

    polling_service = PollingService(
        bot=bot,
        api=api,
        players_repo=players_repo,
        matches_repo=matches_repo,
        reports_repo=reports_repo,
        analytics=analytics_service,
        cards=card_renderer,
        poll_interval_seconds=settings.poll_interval_seconds,
    )

    polling_task = asyncio.create_task(polling_service.run_forever())
    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        polling_task.cancel()
        await assets.close()
        await api.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
