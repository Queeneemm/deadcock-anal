from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean

from app.models import AnalyticsResult, MatchSummary


class AnalyticsService:
    def analyze(
        self,
        current: MatchSummary,
        recent_matches: list[MatchSummary],
        hero_history: list[MatchSummary],
        week_matches: list[MatchSummary],
    ) -> AnalyticsResult:
        bad_points = self._build_bad_points(current, hero_history)
        improved_points = self._build_improvements(current, recent_matches)
        anti_tilt = self._build_anti_tilt(current, hero_history)
        best_hero_week = self._best_hero_week(week_matches)
        return AnalyticsResult(
            bad_points=bad_points,
            improved_points=improved_points,
            anti_tilt=anti_tilt,
            best_hero_week=best_hero_week,
        )

    def _build_bad_points(self, current: MatchSummary, hero_history: list[MatchSummary]) -> list[str]:
        points: list[str] = []
        sample = [m for m in hero_history if m.match_id != current.match_id][:10]
        if not sample:
            return ["Недостаточно истории на этом герое для точного разбора."]

        avg_deaths = mean(m.deaths for m in sample)
        avg_damage = mean(m.damage for m in sample)
        avg_souls = mean(m.souls for m in sample)
        avg_kda = mean((m.kills + m.assists) / max(m.deaths, 1) for m in sample)
        cur_kda = (current.kills + current.assists) / max(current.deaths, 1)

        if current.deaths > avg_deaths * 1.25:
            points.append(f"Смертей больше нормы на герое: {current.deaths} против среднего {avg_deaths:.1f}.")
        if current.damage < avg_damage * 0.8:
            points.append(f"Урон ниже вашего среднего на этом герое ({current.damage} vs {avg_damage:.0f}).")
        if current.souls < avg_souls * 0.8:
            points.append(f"Темп по souls просел: {current.souls} против {avg_souls:.0f} в среднем.")
        if cur_kda < avg_kda * 0.8:
            points.append(f"KDA ниже типичного уровня: {cur_kda:.2f} vs {avg_kda:.2f}.")

        return points[:3] or ["Критичных просадок не найдено, матч скорее нестабильный по темпу."]

    def _build_improvements(self, current: MatchSummary, recent_matches: list[MatchSummary]) -> list[str]:
        prev = next((m for m in recent_matches if m.match_id != current.match_id), None)
        if not prev:
            return ["Нет прошлого матча для сравнения."]
        points: list[str] = []
        if current.damage > prev.damage:
            points.append(f"Урон вырос на {current.damage - prev.damage}.")
        if current.souls > prev.souls:
            points.append(f"Экономика лучше прошлого матча: +{current.souls - prev.souls} souls.")
        if current.deaths < prev.deaths:
            points.append(f"Игра аккуратнее: смертей меньше на {prev.deaths - current.deaths}.")
        cur_kda = (current.kills + current.assists) / max(current.deaths, 1)
        prev_kda = (prev.kills + prev.assists) / max(prev.deaths, 1)
        if cur_kda > prev_kda:
            points.append(f"KDA вырос с {prev_kda:.2f} до {cur_kda:.2f}.")
        return points[:3] or ["Явных улучшений относительно прошлого матча пока нет, это нормально."]

    def _best_hero_week(self, week_matches: list[MatchSummary]) -> dict:
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        filtered = [m for m in week_matches if m.match_datetime.replace(tzinfo=timezone.utc) >= week_ago]
        if not filtered:
            return {"hero_name": "Нет данных", "matches": 0, "winrate": 0.0}

        by_hero: dict[str, list[MatchSummary]] = defaultdict(list)
        for match in filtered:
            by_hero[match.hero_name].append(match)

        candidates = []
        for hero, matches in by_hero.items():
            if len(matches) < 2:
                continue
            wins = sum(1 for m in matches if m.is_win)
            winrate = wins / len(matches)
            kda = mean((m.kills + m.assists) / max(m.deaths, 1) for m in matches)
            avg_damage = mean(m.damage for m in matches)
            avg_souls = mean(m.souls for m in matches)
            candidates.append((hero, len(matches), winrate, kda, avg_damage, avg_souls))

        if not candidates:
            return {"hero_name": "Недостаточно матчей", "matches": len(filtered), "winrate": 0.0}

        hero, count, winrate, *_ = sorted(candidates, key=lambda x: (x[2], x[3], x[4] + x[5]), reverse=True)[0]
        return {"hero_name": hero, "matches": count, "winrate": round(winrate * 100, 1)}

    def _build_anti_tilt(self, current: MatchSummary, hero_history: list[MatchSummary]) -> str:
        kda = (current.kills + current.assists) / max(current.deaths, 1)
        if current.team_damage_rank and current.team_damage_rank <= 2:
            return "Плюс: вы вошли в топ-2 команды по урону."
        if current.team_souls_rank and current.team_souls_rank == 1:
            return "Плюс: лучший показатель souls в команде — отличный темп фарма."
        if hero_history:
            avg_damage = mean(m.damage for m in hero_history)
            if current.damage > avg_damage:
                return "Плюс: урон выше вашего среднего на этом герое."
        if kda >= 2:
            return "Плюс: достойный KDA, механика была на уровне даже в тяжёлой игре."
        return "Матч получился тяжёлым, но это рабочий материал для следующего шага вперёд."
