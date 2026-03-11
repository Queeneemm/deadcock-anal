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
            return ["Not enough history on this hero for an accurate review."]

        points: list[str] = []
        avg_deaths = mean(m.deaths for m in sample)
        avg_souls = mean(m.souls for m in sample)
        avg_kda = mean((m.kills + m.assists) / max(m.deaths, 1) for m in sample)
        cur_kda = (current.kills + current.assists) / max(current.deaths, 1)

        if current.deaths > avg_deaths * 1.25:
            points.append(f"Deaths above your norm: {current.deaths} vs {avg_deaths:.1f}.")
        if current.souls < avg_souls * 0.8:
            points.append(f"Economy dropped: {current.souls} vs average {avg_souls:.0f}.")
        if cur_kda < avg_kda * 0.8:
            points.append(f"KDA below your usual level: {cur_kda:.2f} vs {avg_kda:.2f}.")
        if self._damage_reliable(sample) and current.damage > 0:
            avg_damage = mean(m.damage for m in sample)
            if current.damage < avg_damage * 0.8:
                points.append(f"Damage below your average: {current.damage} vs {avg_damage:.0f}.")

        return points[:3] or ["No obvious failures — the match was just unstable in tempo."]

    def _build_improvements(self, current: MatchSummary, recent_matches: list[MatchSummary]) -> list[str]:
        prev = next((m for m in recent_matches if m.match_id != current.match_id), None)
        if not prev:
            return ["No previous match to compare with."]

        points: list[str] = []
        if current.souls > prev.souls:
            points.append(f"Net worth improved vs previous match: +{current.souls - prev.souls}.")
        if current.deaths < prev.deaths:
            points.append(f"Fewer deaths: {prev.deaths - current.deaths} less.")
        cur_kda = (current.kills + current.assists) / max(current.deaths, 1)
        prev_kda = (prev.kills + prev.assists) / max(prev.deaths, 1)
        if cur_kda > prev_kda:
            points.append(f"KDA improved from {prev_kda:.2f} to {cur_kda:.2f}.")
        if self._damage_reliable([current, prev]) and current.damage > prev.damage:
            points.append(f"Damage increased by {current.damage - prev.damage}.")
        if current.is_win and not prev.is_win:
            points.append("You bounced back from a loss to a win.")
        return points[:3] or ["No clear improvements compared to the previous match yet."]

    def _best_hero_week(self, week_matches: list[MatchSummary]) -> dict:
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        filtered = [m for m in week_matches if m.match_datetime.replace(tzinfo=timezone.utc) >= week_ago]
        if not filtered:
            return {"hero_name": "No data", "matches": 0, "winrate": 0.0}

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
            return "A win is a strong step toward consistency — keep the decisions that worked."
        if kda >= 2:
            return "Even in a rough game, your KDA stayed solid — mechanics and impact were there."
        if hero_history:
            avg_souls = mean(m.souls for m in hero_history)
            if current.souls > avg_souls:
                return "Your economy was above your average on this hero — a good sign of form."
            avg_deaths = mean(m.deaths for m in hero_history)
            if current.deaths < avg_deaths:
                return "Deaths were below your average — better positioning is already paying off."
        return "Tough match, but progress comes from KDA, economy, and reducing deaths."
