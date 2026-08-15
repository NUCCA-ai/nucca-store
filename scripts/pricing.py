"""Расчёт розничной цены товара.

Формула:
    цена = (цена_в_юанях × курс_с_буфером)
         + (вес_категории × стоимость_доставки_за_кг)
         + наценка
    затем округление вниз до красивого числа.
"""

import math


def weight_for(cfg: dict, product: dict) -> float:
    """Вес товара: явный из карточки, иначе по категории, иначе дефолт."""
    if product.get("weight_kg"):
        return float(product["weight_kg"])
    weights = cfg["weights"]
    return float(weights.get(product.get("category", "default"), weights["default"]))


def calculate(cfg: dict, product: dict, rate: float) -> dict:
    price_cny = float(product["price_cny"])
    weight = weight_for(cfg, product)

    goods_rub = price_cny * rate
    delivery_rub = weight * float(cfg["delivery_per_kg"])
    cost = goods_rub + delivery_rub

    markup = cost * float(cfg["markup_percent"]) / 100.0
    raw_price = cost + markup

    step = int(cfg["round_down_to"])
    final_price = int(math.floor(raw_price / step) * step)
    # Никогда не опускаемся ниже себестоимости из-за округления.
    if final_price < cost:
        final_price = int(math.ceil(cost / step) * step)

    return {
        "rate": round(rate, 2),
        "weight_kg": round(weight, 2),
        "goods_rub": round(goods_rub, 2),
        "delivery_rub": round(delivery_rub, 2),
        "cost_rub": round(cost, 2),
        "markup_rub": round(markup, 2),
        "price_rub": final_price,
        "profit_rub": round(final_price - cost, 2),
    }


def format_price(value: int) -> str:
    """3900 -> '3 900'"""
    return f"{value:,}".replace(",", " ")
