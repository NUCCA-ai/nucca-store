"""Ежедневная публикация товаров в Telegram-канал.

Что делает:
  1. Берёт актуальный курс юаня с канала @elvnpay.
  2. Выбирает очередные товары со статусом "pending" из data/products.json.
  3. Считает цену и собирает текст поста.
  4. Отправляет видео с подписью в канал.
  5. Записывает ссылку на пост обратно в products.json и data/published.json —
     эти ссылки потом становятся ссылками пинов в Pinterest.

Токен бота берётся из переменной окружения TELEGRAM_BOT_TOKEN
(в GitHub он лежит в защищённом хранилище Secrets).
"""

import json
import os
import pathlib
import sys
import time
import datetime as dt

import requests

from rate import effective_rate
from pricing import calculate, format_price

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text("utf-8"))
PRODUCTS_PATH = ROOT / "data" / "products.json"
PUBLISHED_PATH = ROOT / "data" / "published.json"

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}"


def load(path: pathlib.Path, default):
    if not path.exists():
        return default
    text = path.read_text("utf-8").strip()
    return json.loads(text) if text else default


def save(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )


def build_caption(product: dict, price: int) -> str:
    lines = [f"<b>{product['title_ru']}</b>", ""]

    if product.get("description_ru"):
        lines += [product["description_ru"], ""]

    details = []
    if product.get("sizes"):
        details.append(f"Размеры: {product['sizes']}")
    if product.get("colors"):
        details.append(f"Цвета: {product['colors']}")
    if details:
        lines += details + [""]

    lines += [
        f"💰 <b>{format_price(price)} ₽</b>",
        "📦 Доставка СДЭК — оплата при получении",
        f"✍️ Заказать: {CONFIG['order_contact']}",
    ]
    return "\n".join(lines)


def send_video(video_path: pathlib.Path, caption: str) -> dict:
    with video_path.open("rb") as handle:
        response = requests.post(
            f"{API}/sendVideo",
            data={
                "chat_id": CONFIG["channel"],
                "caption": caption,
                "parse_mode": "HTML",
                "supports_streaming": True,
            },
            files={"video": handle},
            timeout=300,
        )
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram отказал: {payload}")
    return payload["result"]


def post_link(message_id: int) -> str:
    return f"https://t.me/{CONFIG['channel'].lstrip('@')}/{message_id}"


def main() -> int:
    if not TOKEN:
        print("ОШИБКА: не задан TELEGRAM_BOT_TOKEN", file=sys.stderr)
        return 1

    products = load(PRODUCTS_PATH, [])
    published = load(PUBLISHED_PATH, [])

    queue = [p for p in products if p.get("status", "pending") == "pending"]
    if not queue:
        print("Очередь пуста — публиковать нечего.")
        return 0

    rate, source = effective_rate(CONFIG)
    print(f"Курс в расчёте: {rate} ₽/¥ (источник: {source})")

    limit = int(CONFIG["posts_per_day"])
    today = dt.date.today().isoformat()
    errors = 0

    for product in queue[:limit]:
        video_path = ROOT / product["video"]
        if not video_path.exists():
            print(f"  ПРОПУСК {product['id']}: нет файла {product['video']}")
            errors += 1
            continue

        breakdown = calculate(CONFIG, product, rate)
        caption = build_caption(product, breakdown["price_rub"])

        try:
            result = send_video(video_path, caption)
        except Exception as exc:
            print(f"  ОШИБКА {product['id']}: {exc}")
            errors += 1
            continue

        message_id = result["message_id"]
        link = post_link(message_id)

        product["status"] = "published"
        product["published_at"] = today
        product["telegram_url"] = link
        product["price_rub"] = breakdown["price_rub"]

        published.append(
            {
                "id": product["id"],
                "title_ru": product["title_ru"],
                "title_en": product.get("title_en", product["title_ru"]),
                "category": product.get("category", "default"),
                "price_rub": breakdown["price_rub"],
                "telegram_url": link,
                "video": product["video"],
                "thumb": product.get("thumb", ""),
                "pinterest_description": product.get("pinterest_description", ""),
                "keywords": product.get("keywords", ""),
                "board": product.get("board", CONFIG["pinterest"]["default_board"]),
                "published_at": today,
                "breakdown": breakdown,
            }
        )

        print(
            f"  ✓ {product['id']}: {format_price(breakdown['price_rub'])} ₽ "
            f"(себестоимость {breakdown['cost_rub']:.0f}, "
            f"прибыль {breakdown['profit_rub']:.0f}) → {link}"
        )
        time.sleep(3)  # не упираемся в лимиты Telegram

    save(PRODUCTS_PATH, products)
    save(PUBLISHED_PATH, published)

    remaining = len([p for p in products if p.get("status", "pending") == "pending"])
    print(f"Готово. Осталось в очереди: {remaining}")
    return 0 if errors == 0 else 0  # ошибки отдельных товаров не валят весь запуск


if __name__ == "__main__":
    raise SystemExit(main())
