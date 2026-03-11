import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RateLimiter:
    interval_seconds: float = 1.0
    _lock: asyncio.Lock = field(init=False, repr=False)
    _last_call_monotonic: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_call_monotonic = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = asyncio.get_running_loop().time()
            delta = now - self._last_call_monotonic
            wait_for = self.interval_seconds - delta
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last_call_monotonic = asyncio.get_running_loop().time()


class DeadlockApiClient:
    def __init__(self, base_url: str, timeout_seconds: int, rate_limiter: RateLimiter):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout_seconds
        self.rate_limiter = rate_limiter
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        retries = 4
        for attempt in range(retries):
            await self.rate_limiter.wait()
            try:
                response = await self.client.request(method, path, params=params)
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                retriable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code >= 500
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                    retriable = True
                if not retriable or attempt == retries - 1:
                    logger.exception("Ошибка запроса Deadlock API: %s %s", method, path)
                    raise
                backoff = 2**attempt
                logger.warning("Временная ошибка Deadlock API, повтор через %s сек", backoff)
                await asyncio.sleep(backoff)
        raise RuntimeError("Недостижимая ветка")

    # TODO: сверить финальные пути и параметры с актуальной документацией Deadlock API.
    async def get_player_recent_matches(self, player_id: str) -> list[dict[str, Any]]:
        data = await self._request("GET", "players/recent-matches", params={"player_id": player_id})
        return data.get("matches", data if isinstance(data, list) else [])

    async def get_match(self, match_id: str) -> dict[str, Any]:
        return await self._request("GET", f"matches/{match_id}")

    async def get_player_profile(self, player_id: str) -> dict[str, Any]:
        return await self._request("GET", f"players/{player_id}")

    async def resolve_player(self, query: str) -> list[dict[str, Any]]:
        try:
            return await self._request("GET", "players/search", params={"q": query})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.info("Игрок не найден в Deadlock API по запросу: %s", query)
                return []
            raise

    @staticmethod
    def parse_match_for_player(match_payload: dict[str, Any], player_id: str) -> dict[str, Any]:
        """Преобразование ответа матча к стабильному формату MVP.

        TODO: финально адаптировать по реальным полям API.
        """
        player_stats = next(
            (p for p in match_payload.get("players", []) if str(p.get("player_id")) == str(player_id)),
            {},
        )
        started_at = match_payload.get("started_at") or datetime.now(timezone.utc).isoformat()
        return {
            "match_id": str(match_payload.get("match_id", "")),
            "match_datetime": started_at,
            "duration_seconds": int(match_payload.get("duration_seconds", 0)),
            "hero_name": str(player_stats.get("hero_name", "Неизвестный герой")),
            "is_win": bool(player_stats.get("is_win", False)),
            "kills": int(player_stats.get("kills", 0)),
            "deaths": int(player_stats.get("deaths", 0)),
            "assists": int(player_stats.get("assists", 0)),
            "souls": int(player_stats.get("souls", 0)),
            "damage": int(player_stats.get("damage", 0)),
            "items": [str(i) for i in player_stats.get("items", [])][:6],
            "team_damage_rank": player_stats.get("team_damage_rank"),
            "team_souls_rank": player_stats.get("team_souls_rank"),
            "raw_payload": match_payload,
        }
