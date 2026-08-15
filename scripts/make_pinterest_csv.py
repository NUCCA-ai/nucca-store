"""Сборка CSV для массовой загрузки пинов в Pinterest.

Берёт опубликованные товары (у каждого уже есть ссылка на пост в Telegram)
и раскладывает их по датам: один товар — один пин в день.

Колонки соответствуют шаблону Pinterest для Bulk create:
    Title | Media URL | Pinterest board | Thumbnail | Description | Link |
    Publish date | Keywords

Дата публикации — в формате YYYY-MM-DD hh:mm:ss по UTC.
"""

import argparse
import csv
import json
import pathlib
import datetime as dt

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text("utf-8"))
PUBLISHED_PATH = ROOT / "data" / "published.json"

HEADERS = [
    "Title",
    "Media URL",
    "Pinterest board",
    "Thumbnail",
    "Description",
    "Link",
    "Publish date",
    "Keywords",
]

TITLE_LIMIT = 90
DESC_LIMIT = 490


def trim(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def media_url(item: dict, key: str) -> str:
    path = item.get(key, "")
    if not path:
        return ""
    if path.startswith("http"):
        return path
    base = CONFIG["pinterest"]["pages_base_url"].rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="дата первого пина, YYYY-MM-DD")
    parser.add_argument("--time", default="14:00:00", help="время публикации, UTC")
    parser.add_argument("--per-day", type=int, default=1)
    parser.add_argument("--out", default="pinterest_pins.csv")
    parser.add_argument(
        "--all",
        action="store_true",
        help="включить и те товары, для которых пин уже создавался",
    )
    args = parser.parse_args()

    published = json.loads(PUBLISHED_PATH.read_text("utf-8")) if PUBLISHED_PATH.exists() else []
    items = [i for i in published if args.all or not i.get("pin_scheduled")]

    if not items:
        print("Нет товаров для выгрузки в Pinterest.")
        return 0

    start = (
        dt.date.fromisoformat(args.start)
        if args.start
        else dt.date.today() + dt.timedelta(days=1)
    )

    rows = []
    for index, item in enumerate(items):
        day = start + dt.timedelta(days=index // max(args.per_day, 1))
        rows.append(
            {
                "Title": trim(item.get("title_en") or item["title_ru"], TITLE_LIMIT),
                "Media URL": media_url(item, "video"),
                "Pinterest board": item.get("board", CONFIG["pinterest"]["default_board"]),
                "Thumbnail": media_url(item, "thumb"),
                "Description": trim(
                    item.get("pinterest_description") or item["title_ru"], DESC_LIMIT
                ),
                "Link": item["telegram_url"],
                "Publish date": f"{day.isoformat()} {args.time}",
                "Keywords": item.get("keywords", ""),
            }
        )
        item["pin_scheduled"] = True

    out_path = ROOT / args.out
    with out_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    PUBLISHED_PATH.write_text(
        json.dumps(published, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )

    last = rows[-1]["Publish date"].split()[0]
    print(f"Готово: {len(rows)} пинов в {out_path.name}")
    print(f"График: с {start.isoformat()} по {last}, {args.per_day} шт. в день")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
