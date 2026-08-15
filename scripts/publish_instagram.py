"""Публикация Reels в Instagram через официальный Graph API (Meta).

Что делает:
  1. Берёт товары со статусом status == "published" (уже посчитана цена
     и опубликованы в Telegram) и instagram_status == "pending".
  2. Строит подпись с ценой и хэштегами.
  3. Создаёт медиа-контейнер в Instagram (video_url должен быть публичным —
     берём с GitHub Pages), ждёт обработки, публикует.
  4. Записывает ссылку на Reels обратно в products.json.

Нужны переменные окружения:
  IG_ACCESS_TOKEN   — долгоживущий токен доступа (Page/User token с правами
                       instagram_basic, instagram_content_publish,
                       pages_show_list, pages_read_engagement)
  IG_BUSINESS_ID    — ID бизнес-аккаунта Instagram (Instagram Business
                       Account ID, НЕ имя пользователя)

Видео должно быть доступно по прямой ссылке — используем GitHub Pages
(config.json → pinterest.pages_base_url), поэтому видео сначала должно
быть закоммичено в репозиторий и GitHub Pages должен быть включён.
"""

import json
import os
import pathlib
import sys
import time

import requests

from pricing import format_price

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text("utf-8"))
PRODUCTS_PATH = ROOT / "data" / "products.json"

TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
IG_USER_ID = os.environ.get("IG_BUSINESS_ID", "").strip()
GRAPH = "https://graph.facebook.com/v21.0"

PAGES_BASE = CONFIG["pinterest"]["pages_base_url"].rstrip("/")

# Сколько раз проверять готовность контейнера и с какой паузой (сек)
POLL_ATTEMPTS = 20
POLL_DELAY = 15


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


def build_caption(product: dict) -> str:
    # Товары, опубликованные вручную без названия/цены (caption_used),
    # используем ту же подпись, что была в Telegram, — чтобы не постить
    # пустой текст, пока хозяйка не дозаполнит карточку.
    if not product.get("title_ru") and product.get("caption_used"):
        return product["caption_used"]

    lines = [product["title_ru"], ""]

    if product.get("description_ru"):
        lines += [product["description_ru"], ""]

    price = product.get("price_rub")
    if price:
        lines.append(f"💰 {format_price(price)} ₽")

    if product.get("sizes"):
        lines.append(f"Размеры: {product['sizes']}")
    if product.get("colors"):
        lines.append(f"Цвета: {product['colors']}")

    lines += ["", f"Заказать: {CONFIG['order_contact']}"]

    keywords = product.get("keywords", "")
    if keywords:
        tags = [
            "#" + w.strip().replace(" ", "").replace("-", "")
            for w in keywords.split(",")
            if w.strip()
        ]
        if tags:
            lines += ["", " ".join(tags)]

    return "\n".join(lines)


def video_url(product: dict) -> str:
    return f"{PAGES_BASE}/{product['video']}"


def create_container(video_link: str, caption: str) -> str:
    response = requests.post(
        f"{GRAPH}/{IG_USER_ID}/media",
        data={
            "media_type": "REELS",
            "video_url": video_link,
            "caption": caption,
            "access_token": TOKEN,
        },
        timeout=60,
    )
    payload = response.json()
    if "id" not in payload:
        raise RuntimeError(f"не удалось создать контейнер: {payload}")
    return payload["id"]


def wait_until_ready(creation_id: str) -> None:
    for _ in range(POLL_ATTEMPTS):
        response = requests.get(
            f"{GRAPH}/{creation_id}",
            params={"fields": "status_code", "access_token": TOKEN},
            timeout=30,
        )
        payload = response.json()
        status = payload.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Instagram не смог обработать видео: {payload}")
        time.sleep(POLL_DELAY)
    raise RuntimeError("не дождались обработки видео (таймаут)")


def publish_container(creation_id: str) -> str:
    response = requests.post(
        f"{GRAPH}/{IG_USER_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": TOKEN},
        timeout=60,
    )
    payload = response.json()
    if "id" not in payload:
        raise RuntimeError(f"публикация не удалась: {payload}")
    return payload["id"]


def permalink(media_id: str) -> str:
    response = requests.get(
        f"{GRAPH}/{media_id}",
        params={"fields": "permalink", "access_token": TOKEN},
        timeout=30,
    )
    payload = response.json()
    return payload.get("permalink", "")


def main() -> int:
    if not TOKEN or not IG_USER_ID:
        print("ОШИБКА: не заданы IG_ACCESS_TOKEN / IG_BUSINESS_ID", file=sys.stderr)
        return 1

    products = load(PRODUCTS_PATH, [])

    queue = [
        p
        for p in products
        if p.get("status") == "published"
        and p.get("instagram_status", "pending") == "pending"
    ]
    if not queue:
        print("Нечего публиковать в Instagram — очередь пуста.")
        return 0

    limit = int(CONFIG.get("instagram", {}).get("posts_per_day", 3))
    errors = 0

    for product in queue[:limit]:
        caption = build_caption(product)
        link = video_url(product)
        print(f"  {product['id']}: {link}")

        try:
            creation_id = create_container(link, caption)
            wait_until_ready(creation_id)
            media_id = publish_container(creation_id)
            reel_url = permalink(media_id) or f"https://instagram.com/reel/{media_id}"
        except Exception as exc:
            print(f"  ОШИБКА {product['id']}: {exc}")
            errors += 1
            continue

        product["instagram_status"] = "published"
        product["instagram_url"] = reel_url
        print(f"  ✓ {product['id']} → {reel_url}")
        time.sleep(5)

    save(PRODUCTS_PATH, products)

    remaining = len(
        [
            p
            for p in products
            if p.get("status") == "published"
            and p.get("instagram_status", "pending") == "pending"
        ]
    )
    print(f"Готово. Осталось в очереди на Instagram: {remaining}")
    return 0 if errors == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
