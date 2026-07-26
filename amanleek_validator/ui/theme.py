from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st


LOGO_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "amanleek-logo-white.png"
)

BRAND_CSS = """
<style>
    :root {
        --brand-navy: #172356;
        --brand-blue: #4558D9;
        --brand-teal: #4558D9;
        --brand-orange: #FF4B0B;
        --brand-mint: #EEF0FF;
        --brand-ink: #243B53;
        --brand-muted: #627D98;
        --brand-border: #DDE2F2;
    }
    .stApp {
        background: radial-gradient(circle at 95% 0%, rgba(255,75,11,.07), transparent 25rem), #F8F9FC;
        color: var(--brand-ink);
    }
    [data-testid="stHeader"] {
        background: rgba(247,250,252,.88);
        backdrop-filter: blur(12px);
    }
    [data-testid="stMainBlockContainer"] {
        max-width: 1180px;
        padding-top: 2rem;
        padding-bottom: 4rem;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #172356 0%, #263779 100%);
        border-right: 0;
    }
    [data-testid="stSidebar"] * { color: #F0F8FA; }
    [data-testid="stSidebar"] [role="radiogroup"] label {
        border: 1px solid rgba(255,255,255,.12);
        border-radius: .75rem;
        margin-bottom: .45rem;
        padding: .55rem .75rem;
        transition: background 150ms ease, border-color 150ms ease;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover {
        background: rgba(255,255,255,.08);
        border-color: rgba(255,255,255,.28);
    }
    [data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.14); }
    .brand-lockup {
        display: flex;
        align-items: center;
        gap: .75rem;
        margin: .25rem 0 1.5rem;
    }
    .brand-mark {
        align-items: center;
        background: linear-gradient(135deg, #34D5C5, #0EA5B7);
        border-radius: .85rem;
        box-shadow: 0 8px 20px rgba(0,0,0,.18);
        color: #082F49 !important;
        display: flex;
        font-size: 1.15rem;
        font-weight: 800;
        height: 2.65rem;
        justify-content: center;
        width: 2.65rem;
    }
    .brand-name {
        color: #FFF !important;
        font-size: 1.05rem;
        font-weight: 750;
        line-height: 1.2;
    }
    .brand-product {
        color: #B9D9E5 !important;
        font-size: .73rem;
        letter-spacing: .04em;
        margin-top: .15rem;
        text-transform: uppercase;
    }
    .sidebar-label {
        color: #9EC5D3 !important;
        font-size: .72rem;
        font-weight: 700;
        letter-spacing: .1em;
        margin: 0 0 .55rem;
        text-transform: uppercase;
    }
    .brand-suite {
        border-top: 1px solid rgba(255,255,255,.12);
        color: #C7D2FE !important;
        font-size: .72rem;
        font-weight: 700;
        letter-spacing: .1em;
        margin: .85rem 0 1.5rem;
        padding-top: .75rem;
        text-transform: uppercase;
    }
    .sidebar-security {
        background: rgba(0,166,166,.14);
        border: 1px solid rgba(77,226,210,.24);
        border-radius: .8rem;
        color: #DDFBF7 !important;
        font-size: .78rem;
        line-height: 1.5;
        padding: .85rem;
    }
    .page-kicker {
        background: #FFF0E8;
        border: 1px solid #FFD4C2;
        border-radius: 999px;
        color: #B83200;
        display: inline-flex;
        font-size: .76rem;
        font-weight: 800;
        letter-spacing: .12em;
        margin-bottom: .75rem;
        padding: .35rem .65rem;
        text-transform: uppercase;
    }
    .page-title {
        color: var(--brand-navy);
        font-size: clamp(1.8rem, 4vw, 2.55rem);
        font-weight: 780;
        letter-spacing: -.035em;
        line-height: 1.08;
        margin: 0;
    }
    .page-description {
        color: var(--brand-muted);
        font-size: 1.02rem;
        line-height: 1.65;
        margin: .65rem 0 1.55rem;
        max-width: 760px;
    }
    .section-title {
        color: var(--brand-navy);
        font-size: 1.2rem;
        font-weight: 750;
        margin: 1.65rem 0 .15rem;
    }
    .section-copy {
        color: var(--brand-muted);
        font-size: .92rem;
        margin-bottom: 1rem;
    }
    .step-card {
        background: #FFF;
        border: 1px solid var(--brand-border);
        border-radius: 1rem;
        box-shadow: 0 8px 28px rgba(16,42,67,.05);
        min-height: 155px;
        padding: 1.1rem;
    }
    .step-card-number {
        align-items: center;
        background: var(--brand-mint);
        border-radius: .65rem;
        color: #087C7C;
        display: flex;
        font-size: .78rem;
        font-weight: 800;
        height: 2rem;
        justify-content: center;
        margin-bottom: .85rem;
        width: 2rem;
    }
    .step-card-title {
        color: var(--brand-navy);
        font-size: .96rem;
        font-weight: 750;
        margin-bottom: .35rem;
    }
    .step-card-copy {
        color: var(--brand-muted);
        font-size: .83rem;
        line-height: 1.5;
    }
    .privacy-note {
        align-items: flex-start;
        background: linear-gradient(135deg, #E7F8F5, #EFF8FB);
        border: 1px solid #BDE8E2;
        border-radius: .9rem;
        display: flex;
        gap: .8rem;
        margin: 1.25rem 0;
        padding: 1rem 1.1rem;
    }
    .privacy-icon { font-size: 1.25rem; line-height: 1.2; }
    .privacy-title {
        color: #0A5E67;
        font-size: .88rem;
        font-weight: 800;
        margin-bottom: .15rem;
    }
    .privacy-copy {
        color: #3B6F75;
        font-size: .8rem;
        line-height: 1.5;
    }
    [data-testid="stFileUploader"] {
        background: #FFF;
        border: 1px solid var(--brand-border);
        border-radius: 1rem;
        box-shadow: 0 8px 28px rgba(16,42,67,.05);
        padding: .5rem .8rem .8rem;
    }
    [data-testid="stFileUploaderDropzone"] {
        background: #F6F7FF;
        border-color: #AAB4EF;
        border-radius: .8rem;
    }
    [data-testid="stMetric"] {
        background: #FFF;
        border: 1px solid var(--brand-border);
        border-radius: .9rem;
        box-shadow: 0 6px 20px rgba(16,42,67,.04);
        padding: .9rem 1rem;
    }
    [data-testid="stMetricValue"] { color: var(--brand-navy); }
    .stButton > button, .stDownloadButton > button {
        border-radius: .7rem;
        font-weight: 700;
        min-height: 2.65rem;
    }
    div[data-testid="stExpander"] {
        background: #FFF;
        border-color: var(--brand-border);
        border-radius: .85rem;
    }
    [data-testid="stDataFrame"] {
        border: 1px solid var(--brand-border);
        border-radius: .85rem;
        overflow: hidden;
    }
    @media (max-width: 640px) {
        [data-testid="stMainBlockContainer"] {
            padding-left: 1rem;
            padding-right: 1rem;
            padding-top: 1.25rem;
        }
        .step-card { min-height: 0; }
    }
</style>
"""


