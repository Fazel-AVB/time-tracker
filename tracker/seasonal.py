"""
Seasonal banner utility.
Returns an HTML banner reflecting the meteorological season of a given week.
Seasons: Spring (Mar–May), Summer (Jun–Aug), Autumn (Sep–Nov), Winter (Dec–Feb).
"""
from __future__ import annotations

from datetime import date, timedelta

_THEMES: dict[str, dict] = {
    "spring": {
        "name": "Spring",
        "emoji": "🌸",
        "decorations": "🌷  🌿  🦋",
        "gradient": "linear-gradient(135deg, #d4f5e9 0%, #fce4ec 100%)",
        "text_color": "#4a1942",
        "border": "#f9a8d4",
        "tag_bg": "rgba(249,168,212,0.35)",
        "tag_color": "#831843",
    },
    "summer": {
        "name": "Summer",
        "emoji": "☀️",
        "decorations": "🌊  🌻  🍉",
        "gradient": "linear-gradient(135deg, #fff9c4 0%, #ffe0b2 100%)",
        "text_color": "#7c2d12",
        "border": "#fb923c",
        "tag_bg": "rgba(251,146,60,0.25)",
        "tag_color": "#9a3412",
    },
    "autumn": {
        "name": "Autumn",
        "emoji": "🍂",
        "decorations": "🍁  🌾  🎃",
        "gradient": "linear-gradient(135deg, #fef3c7 0%, #fde8d0 60%, #fcd5b0 100%)",
        "text_color": "#431407",
        "border": "#ea580c",
        "tag_bg": "rgba(234,88,12,0.20)",
        "tag_color": "#7c2d12",
    },
    "winter": {
        "name": "Winter",
        "emoji": "❄️",
        "decorations": "⛄  🌨️  🛷",
        "gradient": "linear-gradient(135deg, #e0f2fe 0%, #dbeafe 60%, #ede9fe 100%)",
        "text_color": "#0c1445",
        "border": "#60a5fa",
        "tag_bg": "rgba(96,165,250,0.25)",
        "tag_color": "#1e3a8a",
    },
}


def get_season(d: date) -> str:
    """Return the meteorological season key for a date."""
    m = d.month
    if m in (3, 4, 5):
        return "spring"
    if m in (6, 7, 8):
        return "summer"
    if m in (9, 10, 11):
        return "autumn"
    return "winter"


def seasonal_banner(week_start: date) -> str:
    """
    Return an HTML string for a full-width seasonal banner.
    week_start: the Monday of the week being viewed.
    """
    key = get_season(week_start)
    t = _THEMES[key]
    week_end = week_start + timedelta(days=6)
    week_label = (
        f"{week_start.strftime('%B %d')} – {week_end.strftime('%B %d, %Y')}"
    )

    return f"""
<div style="
    background: {t['gradient']};
    border: 1px solid {t['border']};
    border-radius: 14px;
    padding: 16px 26px;
    margin-bottom: 1.2rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
">
    <div style="display:flex; align-items:center; gap:14px;">
        <span style="font-size:2.4rem; line-height:1;">{t['emoji']}</span>
        <div>
            <span style="
                display: inline-block;
                background: {t['tag_bg']};
                color: {t['tag_color']};
                font-size: 0.75rem;
                font-weight: 700;
                letter-spacing: 0.1em;
                text-transform: uppercase;
                padding: 2px 10px;
                border-radius: 99px;
                margin-bottom: 4px;
            ">{t['name']}</span><br>
            <span style="
                font-size: 1.1rem;
                font-weight: 600;
                color: {t['text_color']};
            ">Week of {week_label}</span>
        </div>
    </div>
    <span style="font-size:1.7rem; letter-spacing:6px; opacity:0.85;">{t['decorations']}</span>
</div>
"""
