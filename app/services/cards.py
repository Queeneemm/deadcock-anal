from pathlib import Path
from textwrap import shorten

from PIL import Image, ImageDraw, ImageFont

from app.clients.assets import AssetsClient
from app.models import AnalyticsResult, MatchSummary
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
        font_title = ImageFont.load_default(size=42)
        font_text = ImageFont.load_default(size=28)
        font_small = ImageFont.load_default(size=22)

        hero_asset = await self.assets_client.get_hero_assets(summary.hero_name)
        hero_img = crop_cover(load_rgba(hero_asset), (1080, 1350))
        card.alpha_composite(hero_img, (0, 0))
        card.alpha_composite(Image.new("RGBA", (1080, 1350), (10, 12, 16, 165)), (0, 0))

        accent = (34, 197, 94, 255) if summary.is_win else (239, 68, 68, 255)
        card.alpha_composite(rounded_rectangle_overlay((1020, 260), 24, (25, 27, 36, 210)), (30, 30))
        draw.rectangle((30, 30, 44, 290), fill=accent)

        result = "Победа" if summary.is_win else "Поражение"
        draw.text((70, 55), f"{player_name} — {summary.hero_name}", fill=(255, 255, 255), font=font_title)
        draw.text((70, 115), f"Результат: {result}", fill=accent, font=font_text)
        draw.text((70, 160), f"Матч ID: {summary.match_id}", fill=(220, 220, 220), font=font_small)
        draw.text((70, 195), f"Дата: {summary.match_datetime.strftime('%d.%m.%Y %H:%M')}", fill=(180, 180, 185), font=font_small)
        draw.text((70, 230), f"Длительность: {summary.duration_seconds // 60} мин", fill=(180, 180, 185), font=font_small)

        card.alpha_composite(rounded_rectangle_overlay((1020, 170), 20, (20, 22, 30, 220)), (30, 320))
        draw.text(
            (70, 370),
            f"K/D/A: {summary.kills}/{summary.deaths}/{summary.assists}    Souls: {summary.souls}    Damage: {summary.damage}",
            fill=(255, 255, 255),
            font=font_text,
        )

        y = 520
        sections = [
            ("Что было плохо", analytics.bad_points),
            ("Что улучшилось относительно прошлого матча", analytics.improved_points),
            ("Анти-тильт", [analytics.anti_tilt]),
            (
                "Лучший герой за неделю",
                [
                    f"{analytics.best_hero_week['hero_name']} — матчей: {analytics.best_hero_week['matches']}, "
                    f"winrate: {analytics.best_hero_week['winrate']}%"
                ],
            ),
        ]
        for title, lines in sections:
            card.alpha_composite(rounded_rectangle_overlay((1020, 150), 20, (20, 22, 30, 220)), (30, y))
            draw.text((60, y + 18), title, fill=(255, 255, 255), font=font_text)
            safe_lines = [shorten(line, width=110, placeholder="…") for line in lines[:2]]
            draw.text((60, y + 62), "\n".join(f"• {line}" for line in safe_lines), fill=(193, 198, 206), font=font_small)
            y += 165

        icons_y = 1210
        for index, item in enumerate(summary.items[:6]):
            icon = await self.assets_client.get_item_asset(item)
            item_img = load_rgba(icon, (72, 72))
            card.alpha_composite(rounded_rectangle_overlay((80, 80), 16, (30, 32, 40, 220)), (60 + index * 90, icons_y - 4))
            card.alpha_composite(item_img, (64 + index * 90, icons_y))

        draw.text((810, 1308), "Deadlock Scout Bot", fill=(130, 130, 140), font=font_small)

        output = self.output_dir / f"match_{summary.match_id}_{player_name}.png"
        card.convert("RGB").save(output, "PNG")
        return output
