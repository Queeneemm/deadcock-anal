from pathlib import Path

from PIL import ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"

_FONT_CANDIDATES = {
    False: (
        FONTS_DIR / "DejaVuSans.ttf",
        FONTS_DIR / "NotoSans-Regular.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
    ),
    True: (
        FONTS_DIR / "DejaVuSans-Bold.ttf",
        FONTS_DIR / "NotoSans-Bold.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
    ),
}

_UNSUPPORTED_REPLACEMENTS = {
    "🏆": "#1",
    "🥇": "#1",
    "⭐": "*",
    "✅": "[OK]",
    "❌": "[X]",
    "⚠": "!",
    "⚠️": "!",
    "🔥": "!",
    "💀": "x",
    "📅": "",
    "⏱": "",
    "🎯": "",
    "ℹ": "i",
}


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_path in _FONT_CANDIDATES[bold]:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default(size=size)


def safe_text(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> str:
    normalized = text
    for source, target in _UNSUPPORTED_REPLACEMENTS.items():
        normalized = normalized.replace(source, target)

    safe_chars: list[str] = []
    for char in normalized:
        if char in {"\n", "\t"}:
            safe_chars.append(char)
            continue
        try:
            bbox = font.getbbox(char)
        except Exception:
            bbox = None
        if bbox is None:
            safe_chars.append("?")
            continue
        if bbox[0] == bbox[2] and bbox[1] == bbox[3]:
            safe_chars.append("?")
            continue
        safe_chars.append(char)
    return "".join(safe_chars)
