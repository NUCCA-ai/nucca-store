"""Получение актуального курса юаня с Telegram-канала @elvnpay.

Канал публикует курс ежедневно. Берём последние сообщения с публичной
веб-версии канала (t.me/s/...), вытаскиваем числа, похожие на курс,
и выбираем наименьшее — это тариф для сумм от 1000¥ (оптовый).

Если что-то пошло не так — возвращаем запасной курс из config.json,
чтобы публикация никогда не падала целиком.
"""

import re
import html
import urllib.request

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
             "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"

MSG_RE = re.compile(
    r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
    re.S,
)
TAG_RE = re.compile(r"<[^>]+>")
NUM_RE = re.compile(r"\b(\d{1,2}[.,]\d{1,2})\b")


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _clean(chunk: str) -> str:
    chunk = chunk.replace("<br/>", "\n").replace("<br>", "\n")
    return html.unescape(TAG_RE.sub(" ", chunk))


def fetch_rate(cfg: dict) -> tuple[float, str]:
    """Возвращает (курс_без_буфера, источник)."""
    fallback = float(cfg["rate_fallback"])
    lo, hi = float(cfg["rate_min"]), float(cfg["rate_max"])

    try:
        page = _fetch(cfg["rate_source"])
    except Exception as exc:  # сеть недоступна
        return fallback, f"запасной курс (канал недоступен: {exc})"

    messages = [_clean(m) for m in MSG_RE.findall(page)]
    if not messages:
        return fallback, "запасной курс (не нашла сообщений в канале)"

    # Идём от самых свежих сообщений к старым.
    for text in reversed(messages[-8:]):
        low = text.lower()
        if not any(k in low for k in ("¥", "юан", "курс", "cny", "rmb")):
            continue

        found = []
        for raw in NUM_RE.findall(text):
            value = float(raw.replace(",", "."))
            if lo <= value <= hi:
                found.append(value)

        if found:
            # Оптовый тариф (от 1000¥) всегда ниже розничного.
            rate = min(found)
            # Защита от опечатки в канале: слишком далеко от ожидаемого —
            # не доверяем и берём запасной курс.
            if abs(rate - fallback) / fallback > 0.20:
                return fallback, (
                    f"запасной курс (в канале {rate}, слишком далеко "
                    f"от ожидаемого {fallback})"
                )
            return rate, "канал @elvnpay"

    return fallback, "запасной курс (в свежих постах курс не найден)"


def effective_rate(cfg: dict) -> tuple[float, str]:
    """Курс с накинутым буфером — именно он идёт в расчёт цены."""
    base, source = fetch_rate(cfg)
    return round(base + float(cfg["rate_buffer"]), 2), source


if __name__ == "__main__":
    import json
    import pathlib

    config = json.loads(
        (pathlib.Path(__file__).resolve().parents[1] / "config.json").read_text("utf-8")
    )
    value, src = fetch_rate(config)
    print(f"курс: {value} ₽/¥   источник: {src}")
    print(f"в расчёт пойдёт: {round(value + config['rate_buffer'], 2)} ₽/¥")
