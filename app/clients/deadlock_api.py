import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree

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
    steam_profiles: str = "players/steam"
    steam_search: str = "players/steam-search"
    match_history: str = "players/{account_id}/match-history"
    hero_stats: str = "players/hero-stats"
    enemy_stats: str = "players/{account_id}/enemy-stats"
    mate_stats: str = "players/{account_id}/mate-stats"
    party_stats: str = "players/{account_id}/party-stats"
    mmr: str = "players/mmr"
    leaderboard: str = "leaderboard/{region}"
    analytics_hero_synergy: str = "analytics/hero-synergy-stats"
    analytics_hero_counter: str = "analytics/hero-counter-stats"
    analytics_hero_stats: str = "analytics/hero-stats"
    info: str = "info"


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
    def account_id_to_steam64(account_id: str | int) -> str:
        raw = str(account_id).strip()
        if not raw.isdigit():
            raise ValueError("account_id должен быть числом")
        return str(int(raw) + STEAM64_OFFSET)

    @staticmethod
    def normalize_account_id(raw_id: str | int) -> str:
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
        return await self.resolve_steam_profile_to_account_id(profile_url)

    @staticmethod
    def _extract_list_payload(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("players", "results", "data", "items", "matches", "hero_stats", "stats"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

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

    async def search_steam_profiles(self, query: str) -> list[dict[str, Any]]:
        data = await self._request("GET", self.routes.steam_search, params={"search_query": query})
        return self._extract_list_payload(data)

    async def get_steam_profiles(self, account_ids: list[str] | list[int]) -> list[dict[str, Any]]:
        normalized = [self.normalize_account_id(value) for value in account_ids]
        data = await self._request("GET", self.routes.steam_profiles, params={"account_ids": ",".join(normalized)})
        return self._extract_list_payload(data)

    async def get_match_history(self, account_id: str | int) -> list[dict[str, Any]]:
        normalized = self.normalize_account_id(account_id)
        data = await self._request("GET", self.routes.match_history.format(account_id=normalized))
        return self._extract_list_payload(data)

    async def get_player_recent_matches(self, account_id: str | int, limit: int = 20) -> list[dict[str, Any]]:
        return (await self.get_match_history(account_id))[:limit]

    async def get_player_hero_stats(self, account_ids: list[str] | list[int]) -> list[dict[str, Any]]:
        normalized = [self.normalize_account_id(value) for value in account_ids]
        data = await self._request("GET", self.routes.hero_stats, params={"account_ids": ",".join(normalized)})
        return self._extract_list_payload(data)

    async def get_player_enemy_stats(self, account_id: str | int) -> list[dict[str, Any]]:
        normalized = self.normalize_account_id(account_id)
        data = await self._request("GET", self.routes.enemy_stats.format(account_id=normalized))
        return self._extract_list_payload(data)

    async def get_player_mate_stats(self, account_id: str | int) -> list[dict[str, Any]]:
        normalized = self.normalize_account_id(account_id)
        data = await self._request("GET", self.routes.mate_stats.format(account_id=normalized))
        return self._extract_list_payload(data)

    async def get_player_party_stats(self, account_id: str | int) -> list[dict[str, Any]]:
        normalized = self.normalize_account_id(account_id)
        data = await self._request("GET", self.routes.party_stats.format(account_id=normalized))
        return self._extract_list_payload(data)

    async def get_player_mmr(self, account_ids: list[str] | list[int]) -> list[dict[str, Any]]:
        normalized = [self.normalize_account_id(value) for value in account_ids]
        data = await self._request("GET", self.routes.mmr, params={"account_ids": ",".join(normalized)})
        return self._extract_list_payload(data)

    async def get_leaderboard(self, region: str) -> list[dict[str, Any]]:
        data = await self._request("GET", self.routes.leaderboard.format(region=region))
        return self._extract_list_payload(data)

    async def get_global_hero_stats(self) -> list[dict[str, Any]]:
        data = await self._request("GET", self.routes.analytics_hero_stats)
        return self._extract_list_payload(data)

    async def get_hero_synergy_stats(self) -> list[dict[str, Any]]:
        data = await self._request("GET", self.routes.analytics_hero_synergy)
        return self._extract_list_payload(data)

    async def get_hero_counter_stats(self) -> list[dict[str, Any]]:
        data = await self._request("GET", self.routes.analytics_hero_counter)
        return self._extract_list_payload(data)

    async def get_info(self) -> dict[str, Any]:
        data = await self._request("GET", self.routes.info)
        return data if isinstance(data, dict) else {"raw": data}

    async def get_player_profile(self, player_id: str) -> dict[str, Any]:
        account_id = self.normalize_account_id(player_id)
        steam_profiles, mmr_stats, hero_stats, history = await asyncio.gather(
            self.get_steam_profiles([account_id]),
            self.get_player_mmr([account_id]),
            self.get_player_hero_stats([account_id]),
            self.get_player_recent_matches(account_id, limit=20),
            return_exceptions=True,
        )

        steam = steam_profiles[0] if isinstance(steam_profiles, list) and steam_profiles else {}
        mmr = mmr_stats[0] if isinstance(mmr_stats, list) and mmr_stats else {}
        parsed_matches = [self.parse_match_for_player(item, account_id) for item in history] if isinstance(history, list) else []

        winrate = round((sum(1 for m in parsed_matches if m["is_win"]) / len(parsed_matches)) * 100, 1) if parsed_matches else 0.0
        avg_kda = (
            round(sum((m["kills"] + m["assists"]) / max(m["deaths"], 1) for m in parsed_matches) / len(parsed_matches), 2)
            if parsed_matches
            else 0.0
        )
        top_heroes: list[dict[str, Any]] = []
        if isinstance(hero_stats, list) and hero_stats:
            for hero in sorted(hero_stats, key=lambda item: int(item.get("matches_played") or item.get("matches") or 0), reverse=True)[:3]:
                hero_id = hero.get("hero_id")
                top_heroes.append({"hero_name": f"Hero #{hero_id}" if hero_id is not None else "Неизвестный герой", "matches": int(hero.get("matches_played") or hero.get("matches") or 0)})

        return {
            "account_id": account_id,
            "display_name": str(steam.get("personaname") or steam.get("name") or f"Игрок {account_id}"),
            "steam_url": str(steam.get("profileurl") or steam.get("steam_profile_url") or f"https://steamcommunity.com/profiles/{self.account_id_to_steam64(account_id)}"),
            "matches_count": len(parsed_matches),
            "avg_kda": avg_kda,
            "avg_net_worth": round(sum(m["souls"] for m in parsed_matches) / len(parsed_matches), 1) if parsed_matches else 0.0,
            "avg_last_hits": round(sum(int((m["raw_payload"] or {}).get("last_hits") or 0) for m in parsed_matches) / len(parsed_matches), 1) if parsed_matches else 0.0,
            "top_heroes": top_heroes,
            "winrate": winrate,
            "mmr": mmr.get("mmr") or mmr.get("rank") or mmr.get("score"),
            "profile_source": "steam+mmr+hero_stats+match_history",
        }

    async def get_match(self, match_id: str) -> dict[str, Any]:
        raise DeadlockApiUnsupportedRouteError(
            f"Маршрут деталей матча для match_id={match_id} не подтверждён в API. Используйте /players/{{account_id}}/match-history."
        )

    async def resolve_player(self, query: str) -> list[dict[str, Any]]:
        normalized = query.strip()
        if not normalized:
            return []

        if normalized.isdigit():
            account_id = self.normalize_account_id(normalized)
            profile = await self.get_steam_profiles([account_id])
            if profile:
                return [{**self._map_steam_profile(profile[0]), "account_id": account_id, "source": "numeric"}]
            return [{"account_id": account_id, "source": "numeric"}]

        if re.match(r"^https?://steamcommunity\.com/(profiles|id)/", normalized, flags=re.IGNORECASE):
            account_id = await self.resolve_steam_profile_to_account_id(normalized)
            if not account_id:
                return []
            profile = await self.get_steam_profiles([account_id])
            if profile:
                return [{**self._map_steam_profile(profile[0]), "account_id": account_id, "source": "steamcommunity_url"}]
            return [{"account_id": account_id, "source": "steamcommunity_url"}]

        profiles = await self.search_steam_profiles(normalized)
        return [{**self._map_steam_profile(profile), "source": "steam_search"} for profile in profiles]

    def _map_steam_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        account_raw = payload.get("account_id") or payload.get("accountid") or payload.get("id")
        account_id = self.normalize_account_id(account_raw) if account_raw is not None and str(account_raw).isdigit() else None
        steam_id64 = payload.get("steamid") or payload.get("steam_id")
        if not steam_id64 and account_id:
            steam_id64 = self.account_id_to_steam64(account_id)
        profile_url = payload.get("profileurl") or payload.get("steam_profile_url")
        if not profile_url and steam_id64:
            profile_url = f"https://steamcommunity.com/profiles/{steam_id64}"
        personaname = payload.get("personaname") or payload.get("name") or (f"Игрок {account_id}" if account_id else "Неизвестный игрок")
        return {
            "account_id": account_id,
            "steam_id64": str(steam_id64) if steam_id64 else None,
            "personaname": str(personaname),
            "profile_url": str(profile_url) if profile_url else None,
        }

    @staticmethod
    def parse_match_for_player(match_payload: dict[str, Any], player_id: str) -> dict[str, Any]:
        _ = player_id
        start_time = match_payload.get("start_time")
        if isinstance(start_time, (int, float)):
            started_at = datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        raw_hero_id = match_payload.get("hero_id")
        hero_id = int(raw_hero_id) if isinstance(raw_hero_id, (int, float, str)) and str(raw_hero_id).isdigit() else 0
        hero_name = f"Hero #{hero_id}" if hero_id > 0 else "Неизвестный герой"
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
            "hero_id": hero_id,
            "hero_name": hero_name,
            "is_win": is_win,
            "kills": int(match_payload.get("player_kills") or 0),
            "deaths": int(match_payload.get("player_deaths") or 0),
            "assists": int(match_payload.get("player_assists") or 0),
            "souls": int(match_payload.get("net_worth") or 0),
            "last_hits": int(match_payload.get("last_hits") or 0),
            "damage": int(match_payload.get("damage") or 0),
            "items": [],
            "team_damage_rank": None,
            "team_souls_rank": None,
            "raw_payload": match_payload,
        }
