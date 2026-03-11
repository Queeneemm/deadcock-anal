from pathlib import Path

from PIL import Image, ImageDraw


def load_rgba(path: Path, size: tuple[int, int] | None = None) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    if size:
        image = image.resize(size)
    return image


def rounded_rectangle_overlay(size: tuple[int, int], radius: int, color: tuple[int, int, int, int]) -> Image.Image:
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=color)
    return overlay


def crop_cover(img: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    tw, th = target_size
    iw, ih = img.size
    scale = max(tw / iw, th / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    resized = img.resize((nw, nh))
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return resized.crop((left, top, left + tw, top + th))
