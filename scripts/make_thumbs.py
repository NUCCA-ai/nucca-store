"""Обложки для видео.

Pinterest требует отдельную картинку-превью для видео-пина.
Берём кадр с первой секунды каждого видео и приводим к вертикали 1000x1500
(соотношение 2:3 — рекомендованный формат Pinterest).

Уже существующие обложки не перегенерируем.
"""

import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRODUCTS_PATH = ROOT / "data" / "products.json"
THUMBS_DIR = ROOT / "thumbs"

VF = (
    "scale=1000:1500:force_original_aspect_ratio=increase,"
    "crop=1000:1500"
)


def main() -> int:
    if not PRODUCTS_PATH.exists():
        print("Нет data/products.json — пропускаю.")
        return 0

    products = json.loads(PRODUCTS_PATH.read_text("utf-8") or "[]")
    THUMBS_DIR.mkdir(exist_ok=True)
    made = 0

    for product in products:
        video = ROOT / product.get("video", "")
        if not video.exists():
            continue

        thumb_rel = f"thumbs/{product['id']}.jpg"
        thumb_path = ROOT / thumb_rel

        if not thumb_path.exists():
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-ss", "1", "-i", str(video),
                    "-frames:v", "1", "-vf", VF, "-q:v", "3",
                    str(thumb_path),
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"  не смогла сделать обложку для {product['id']}: {result.stderr.strip()}")
                continue
            made += 1

        product["thumb"] = thumb_rel

    PRODUCTS_PATH.write_text(
        json.dumps(products, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    print(f"Обложек создано: {made}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
