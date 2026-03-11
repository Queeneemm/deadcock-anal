"""Словарь имён героев Deadlock."""

HERO_NAME_MAP: dict[int, str] = {
    1: "Infernus",
    2: "Seven",
    3: "Vindicta",
    4: "Lady Geist",
    6: "Abrams",
    7: "Wraith",
    8: "McGinnis",
    10: "Paradox",
    11: "Dynamo",
    12: "Kelvin",
    13: "Haze",
    14: "Holliday",
    15: "Bebop",
    16: "Calico",
    17: "Grey Talon",
    18: "Mo & Krill",
    19: "Shiv",
    20: "Ivy",
    25: "Warden",
    27: "Yamato",
    31: "Lash",
    35: "Viscous",
    50: "Pocket",
    52: "Mirage",
    58: "Vyper",
    60: "Sinclair",
    63: "Mina",
    64: "Drifter",
    65: "Venator",
    66: "Victor",
    67: "Paige",
    69: "The Doorman",
    79: "Rem",
    72: "Billy",
    76: "Graves",
    77: "Apollo",
    80: "Silver",
    81: "Celeste",
}


def hero_name_by_id(hero_id: int | str | None) -> str:
    if hero_id is None:
        return "Неизвестный герой"
    try:
        value = int(float(hero_id))
    except (TypeError, ValueError):
        return f"Hero #{hero_id}"
    return HERO_NAME_MAP.get(value, f"Hero #{value}")
