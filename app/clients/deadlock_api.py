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
    match_history: str = "players/{account_id}/match-history"
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
        matches = await self.get_match_history(account_id)
        if not matches:
            return {
                "account_id": account_id,
                "display_name": f"Игрок {account_id}",
                "matches_count": 0,
            }

        recent = matches[:20]
        parsed = [self.parse_match_for_player(item, account_id) for item in recent]
        avg_kda = sum((m["kills"] + m["assists"]) / max(m["deaths"], 1) for m in parsed) / len(parsed)
        avg_souls = sum(int(m["souls"]) for m in parsed) / len(parsed)
        avg_last_hits = sum(int(item.get("last_hits") or 0) for item in recent) / len(recent)
        wins = sum(1 for m in parsed if m["is_win"])

        hero_freq: dict[str, int] = {}
        for m in parsed:
            hero_name = str(m["hero_name"])
            hero_freq[hero_name] = hero_freq.get(hero_name, 0) + 1

        top_heroes = sorted(hero_freq.items(), key=lambda kv: kv[1], reverse=True)[:3]
        return {
            "account_id": account_id,
            "display_name": f"Игрок {account_id}",
            "matches_count": len(recent),
            "avg_kda": round(avg_kda, 2),
            "avg_net_worth": round(avg_souls, 1),
            "avg_last_hits": round(avg_last_hits, 1),
            "top_heroes": [{"hero_name": hero, "matches": count} for hero, count in top_heroes],
            "winrate": round((wins / len(parsed)) * 100, 1),
            "profile_source": "match_history_fallback",
        }

    async def get_match(self, match_id: str) -> dict[str, Any]:
        if not self.routes.match_details:
            raise DeadlockApiUnsupportedRouteError(
                "Маршрут деталей матча не подтверждён. Укажите routes.match_details после проверки docs."
            )
        data = await self._request("GET", self.routes.match_details.format(match_id=match_id))
        return data if isinstance(data, dict) else {}

    async def resolve_player(self, query: str) -> list[dict[str, Any]]:
        normalized = query.strip()
        if not normalized:
            return []

        if normalized.isdigit():
            return [{"account_id": self.normalize_account_id(normalized), "source": "numeric"}]

        if re.match(r"^https?://steamcommunity\.com/profiles/\d+/?", normalized, flags=re.IGNORECASE):
            account_id = await self.resolve_steam_profile_to_account_id(normalized)
            return [{"account_id": account_id, "source": "steamcommunity_profiles"}] if account_id else []

        if re.match(r"^https?://steamcommunity\.com/id/[A-Za-z0-9_\-]+/?", normalized, flags=re.IGNORECASE):
            account_id = await self.resolve_steam_profile_to_account_id(normalized)
            return [{"account_id": account_id, "source": "steamcommunity_id"}] if account_id else []

        raise DeadlockApiError(
            "Поддерживаются только account_id, Steam64 или ссылки steamcommunity.com/profiles/... и /id/..."
        )

    @staticmethod
    def parse_match_for_player(match_payload: dict[str, Any], player_id: str) -> dict[str, Any]:
        _ = player_id
        start_time = match_payload.get("start_time")
        if isinstance(start_time, (int, float)):
            started_at = datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        hero_id = match_payload.get("hero_id")
        hero_name = f"Hero #{hero_id}" if hero_id is not None else "Неизвестный герой"
        match_result = str(match_payload.get("match_result") or "").lower()
        player_team = str(match_payload.get("player_team") or "").lower()

        is_win = False
        if match_result in {"win", "won", "victory", "true", "1"}:
            is_win = True
        elif match_result in {"loss", "lose", "lost", "defeat", "false", "0"}:
            is_win = False
        elif match_result and player_team and match_result == player_team:
            is_win = True

        return {
            "match_id": str(match_payload.get("match_id") or match_payload.get("id") or ""),
            "match_datetime": started_at,
            "duration_seconds": int(match_payload.get("match_duration_s") or match_payload.get("duration_seconds") or 0),
            "hero_name": hero_name,
            "is_win": is_win,
            "kills": int(match_payload.get("player_kills") or 0),
            "deaths": int(match_payload.get("player_deaths") or 0),
            "assists": int(match_payload.get("player_assists") or 0),
            "souls": int(match_payload.get("net_worth") or 0),
            "damage": 0,
            "items": [],
            "team_damage_rank": None,
            "team_souls_rank": None,
            "raw_payload": match_payload,
        }
