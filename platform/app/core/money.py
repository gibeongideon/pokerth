"""How amounts (integer US cents) are written for players."""


def money(cents: int) -> str:
    """``$12.50``; amounts under a dollar in cents (``11¢``); zero is ``$0.00``."""
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    if 0 < c < 100:
        return f"{sign}{c}¢"
    return f"{sign}${c // 100:,}.{c % 100:02d}"
