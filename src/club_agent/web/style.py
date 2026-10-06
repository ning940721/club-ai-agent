"""網頁的視覺樣式：少量 CSS 補足主題設定（.streamlit/config.toml）做不到的細節。"""

from __future__ import annotations

import html

import streamlit as st

CSS = """
<style>
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem; max-width: 1120px; }
section[data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }

.app-brand { font-size: 0.8rem; letter-spacing: 0.08em; color: #6B7280; margin-bottom: 0.15rem; }
.app-club { font-size: 1.15rem; font-weight: 600; color: #1D2433; margin-bottom: 1.2rem; }

.page-eyebrow { font-size: 0.85rem; color: #6B7280; letter-spacing: 0.04em; margin-bottom: 0.2rem; }
.page-title { font-size: 1.75rem; font-weight: 600; color: #1D2433; margin: 0 0 1.4rem 0; line-height: 1.3; }
.beta-tag {
  display: inline-block; font-size: 0.72rem; font-weight: 500; color: #6B7280;
  border: 1px solid #D6D2C8; border-radius: 999px; padding: 0.05rem 0.55rem;
  margin-left: 0.6rem; vertical-align: middle; letter-spacing: 0.04em;
}
.section-note { font-size: 0.88rem; color: #6B7280; margin: -0.4rem 0 0.9rem 0; }

button[data-baseweb="tab"] p { font-size: 0.95rem; }

/* 行事曆 */
.cal-wrap { overflow-x: auto; margin: 0.4rem 0 1rem 0; }
table.cal { width: 100%; min-width: 560px; border-collapse: collapse; table-layout: fixed; }
table.cal th { font-size: 0.8rem; font-weight: 500; color: #6B7280; padding: 0.3rem; text-align: left; border-bottom: 1px solid #E2DED6; }
table.cal td.cal-day { vertical-align: top; height: 92px; padding: 0.25rem; border: 1px solid #E2DED6; background: #FFFFFF; overflow: hidden; }
table.cal td.cal-out { background: #F6F4EF; }
table.cal td.cal-out .cal-num { color: #B4B0A6; }
table.cal td.cal-today { box-shadow: inset 0 0 0 2px #2D4A6B; }
.cal-num { font-size: 0.78rem; color: #1D2433; margin-bottom: 0.15rem; }
.cal-chip {
  display: block; font-size: 0.72rem; line-height: 1.35; padding: 0.05rem 0.3rem; margin-bottom: 0.15rem;
  border-radius: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.cal-legend { margin-top: 0.4rem; }
.cal-legend .cal-chip { display: inline-block; margin-right: 0.4rem; }
.ev-event { background: #E3EBF4; color: #22405F; }
.ev-meeting { background: #2D4A6B; color: #FFFFFF; }
.ev-due { background: #F7E3DF; color: #8A3324; }
.ev-other { background: #ECEAE4; color: #4B5160; }
.cal-more { font-size: 0.7rem; color: #6B7280; }
div[data-testid="stExpander"] details { border-color: #E2DED6; }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def page_header(title: str, eyebrow: str = "", beta: bool = False) -> None:
    tag = '<span class="beta-tag">測試版</span>' if beta else ""
    eyebrow_html = f'<div class="page-eyebrow">{html.escape(eyebrow)}</div>' if eyebrow else ""
    st.markdown(f'{eyebrow_html}<div class="page-title">{html.escape(title)}{tag}</div>', unsafe_allow_html=True)


def sidebar_brand(club_name: str) -> None:
    st.markdown(
        f'<div class="app-brand">社團營運平台</div><div class="app-club">{html.escape(club_name)}</div>',
        unsafe_allow_html=True,
    )


def note(text: str) -> None:
    st.markdown(f'<div class="section-note">{html.escape(text)}</div>', unsafe_allow_html=True)
