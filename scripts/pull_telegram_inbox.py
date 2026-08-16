"""Забирает новые товары, которые хозяйка прислала боту в личные сообщения.

Почему это отдельный шаг:
  Писать текст в чат с Claude неудобно с телефона. Вместо этого она просто
  шлёт фото/видео товара с описанием (на китайском/русском, как есть,
  без строгого формата) в личку тому же Telegram-боту, который публикует
  в канал. Этот скрипт периодически проверяет личные сообщения бота,
  скачивает медиа и складывает "сырые" заявки в data/inbox.json.

  Сам разбор текста (цена, размеры, категория, перевод) в это скрипт
  НЕ входит — это на следующем шаге делает Claude в отдельной сессии
  (нужно понимание языка, а не регулярки), см. data/inbox.json.

Нужна переменная окружения TELEGRAM_BOT_TOKEN (тот же бот, что публикует).
"""

import json
import pathlib
import sys

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
INBOX_PATH = ROOT / "data" / "inbox.json"
OFFSET_PATH = ROOT / "data" / "telegram_offset.json"
MEDIA_DIR = ROOT / "media" / "inbox"
NOTIFY_CONFIG_PATH = ROOT / "data" / "notify_config.json"

import os

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{TOKEN}"


def load(path: pathlib.Path, default):
    if not path.exists():
        return default
    text = path.read_text("utf-8").strip()
    return json.loads(text) if text else default


def save(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")


def download_file(file_id: str, dest: pathlib.Path) -> None:
    info = requests.get(f"{API}/getFile", params={"file_id": file_id}, timeout=30).json()
    file_path = info["result"]["file_path"]
    resp = requests.get(f"{FILE_API}/{file_path}", timeout=300)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)


def main() -> int:
    if not TOKEN:
        print("ОШИБКА: не задан TELEGRAM_BOT_TOKEN", file=sys.stderr)
        return 1

    offset_data = load(OFFSET_PATH, {"offset": 0})
    inbox = load(INBOX_PATH, [])

    resp = requests.get(
        f"{API}/getUpdates",
        params={"offset": offset_data["offset"], "timeout": 0, "limit": 50},
        timeout=30,
    )
    payload = resp.json()
    if not payload.get("ok"):
        print(f"ОШИБКА Telegram: {payload}", file=sys.stderr)
        return 1

    updates = payload["result"]
    added = 0

    for update in updates:
        offset_data["offset"] = update["update_id"] + 1
        msg = update.get("message")
        if not msg:
            continue
        chat = msg.get("chat", {})
        # Берём только личные сообщения (не сам канал/группу публикации),
        # чтобы случайно не подхватить собственные посты бота.
        if chat.get("type") != "private":
            continue

        # Запоминаем chat_id хозяйки — сюда потом шлём алерты об остатках
        # (см. ozon_stock_alert.py). Она единственная, кто пишет боту в личку.
        notify_config = load(NOTIFY_CONFIG_PATH, {})
        if notify_config.get("admin_chat_id") != chat.get("id"):
            notify_config["admin_chat_id"] = chat.get("id")
            save(NOTIFY_CONFIG_PATH, notify_config)

        caption = msg.get("caption", "") or msg.get("text", "")
        media_file_id = None
        media_kind = None
        media_ext = "bin"

        if msg.get("video"):
            media_file_id = msg["video"]["file_id"]
            media_kind = "video"
            media_ext = "mp4"
        elif msg.get("photo"):
            media_file_id = msg["photo"][-1]["file_id"]  # самое крупное фото
            media_kind = "photo"
            media_ext = "jpg"
        elif msg.get("document"):
            media_file_id = msg["document"]["file_id"]
            media_kind = "document"
            name = msg["document"].get("file_name", "")
            media_ext = name.rsplit(".", 1)[-1] if "." in name else "bin"

        if not media_file_id and not caption:
            continue  # пустое служебное сообщение

        entry_id = f"inbox-{msg['message_id']}"
        media_rel = None
        if media_file_id:
            dest = MEDIA_DIR / f"{entry_id}.{media_ext}"
            try:
                download_file(media_file_id, dest)
                media_rel = str(dest.relative_to(ROOT))
            except Exception as exc:
                print(f"  ОШИБКА скачивания {entry_id}: {exc}", file=sys.stderr)

        inbox.append(
            {
                "id": entry_id,
                "caption": caption,
                "media": media_rel,
                "media_kind": media_kind,
                "received_at": msg.get("date"),
                "processed": False,
            }
        )
        added += 1
        print(f"  + {entry_id}: {media_kind or 'текст'} — {caption[:60]!r}")

    save(OFFSET_PATH, offset_data)
    save(INBOX_PATH, inbox)

    print(f"Готово. Новых заявок: {added}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
