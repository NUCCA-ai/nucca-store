"""Подмешивает нашид/халяльный бит в видео перед публикацией в Instagram.

Почему это отдельный шаг:
  Исходное видео товара (из приложения поставщика) часто уже содержит
  чужую фоновую музыку — это нельзя оставлять в Reels. Скрипт полностью
  убирает оригинальную аудиодорожку и накладывает вместо неё случайный
  трек из папки audio/ (только no-copyright нашиды/биты без мелодических
  инструментов), обрезанный по длине видео с плавным затуханием в конце.

  Видео для Telegram (media/<id>.mp4) не трогаем — там всё как есть.
  Результат сохраняется рядом как media/<id>-ig.mp4 и именно этот файл
  публикуется в Instagram (см. scripts/publish_instagram.py).

Ничего не делает, если:
  - папки audio/ нет или она пуста;
  - "audio_enabled" в config.json выставлен в false;
  - файл <id>-ig.mp4 уже существует (чтобы не пересчитывать каждый день).
"""

import json
import pathlib
import random
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text("utf-8"))
PRODUCTS_PATH = ROOT / "data" / "products.json"
AUDIO_DIR = ROOT / "audio"
FADE_SECONDS = 0.6


def load(path: pathlib.Path, default):
    if not path.exists():
        return default
    text = path.read_text("utf-8").strip()
    return json.loads(text) if text else default


def save(path: pathlib.Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")


def ffprobe_duration(path: pathlib.Path) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def mix(video_path: pathlib.Path, audio_path: pathlib.Path, out_path: pathlib.Path) -> None:
    duration = ffprobe_duration(video_path)
    fade_start = max(duration - FADE_SECONDS, 0)
    filt = f"[1:a]atrim=0:{duration:.3f},afade=t=out:st={fade_start:.3f}:d={FADE_SECONDS}[a]"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-filter_complex", filt,
            "-map", "0:v:0", "-map", "[a]",
            # Видео перекодируем (не copy): у части исходников от поставщика
            # переменный fps (VFR) — Instagram Graph API часто не может
            # обработать такое видео и отдаёт status_code=ERROR без деталей.
            # Принудительно приводим к постоянному fps.
            "-c:v", "libx264", "-r", "30", "-fps_mode", "cfr",
            "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-shortest",
            "-movflags", "+faststart",
            str(out_path),
        ],
        check=True, capture_output=True, text=True,
    )


def main() -> int:
    ig_config = CONFIG.get("instagram", {})
    if not ig_config.get("audio_enabled", True):
        print("Подмешивание аудио выключено в config.json (instagram.audio_enabled=false).")
        return 0

    tracks = sorted(AUDIO_DIR.glob("*.mp3"))
    if not tracks:
        print("Папка audio/ пуста — нечего подмешивать, пропускаю.")
        return 0

    products = load(PRODUCTS_PATH, [])
    queue = [
        p for p in products
        if p.get("status") == "published"
        and p.get("instagram_status", "pending") == "pending"
    ]
    if not queue:
        print("Нет товаров в очереди на Instagram — подмешивать нечего.")
        return 0

    for product in queue:
        if product.get("keep_audio"):
            # Хозяйка явно попросила не трогать звук в этом видео
            # (например, в нём и так нет посторонней музыки).
            print(f"  {product['id']}: keep_audio=true, пропускаю подмешивание")
            continue

        video_path = ROOT / product["video"]
        if not video_path.exists():
            print(f"  {product['id']}: видео не найдено ({video_path}), пропускаю")
            continue

        out_path = video_path.with_name(video_path.stem + "-ig.mp4")
        if out_path.exists():
            continue

        track = random.choice(tracks)
        try:
            mix(video_path, track, out_path)
            print(f"  {product['id']}: {out_path.name} ← {track.name}")
        except subprocess.CalledProcessError as exc:
            print(f"  ОШИБКА {product['id']}: {exc.stderr[-500:] if exc.stderr else exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