def apply_theme() -> None:
    st.markdown(BRAND_CSS, unsafe_allow_html=True)


def render_sidebar_brand() -> None:
    st.image(str(LOGO_PATH), width="stretch")
    st.markdown(
        '<div class="brand-suite">Utilization File Validator</div>',
        unsafe_allow_html=True,
    )


def render_page_header(kicker: str, title: str, description: str) -> None:
    st.markdown(
        f'<div class="page-kicker">{escape(kicker)}</div>'
        f'<h1 class="page-title">{escape(title)}</h1>'
        f'<p class="page-description">{escape(description)}</p>',
        unsafe_allow_html=True,
    )


def render_section_heading(title: str, description: str = "") -> None:
    copy = (
        f'<div class="section-copy">{escape(description)}</div>'
        if description
        else ""
    )
    st.markdown(
        f'<div class="section-title">{escape(title)}</div>{copy}',
        unsafe_allow_html=True,
    )


def render_step_card(number: str, title: str, description: str) -> None:
    st.markdown(
        '<div class="step-card">'
        f'<div class="step-card-number">{escape(number)}</div>'
        f'<div class="step-card-title">{escape(title)}</div>'
        f'<div class="step-card-copy">{escape(description)}</div></div>',
        unsafe_allow_html=True,
    )


def render_privacy_note() -> None:
    st.markdown(
        """
        <div class="privacy-note">
            <div class="privacy-icon">🔒</div>
            <div>
                <div class="privacy-title">Private by design</div>
                <div class="privacy-copy">
                    Uploaded and generated files are processed in memory. They are not
                    automatically saved by this application.
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
