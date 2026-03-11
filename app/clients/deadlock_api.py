import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.etree import ElementTree
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

    async def resolve_steam_profile_to_player_id(self, profile_url: str) -> str | None:
        """Преобразует ссылку steamcommunity в SteamID64/account_id для Deadlock API."""
        normalized = profile_url.strip()
        direct_match = re.match(r"^https?://steamcommunity\.com/profiles/(\d+)/?", normalized, flags=re.IGNORECASE)
        if direct_match:
            return direct_match.group(1)

        vanity_match = re.match(
            r"^https?://steamcommunity\.com/id/([A-Za-z0-9_\-]+)/?",
            normalized,
            flags=re.IGNORECASE,
        )
        if not vanity_match:
            return None

        vanity_name = vanity_match.group(1)
        try:
            response = await self.client.get(f"https://steamcommunity.com/id/{vanity_name}/?xml=1")
            response.raise_for_status()
            xml_root = ElementTree.fromstring(response.text)
            steam_id64 = xml_root.findtext("steamID64")
            return steam_id64.strip() if steam_id64 else None
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, ElementTree.ParseError):
            logger.exception("Не удалось разрешить Steam профиль: %s", profile_url)
            return None

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
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
                        logger.info("Deadlock API вернул 404: %s %s", method, path)
                    else:
                        logger.exception("Ошибка запроса Deadlock API: %s %s", method, path)
                    raise
                backoff = 2**attempt
                logger.warning("Временная ошибка Deadlock API, повтор через %s сек", backoff)
                await asyncio.sleep(backoff)
        raise RuntimeError("Недостижимая ветка")

    @staticmethod
    def _candidate_player_ids(player_id: str) -> list[str]:
        """Возвращает варианты player_id для разных схем API (SteamID64/account_id)."""
        variants = [str(player_id)]
        if not str(player_id).isdigit():
            return variants

        value = int(player_id)
        steam64_offset = 76561197960265728
        if value >= steam64_offset:
            variants.append(str(value - steam64_offset))
        else:
            variants.append(str(value + steam64_offset))
        return list(dict.fromkeys(variants))

    async def _request_with_player_variants(
        self,
        method: str,
        path_builder: Any,
        params_builder: Any,
        player_id: str,
    ) -> Any:
        last_exc: httpx.HTTPStatusError | None = None
        for candidate in self._candidate_player_ids(player_id):
            try:
                path = path_builder(candidate)
                params = params_builder(candidate)
                return await self._request(method, path, params=params)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                last_exc = exc
                logger.info("Игрок %s не найден по варианту id=%s", player_id, candidate)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Недостижимая ветка")

    # TODO: сверить финальные пути и параметры с актуальной документацией Deadlock API.
    async def get_player_recent_matches(self, player_id: str) -> list[dict[str, Any]]:
        data = await self._request_with_player_variants(
            "GET",
            path_builder=lambda _pid: "players/recent-matches",
            params_builder=lambda pid: {"player_id": pid},
            player_id=player_id,
        )
        return data.get("matches", data if isinstance(data, list) else [])

    async def get_match(self, match_id: str) -> dict[str, Any]:
        return await self._request("GET", f"matches/{match_id}")

    async def get_player_profile(self, player_id: str) -> dict[str, Any]:
        return await self._request_with_player_variants(
            "GET",
            path_builder=lambda pid: f"players/{pid}",
            params_builder=lambda _pid: None,
            player_id=player_id,
        )

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
