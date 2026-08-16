"""Следит за остатками на Ozon и предупреждает, когда ходовой товар кончается.

Почему это нужно:
  16 августа обнаружили, что товар palantinblack4 закончился на складе,
  но заказы всё равно приходили (спрос был) — они срывались и Ozon списывал
  логистику/обработку возврата без единой продажи (реальный убыток).
  Этот скрипт каждые несколько часов сверяет остатки через Ozon Seller API
  и, если что-то БЫЛО в наличии, а теперь стало 0, сразу шлёт хозяйке
  сообщение в личку тому же Telegram-боту, что публикует товары.

Нужны переменные окружения:
  OZON_CLIENT_ID, OZON_API_KEY   — ключ Seller API (Настройки → API интеграции)
  TELEGRAM_BOT_TOKEN             — тот же бот, что публикует в канал

Куда слать алерт:
  data/notify_config.json → {"admin_chat_id": <id>}. Это заполняется само
  скриптом pull_telegram_inbox.py, как только хозяйка хоть раз напишет боту
  в личку. Пока такого сообщения не было — скрипт просто сохраняет отчёт
  в data/ozon_stock_alerts.json и ничего никуда не шлёт (чтобы не падать).
"""

import json
import os
import pathlib
import sys

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "data" / "ozon_stock_snapshot.json"
ALERTS_PATH = ROOT / "data" / "ozon_stock_alerts.json"
NOTIFY_CONFIG_PATH = ROOT / "data" / "notify_config.json"

OZON_CLIENT_ID = os.environ.get("OZON_CLIENT_ID", "").strip()
OZON_API_KEY = os.environ.get("OZON_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

OZON_API_BASE = "https://api-seller.ozon.ru"


def load(path: pathlib.Path, default):
    if not path.exists():
        return default
    text = path.read_text("utf-8").strip()
    return json.loads(text) if text else default


def save(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")


def fetch_stocks() -> dict:
    """Возвращает {offer_id: {"name": ..., "present": int}} по всем товарам."""
    headers = {
        "Client-Id": OZON_CLIENT_ID,
        "Api-Key": OZON_API_KEY,
        "Content-Type": "application/json",
    }
    items = {}
    last_id = ""
    while True:
        body = {
            "filter": {"visibility": "ALL"},
            "last_id": last_id,
            "limit": 1000,
        }
        resp = requests.post(
            f"{OZON_API_BASE}/v4/product/info/stocks",
            headers=headers, json=body, timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        result = payload.get("result", payload)
        rows = result.get("items", [])
        if not rows:
            break
        for row in rows:
            offer_id = row.get("offer_id") or str(row.get("product_id"))
            present = sum(s.get("present", 0) for s in row.get("stocks", []))
            name = row.get("name") or offer_id
            items[offer_id] = {"name": name, "present": present}
        last_id = result.get("last_id", "")
        if not last_id or not result.get("has_next", False):
            break
    return items


def send_telegram(chat_id, text: str) -> None:
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=30,
    )


def main() -> int:
    if not OZON_CLIENT_ID or not OZON_API_KEY:
        print("ОШИБКА: не заданы OZON_CLIENT_ID / OZON_API_KEY", file=sys.stderr)
        return 1

    try:
        current = fetch_stocks()
    except requests.RequestException as exc:
        print(f"ОШИБКА запроса к Ozon Seller API: {exc}", file=sys.stderr)
        return 1

    previous = load(SNAPSHOT_PATH, {})

    just_ran_out = []
    for offer_id, info in current.items():
        was_present = previous.get(offer_id, {}).get("present", 0)
        if was_present > 0 and info["present"] == 0:
            just_ran_out.append(info["name"])
            print(f"  ЗАКОНЧИЛСЯ: {info['name']} (было {was_present} шт)")

    save(SNAPSHOT_PATH, current)

    if just_ran_out:
        alert_text = (
            "⚠️ На Ozon только что закончился ходовой товар "
            "(был в наличии, сейчас 0):\n"
            + "\n".join(f"— {name}" for name in just_ran_out)
            + "\n\nПополни остаток, иначе новые заказы будут срываться "
              "и списываться в минус на логистике."
        )
        alerts = load(ALERTS_PATH, [])
        alerts.append({"items": just_ran_out})
        save(ALERTS_PATH, alerts)

        notify_config = load(NOTIFY_CONFIG_PATH, {})
        admin_chat_id = notify_config.get("admin_chat_id")
        if admin_chat_id and TELEGRAM_BOT_TOKEN:
            send_telegram(admin_chat_id, alert_text)
            print("Алерт отправлен в Telegram.")
        else:
            print(
                "Алерт есть, но отправить некуда: ещё не известен "
                "admin_chat_id (хозяйка ни разу не писала боту в личку) "
                "или не задан TELEGRAM_BOT_TOKEN. Сохранил в "
                "data/ozon_stock_alerts.json."
            )
    else:
        print("Всё в наличии, ничего не закончилось с прошлой проверки.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
