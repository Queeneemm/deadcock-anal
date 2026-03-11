import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.etree import ElementTree
from typing import Any

import httpx

logger = logging.getLogger(__name__)

STEAM64_OFFSET = 76561197960265728


class DeadlockApiError(Exception):
    """Базовая ошибка клиента Deadlock API."""


class DeadlockApiNotFoundError(DeadlockApiError):
    """Ресурс не найден (404)."""


class DeadlockApiTemporaryError(DeadlockApiError):
    """Временная ошибка API (429/5xx или сеть/таймаут)."""


class DeadlockApiUnsupportedRouteError(DeadlockApiError):
    """Запрошен маршрут, который не подтверждён документацией."""


@dataclass(frozen=True, slots=True)
class DeadlockApiRoutes:
    match_history: str = "match-history/{account_id}"
    steam_profile: str = "steam-profile/{account_id}"
    # TODO: подтвердить реальный маршрут деталей матча и задать его здесь.
    match_details: str | None = None


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
    def __init__(
        self,
        base_url: str,
        timeout_seconds: int,
        rate_limiter: RateLimiter,
        routes: DeadlockApiRoutes | None = None,
    ):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout_seconds
        self.rate_limiter = rate_limiter
        self.routes = routes or DeadlockApiRoutes()
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)

    async def close(self) -> None:
        await self.client.aclose()

    @staticmethod
    def steam64_to_account_id(steam_id64: str) -> str:
        if not steam_id64.isdigit():
            raise ValueError("SteamID64 должен быть числом")
        value = int(steam_id64)
        return str(value - STEAM64_OFFSET) if value >= STEAM64_OFFSET else steam_id64

    @staticmethod
    def normalize_account_id(raw_id: str) -> str:
        raw_id = str(raw_id).strip()
        if not raw_id.isdigit():
            raise ValueError("account_id должен быть числом")
        return DeadlockApiClient.steam64_to_account_id(raw_id)

    async def resolve_steam_profile_to_account_id(self, profile_url: str) -> str | None:
        normalized = profile_url.strip()
        direct_match = re.match(r"^https?://steamcommunity\.com/profiles/(\d+)/?", normalized, flags=re.IGNORECASE)
        if direct_match:
            return self.steam64_to_account_id(direct_match.group(1))

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
            return self.steam64_to_account_id(steam_id64.strip()) if steam_id64 else None
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, ElementTree.ParseError):
            logger.exception("Не удалось разрешить Steam профиль: %s", profile_url)
            return None

    async def resolve_steam_profile_to_player_id(self, profile_url: str) -> str | None:
        """Совместимость: в проекте поле БД называется player_id, но это account_id."""
        return await self.resolve_steam_profile_to_account_id(profile_url)

    async def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        retries = 4
        for attempt in range(retries):
            await self.rate_limiter.wait()
            try:
                response = await self.client.request(method, path, params=params)
                status = response.status_code
                if status == 404:
                    raise DeadlockApiNotFoundError(f"404 для маршрута {method} {path}")
                if status == 429 or status >= 500:
                    raise DeadlockApiTemporaryError(f"Временная ошибка {status} для {method} {path}")
                if status >= 400:
                    raise DeadlockApiError(f"Ошибка API {status} для {method} {path}: {response.text[:200]}")
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == retries - 1:
                    raise DeadlockApiTemporaryError(f"Сетевая ошибка для {method} {path}: {exc}") from exc
                backoff = 2**attempt
                logger.warning("Сетевая ошибка Deadlock API, повтор через %s сек", backoff)
                await asyncio.sleep(backoff)
            except DeadlockApiTemporaryError:
                if attempt == retries - 1:
                    raise
                backoff = 2**attempt
                logger.warning("Временная ошибка Deadlock API, повтор через %s сек", backoff)
                await asyncio.sleep(backoff)
            except ValueError as exc:
                raise DeadlockApiError(f"Некорректный JSON от API для {method} {path}") from exc
        raise RuntimeError("Недостижимая ветка")

    async def get_match_history(self, account_id: str) -> list[dict[str, Any]]:
        account_id = self.normalize_account_id(account_id)
        data = await self._request("GET", self.routes.match_history.format(account_id=account_id))
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("matches", []) if isinstance(data.get("matches", []), list) else []
        return []

    async def get_player_recent_matches(self, player_id: str) -> list[dict[str, Any]]:
        """Совместимость по имени метода: возвращает match-history по account_id."""
        return await self.get_match_history(player_id)

    async def get_player_profile(self, player_id: str) -> dict[str, Any]:
        account_id = self.normalize_account_id(player_id)
        data = await self._request("GET", self.routes.steam_profile.format(account_id=account_id))
        if isinstance(data, dict):
            return data
        return {"account_id": account_id}

    async def get_match(self, match_id: str) -> dict[str, Any]:
        if not self.routes.match_details:
            raise DeadlockApiUnsupportedRouteError(
                "Маршрут деталей матча не подтверждён. Укажите routes.match_details после проверки docs."
            )
        data = await self._request("GET", self.routes.match_details.format(match_id=match_id))
        return data if isinstance(data, dict) else {}

    async def resolve_player(self, query: str) -> list[dict[str, Any]]:
        raise DeadlockApiUnsupportedRouteError(
            "Поиск игрока по нику отключён: маршрут не подтверждён (старый /players/search удалён)."
        )

    @staticmethod
    def parse_match_for_player(match_payload: dict[str, Any], player_id: str) -> dict[str, Any]:
        player_stats = next(
            (
                p
                for p in match_payload.get("players", [])
                if str(p.get("player_id") or p.get("account_id")) == str(player_id)
            ),
            {},
        )
        started_at = (
            match_payload.get("started_at")
            or match_payload.get("start_time")
            or datetime.now(timezone.utc).isoformat()
        )
        return {
            "match_id": str(match_payload.get("match_id") or match_payload.get("id") or ""),
            "match_datetime": started_at,
            "duration_seconds": int(match_payload.get("duration_seconds") or match_payload.get("duration") or 0),
            "hero_name": str(player_stats.get("hero_name") or match_payload.get("hero_name") or "Неизвестный герой"),
            "is_win": bool(player_stats.get("is_win") or match_payload.get("is_win") or False),
            "kills": int(player_stats.get("kills") or match_payload.get("kills") or 0),
            "deaths": int(player_stats.get("deaths") or match_payload.get("deaths") or 0),
            "assists": int(player_stats.get("assists") or match_payload.get("assists") or 0),
            "souls": int(player_stats.get("souls") or match_payload.get("souls") or 0),
            "damage": int(player_stats.get("damage") or match_payload.get("damage") or 0),
            "items": [str(i) for i in (player_stats.get("items") or match_payload.get("items") or [])][:6],
            "team_damage_rank": player_stats.get("team_damage_rank"),
            "team_souls_rank": player_stats.get("team_souls_rank"),
            "raw_payload": match_payload,
        }
