"""Временный helper для имён героев.

TODO: подключить подтверждённый источник hero_id -> hero_name.
"""

HERO_NAME_MAP: dict[int, str] = {}


def hero_name_by_id(hero_id: int | str | None) -> str:
    if hero_id is None:
        return "Неизвестный герой"
    try:
        value = int(hero_id)
    except (TypeError, ValueError):
        return f"Hero #{hero_id}"
    return HERO_NAME_MAP.get(value, f"Hero #{value}")
