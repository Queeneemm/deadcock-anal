from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class TrackedPlayer:
    id: int
    telegram_user_id: int
    player_id: str
    display_name: str
    steam_profile_url: str | None
    is_enabled: bool
    auto_reports_enabled: bool
    created_at: str
    last_seen_match_id: str | None
    last_sent_match_id: str | None


@dataclass(slots=True)
class MatchSummary:
    match_id: str
    match_datetime: datetime
    hero_name: str
    is_win: bool
    kills: int
    deaths: int
    assists: int
    souls: int
    damage: int
    duration_seconds: int
    items: list[str]
    team_damage_rank: int | None = None
    team_souls_rank: int | None = None
    raw_payload: dict[str, Any] | None = None


@dataclass(slots=True)
class AnalyticsResult:
    bad_points: list[str]
    improved_points: list[str]
    anti_tilt: str
    best_hero_week: dict[str, Any]
