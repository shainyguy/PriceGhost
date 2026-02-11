import io
import logging
from datetime import datetime
from typing import List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter
import numpy as np

from database.models import PriceRecord

logger = logging.getLogger(__name__)

# Стиль графика
plt.rcParams.update({
    "figure.facecolor": "#1a1a2e",
    "axes.facecolor": "#16213e",
    "axes.edgecolor": "#e94560",
    "axes.labelcolor": "#eee",
    "text.color": "#eee",
    "xtick.color": "#aaa",
    "ytick.color": "#aaa",
    "grid.color": "#333",
    "grid.alpha": 0.3,
    "font.size": 11,
})


def _price_formatter(x, pos):
    """Форматирование цены на оси Y"""
    if x >= 1000:
        return f"{x/1000:.1f}K"
    return f"{x:.0f}"


async def generate_price_chart(
    records: List[PriceRecord],
    title: str = "История цен",
    current_price: float = None,
    min_price: float = None,
    max_price: float = None,
) -> io.BytesIO:
    """
    Генерирует красивый график истории цен.
    Возвращает BytesIO с PNG изображением.
    """
    if not records:
        return _generate_empty_chart()

    dates = [r.recorded_at for r in records]
    prices = [r.price for r in records]
    original_prices = [r.original_price for r in records if r.original_price]

    fig, ax = plt.subplots(figsize=(12, 6))

    # Основная линия цены
    ax.plot(
        dates, prices,
        color="#00d2ff",
        linewidth=2.5,
        label="Цена",
        zorder=5,
    )

    # Заливка под графиком
    ax.fill_between(
        dates, prices,
        alpha=0.15,
        color="#00d2ff",
    )

    # «Оригинальная» цена (до скидки) если есть
    if original_prices and len(original_prices) == len(dates):
        ax.plot(
            dates, original_prices,
            color="#e94560",
            linewidth=1.5,
            linestyle="--",
            alpha=0.6,
            label="Цена до скидки",
        )

    # Маркеры мин/макс
    if min_price is not None:
        min_indices = [i for i, p in enumerate(prices) if p == min_price]
        if min_indices:
            idx = min_indices[0]
            ax.scatter(
                [dates[idx]], [prices[idx]],
                color="#00ff88", s=100, zorder=10, marker="v"
            )
            ax.annotate(
                f"Мин: {min_price:,.0f}₽",
                xy=(dates[idx], prices[idx]),
                xytext=(0, -25),
                textcoords="offset points",
                fontsize=10,
                color="#00ff88",
                ha="center",
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#1a1a2e", edgecolor="#00ff88", alpha=0.8),
            )

    if max_price is not None:
        max_indices = [i for i, p in enumerate(prices) if p == max_price]
        if max_indices:
            idx = max_indices[-1]
            ax.scatter(
                [dates[idx]], [prices[idx]],
                color="#e94560", s=100, zorder=10, marker="^"
            )
            ax.annotate(
                f"Макс: {max_price:,.0f}₽",
                xy=(dates[idx], prices[idx]),
                xytext=(0, 20),
                textcoords="offset points",
                fontsize=10,
                color="#e94560",
                ha="center",
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#1a1a2e", edgecolor="#e94560", alpha=0.8),
            )

    # Текущая цена — горизонтальная линия
    if current_price is not None:
        ax.axhline(
            y=current_price,
            color="#ffcc00",
            linewidth=1,
            linestyle=":",
            alpha=0.5,
            label=f"Сейчас: {current_price:,.0f}₽",
        )

    # Средняя цена
    avg = sum(prices) / len(prices)
    ax.axhline(
        y=avg,
        color="#888",
        linewidth=1,
        linestyle="-.",
        alpha=0.4,
        label=f"Средняя: {avg:,.0f}₽",
    )

    # Оформление
    ax.set_title(
        f"👻 {title}",
        fontsize=16,
        fontweight="bold",
        pad=15,
    )
    ax.set_xlabel("")
    ax.set_ylabel("Цена (₽)", fontsize=12)

    # Формат дат
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=45)

    # Формат цен
    ax.yaxis.set_major_formatter(FuncFormatter(_price_formatter))

    ax.legend(
        loc="upper right",
        fontsize=9,
        framealpha=0.7,
        facecolor="#1a1a2e",
        edgecolor="#444",
    )

    ax.grid(True, alpha=0.2)
    ax.set_xlim(min(dates), max(dates))

    # Добавляем padding по Y
    y_min = min(prices) * 0.9
    y_max = max(prices) * 1.1
    ax.set_ylim(y_min, y_max)

    # Watermark
    fig.text(
        0.99, 0.01, "PriceGhost 👻",
        fontsize=9, color="#555",
        ha="right", va="bottom",
        style="italic",
    )

    plt.tight_layout()

    # Сохраняем в BytesIO
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)

    return buf


def _generate_empty_chart() -> io.BytesIO:
    """Пустой график если нет данных"""
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.text(
        0.5, 0.5,
        "📊 Недостаточно данных\nОтслеживание начато!",
        transform=ax.transAxes,
        fontsize=18,
        ha="center",
        va="center",
        color="#aaa",
    )
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("👻 PriceGhost — История цен", fontsize=14, fontweight="bold")

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    buf.seek(0)
    plt.close(fig)
    return buf


async def generate_monthly_chart(
    monthly_data: dict,
    title: str = "Средние цены по месяцам"
) -> io.BytesIO:
    """Генерирует столбчатый график средних цен по месяцам (для прогноза)"""

    months_names = [
        "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
        "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"
    ]

    fig, ax = plt.subplots(figsize=(12, 6))

    months = sorted(monthly_data.keys())
    values = [monthly_data[m] for m in months]
    labels = [months_names[m - 1] for m in months]

    # Цвета: зеленый для дешёвых, красный для дорогих
    if values:
        min_val = min(values)
        max_val = max(values)
        range_val = max_val - min_val if max_val > min_val else 1
        colors = []
        for v in values:
            ratio = (v - min_val) / range_val
            r = int(ratio * 233 + (1 - ratio) * 0)
            g = int((1 - ratio) * 210 + ratio * 69)
            b = int((1 - ratio) * 136 + ratio * 96)
            colors.append(f"#{r:02x}{g:02x}{b:02x}")
    else:
        colors = ["#00d2ff"]

    bars = ax.bar(labels, values, color=colors, edgecolor="#333", linewidth=0.5)

    # Значения над столбцами
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + (max(values) * 0.02),
            f"{val:,.0f}₽",
            ha="center", va="bottom",
            fontsize=9, color="#ddd",
        )

    # Лучший месяц
    if values:
        best_idx = values.index(min(values))
        bars[best_idx].set_edgecolor("#00ff88")
        bars[best_idx].set_linewidth(3)

    ax.set_title(f"👻 {title}", fontsize=14, fontweight="bold", pad=15)
    ax.set_ylabel("Средняя цена (₽)")
    ax.yaxis.set_major_formatter(FuncFormatter(_price_formatter))
    ax.grid(axis="y", alpha=0.2)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf