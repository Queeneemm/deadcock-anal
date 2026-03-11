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

    @staticmethod
    def _damage_reliable(matches: list[MatchSummary]) -> bool:
        return bool(matches and sum(1 for m in matches if m.damage > 0) / len(matches) >= 0.5)

    def _build_bad_points(self, current: MatchSummary, hero_history: list[MatchSummary]) -> list[str]:
        sample = [m for m in hero_history if m.match_id != current.match_id][:10]
        if not sample:
            return ["Недостаточно истории по этому герою для точного разбора."]

        points: list[str] = []
        avg_deaths = mean(m.deaths for m in sample)
        avg_souls = mean(m.souls for m in sample)
        avg_kda = mean((m.kills + m.assists) / max(m.deaths, 1) for m in sample)
        cur_kda = (current.kills + current.assists) / max(current.deaths, 1)

        if current.deaths > avg_deaths * 1.25:
            points.append(f"Смертей больше нормы: {current.deaths} против {avg_deaths:.1f}.")
        if current.souls < avg_souls * 0.8:
            points.append(f"Экономика просела: {current.souls} против среднего {avg_souls:.0f}.")
        if cur_kda < avg_kda * 0.8:
            points.append(f"KDA ниже привычного уровня: {cur_kda:.2f} против {avg_kda:.2f}.")
        if self._damage_reliable(sample) and current.damage > 0:
            avg_damage = mean(m.damage for m in sample)
            if current.damage < avg_damage * 0.8:
                points.append(f"Урон ниже среднего: {current.damage} против {avg_damage:.0f}.")

        return points[:3] or ["Явных провалов нет — матч был нестабильным по темпу."]

    def _build_improvements(self, current: MatchSummary, recent_matches: list[MatchSummary]) -> list[str]:
        prev = next((m for m in recent_matches if m.match_id != current.match_id), None)
        if not prev:
            return ["Нет предыдущего матча для сравнения."]

        points: list[str] = []
        if current.souls > prev.souls:
            points.append(f"Нетворс вырос относительно прошлого матча: +{current.souls - prev.souls}.")
        if current.deaths < prev.deaths:
            points.append(f"Смертей стало меньше: на {prev.deaths - current.deaths}.")
        cur_kda = (current.kills + current.assists) / max(current.deaths, 1)
        prev_kda = (prev.kills + prev.assists) / max(prev.deaths, 1)
        if cur_kda > prev_kda:
            points.append(f"KDA вырос с {prev_kda:.2f} до {cur_kda:.2f}.")
        if self._damage_reliable([current, prev]) and current.damage > prev.damage:
            points.append(f"Урон увеличился на {current.damage - prev.damage}.")
        if current.is_win and not prev.is_win:
            points.append("Классный камбэк: после поражения сразу победа.")
        return points[:3] or ["Пока нет явных улучшений относительно прошлого матча."]

    def _best_hero_week(self, week_matches: list[MatchSummary]) -> dict:
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        filtered = [m for m in week_matches if m.match_datetime.replace(tzinfo=timezone.utc) >= week_ago]
        if not filtered:
            return {"hero_name": "Нет данных", "matches": 0, "winrate": 0.0}

        by_hero: dict[str, list[MatchSummary]] = defaultdict(list)
        for match in filtered:
            by_hero[match.hero_name].append(match)

        candidates = []
        for hero, matches in by_hero.items():
            wins = sum(1 for m in matches if m.is_win)
            winrate = wins / len(matches)
            kda = mean((m.kills + m.assists) / max(m.deaths, 1) for m in matches)
            candidates.append((hero, len(matches), winrate, kda))

        hero, count, winrate, _ = sorted(candidates, key=lambda x: (x[2], x[1], x[3]), reverse=True)[0]
        return {"hero_name": hero, "matches": count, "winrate": round(winrate * 100, 1)}

    def _build_anti_tilt(self, current: MatchSummary, hero_history: list[MatchSummary]) -> str:
        kda = (current.kills + current.assists) / max(current.deaths, 1)
        if current.is_win:
            return "Победа — сильный шаг к стабильности. Повтори решения, которые сработали."
        if kda >= 2:
            return "Даже в тяжёлом матче KDA остался достойным — механика и импакт были на месте."
        if hero_history:
            avg_souls = mean(m.souls for m in hero_history)
            if current.souls > avg_souls:
                return "Экономика выше средней по этому герою — это хороший признак формы."
            avg_deaths = mean(m.deaths for m in hero_history)
            if current.deaths < avg_deaths:
                return "Смертей меньше среднего — позиционка уже даёт результат."
        return "Тяжёлый матч, но прогресс строится через KDA, экономику и меньше смертей."
