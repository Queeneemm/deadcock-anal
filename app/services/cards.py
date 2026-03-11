from pathlib import Path
from textwrap import shorten

from PIL import Image, ImageDraw

from app.clients.assets import AssetsClient
from app.models import AnalyticsResult, MatchSummary
from app.utils.fonts import get_font, safe_text
from app.utils.image import crop_cover, load_rgba, rounded_rectangle_overlay


class CardRenderer:
    def __init__(self, assets_client: AssetsClient, output_dir: Path):
        self.assets_client = assets_client
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def render(
        self,
        player_name: str,
        summary: MatchSummary,
        analytics: AnalyticsResult,
    ) -> Path:
        card = Image.new("RGBA", (1080, 1350), (18, 20, 28, 255))
        draw = ImageDraw.Draw(card)
        font_title = get_font(42, bold=True)
        font_text = get_font(28, bold=True)
        font_small = get_font(22)

        hero_asset = await self.assets_client.get_hero_asset_by_id(summary.hero_id or 0)
        hero_img = crop_cover(load_rgba(hero_asset), (1080, 1350))
        card.alpha_composite(hero_img, (0, 0))
        card.alpha_composite(Image.new("RGBA", (1080, 1350), (10, 12, 16, 165)), (0, 0))

        accent = (34, 197, 94, 255) if summary.is_win else (239, 68, 68, 255)
        card.alpha_composite(rounded_rectangle_overlay((1020, 260), 24, (25, 27, 36, 210)), (30, 30))
        draw.rectangle((30, 30, 44, 290), fill=accent)

        result = "Победа" if summary.is_win else "Поражение"
        draw.text((70, 55), safe_text(f"{player_name} — {summary.hero_name}", font_title), fill=(255, 255, 255), font=font_title)
        draw.text((70, 115), safe_text(f"Результат: {result}", font_text), fill=accent, font=font_text)
        draw.text((70, 160), safe_text(f"Матч ID: {summary.match_id}", font_small), fill=(220, 220, 220), font=font_small)
        draw.text((70, 195), safe_text(f"Дата: {summary.match_datetime.strftime('%d.%m.%Y %H:%M')}", font_small), fill=(180, 180, 185), font=font_small)
        draw.text((70, 230), safe_text(f"Длительность: {summary.duration_seconds // 60} мин", font_small), fill=(180, 180, 185), font=font_small)

        card.alpha_composite(rounded_rectangle_overlay((1020, 170), 20, (20, 22, 30, 220)), (30, 320))
        draw.text(
            (70, 370),
            safe_text(
                f"K/D/A: {summary.kills}/{summary.deaths}/{summary.assists}    Души: {summary.souls}    Урон: {summary.damage}",
                font_text,
            ),
            fill=(255, 255, 255),
            font=font_text,
        )

        y = 520
        sections = [
            ("Что было плохо", analytics.bad_points),
            ("Что улучшилось с прошлого матча", analytics.improved_points),
            ("Анти-тильт", [analytics.anti_tilt]),
            (
                "Лучший герой недели",
                [
                    f"{analytics.best_hero_week['hero_name']} — матчей: {analytics.best_hero_week['matches']}, винрейт: {analytics.best_hero_week['winrate']}%"
                ],
            ),
        ]
        for title, lines in sections:
            card.alpha_composite(rounded_rectangle_overlay((1020, 150), 20, (20, 22, 30, 220)), (30, y))
            draw.text((60, y + 18), safe_text(title, font_text), fill=(255, 255, 255), font=font_text)
            safe_lines = [safe_text(shorten(line, width=110, placeholder="…"), font_small) for line in lines[:2]]
            draw.text((60, y + 62), "\n".join(f"• {line}" for line in safe_lines), fill=(193, 198, 206), font=font_small)
            y += 165

        icons_y = 1210
        for index, item in enumerate(summary.items[:6]):
            icon = await self.assets_client.get_item_asset(item)
            item_img = load_rgba(icon, (72, 72))
            card.alpha_composite(rounded_rectangle_overlay((80, 80), 16, (30, 32, 40, 220)), (60 + index * 90, icons_y - 4))
            card.alpha_composite(item_img, (64 + index * 90, icons_y))

        draw.text((780, 1308), safe_text("DeadCock ANALis", font_small), fill=(130, 130, 140), font=font_small)

        output = self.output_dir / f"match_{summary.match_id}_{player_name}.png"
        card.convert("RGB").save(output, "PNG")
        return output

    async def render_dashboard(self, player_name: str, hero_id: int, rows: list[tuple[str, str]]) -> Path:
        card = Image.new("RGBA", (1080, 1350), (18, 20, 28, 255))
        draw = ImageDraw.Draw(card)
        font_title = get_font(44, bold=True)
        font_text = get_font(30, bold=True)
        font_small = get_font(24)

        hero_asset = await self.assets_client.get_hero_asset_by_id(hero_id)
        hero_img = crop_cover(load_rgba(hero_asset), (1080, 1350))
        card.alpha_composite(hero_img, (0, 0))
        card.alpha_composite(Image.new("RGBA", (1080, 1350), (10, 12, 16, 175)), (0, 0))
        card.alpha_composite(rounded_rectangle_overlay((1020, 120), 24, (25, 27, 36, 210)), (30, 30))
        draw.text((60, 68), safe_text(f"Дашборд: {player_name}", font_title), fill=(255, 255, 255), font=font_title)

        y = 190
        for title, value in rows:
            card.alpha_composite(rounded_rectangle_overlay((1020, 140), 18, (20, 22, 30, 220)), (30, y))
            draw.text((60, y + 18), safe_text(title, font_text), fill=(220, 220, 220), font=font_text)
            draw.text((60, y + 72), safe_text(shorten(value, width=90, placeholder="…"), font_small), fill=(255, 255, 255), font=font_small)
            y += 155

        output = self.output_dir / f"dashboard_{player_name}.png"
        card.convert("RGB").save(output, "PNG")
        return output
