from __future__ import annotations

import html
import json
import re
import tempfile
from copy import deepcopy
from datetime import date, datetime, timedelta, time
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from calculator.engine import calcular_dimensionamento_minimo, simular_ciclo_bt
from calculator.gantt import (
    gerar_disponibilidade_bt,
    gerar_disponibilidade_bt_interativa,
    gerar_gantt,
    gerar_gantt_interativo,
    gerar_tabela_disponibilidade_bt,
)
from calculator.models import Concretagem
from calculator.utils import format_clock, parse_time_value, round_minutes, safe_identifier
from exports.csv_export import (
    exportar_detalhamento_csv,
    exportar_programacao_cenario_csv,
    importar_programacao_cenario_csv,
)
from exports.pdf_export import exportar_relatorio_operacional_pdf


BASE_DIR = Path(__file__).resolve().parent
SAVED_SCENARIOS_PATH = BASE_DIR / "sample_data" / "saved_scenarios.json"
BROWSER_SCENARIOS_STORAGE_KEY = "programacoes_concretagem_saved_scenarios_v1"
BROWSER_DEVICE_ID_STORAGE_KEY = "programacoes_concretagem_device_id_v1"
BROWSER_DEVICE_QUERY_KEY = "pcid"
DEVICE_SCENARIOS_DIR = Path(tempfile.gettempdir()) / "programacoes_concretagem_browser_saved_scenarios"
TURNO_OPTIONS = ["Diurno", "Noturno"]
INICIO_DIA_OPTIONS = [0, 1, 2]
INICIO_DIA_LABELS = {
    0: "D",
    1: "D+1",
    2: "D+2",
}
CALCULATION_SIGNATURE_VERSION = "2026-04-08-priority-shared-v3"


st.set_page_config(
    page_title="Programação de Concretagens",
    layout="wide",
)


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stHeader"] {
            background: transparent;
        }
        div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlockBorderWrapper"] {
            background: transparent;
        }
        div[data-testid="stForm"] {
            border: none !important;
            padding: 0 !important;
            background: transparent !important;
        }
        .element-container:has(textarea[aria-label="__browser_saved_scenarios_storage__"]) {
            display: none !important;
        }
        .section-helper {
            color: #5f6b7a;
            font-size: 0.95rem;
            margin-top: -0.35rem;
            margin-bottom: 0.9rem;
        }
        .page-title-block {
            margin-bottom: 0.95rem;
        }
        .page-title-row {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 0.75rem;
        }
        .page-title-text {
            font-size: 2.15rem;
            line-height: 1.06;
            font-weight: 700;
            margin: 0;
            color: inherit;
        }
        .page-title-subtitle {
            color: #5f6b7a;
            font-size: 0.95rem;
            margin-top: 0.25rem;
        }
        .page-title-help {
            display: none;
            flex: 0 0 auto;
        }
        .page-title-help details {
            position: relative;
        }
        .page-title-help summary {
            list-style: none;
            width: 1.8rem;
            height: 1.8rem;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 999px;
            border: 1px solid rgba(127, 127, 127, 0.18);
            background: rgba(127, 127, 127, 0.05);
            color: #6b7280;
            font-weight: 700;
            cursor: pointer;
            user-select: none;
        }
        .page-title-help summary::-webkit-details-marker {
            display: none;
        }
        .page-title-help .body {
            position: absolute;
            right: 0;
            top: 2.15rem;
            z-index: 5;
            width: min(78vw, 320px);
            padding: 0.7rem 0.8rem;
            border-radius: 10px;
            border: 1px solid rgba(127, 127, 127, 0.18);
            background: var(--secondary-background-color, #eef2f7);
            color: var(--text-color, #0f172a);
            box-shadow: 0 10px 25px rgba(15, 23, 42, 0.14);
            font-size: 0.88rem;
            line-height: 1.4;
        }
        .mobile-info-helper {
            display: none;
            margin: -0.2rem 0 0.85rem 0;
        }
        .mobile-info-helper details {
            border: 1px solid rgba(128, 128, 128, 0.16);
            border-radius: 10px;
            padding: 0.12rem 0.75rem;
            background: rgba(127, 127, 127, 0.035);
        }
        .mobile-info-helper summary {
            cursor: pointer;
            list-style: none;
            font-size: 0.9rem;
            color: #7c8796;
            font-weight: 600;
        }
        .mobile-info-helper summary::-webkit-details-marker {
            display: none;
        }
        .mobile-info-helper .body {
            font-size: 0.88rem;
            color: #9aa6b6;
            line-height: 1.4;
            padding: 0.45rem 0 0.25rem 0;
        }
        .page-separator {
            height: 1px;
            background: rgba(255, 255, 255, 0.1);
            margin: 1.1rem 0 1.4rem 0;
        }
        .main-section-gap {
            height: 0.95rem;
        }
        .active-scenario-box {
            border-radius: 12px;
            min-height: 40px;
            padding: 0.35rem 0.9rem;
            box-sizing: border-box;
            display: flex;
            align-items: center;
            font-size: 0.96rem;
            font-weight: 700;
            margin-bottom: 0.15rem;
        }
        .scenario-meta-preview {
            padding: 0.15rem 0 0.55rem 0;
            color: #5f6b7a;
            font-size: 0.94rem;
        }
        .stApp,
        html,
        body {
            --result-surface-bg: var(--secondary-background-color, #eef2f7);
            --result-surface-title: var(--text-color, #0f172a);
            --result-surface-label: color-mix(
                in srgb,
                var(--text-color, #0f172a) 82%,
                var(--background-color, #ffffff) 18%
            );
            --result-surface-text: color-mix(
                in srgb,
                var(--text-color, #0f172a) 74%,
                var(--background-color, #ffffff) 26%
            );
            --result-box-bg: var(--secondary-background-color, #eef2f7);
            --result-box-title: var(--text-color, #0f172a);
            --result-box-subtitle: color-mix(
                in srgb,
                var(--text-color, #0f172a) 74%,
                var(--background-color, #ffffff) 26%
            );
            --result-box-text: color-mix(
                in srgb,
                var(--text-color, #0f172a) 78%,
                var(--background-color, #ffffff) 22%
            );
            --result-note-bg: var(--secondary-background-color, #eef2f7);
            --result-note-title: var(--text-color, #0f172a);
            --result-note-text: color-mix(
                in srgb,
                var(--text-color, #0f172a) 78%,
                var(--background-color, #ffffff) 22%
            );
        }
        .result-status-card {
            --card-border: color-mix(in srgb, var(--text-color, #ffffff) 12%, transparent);
            --card-accent: rgba(255, 255, 255, 0.18);
            --card-bg: var(--result-surface-bg, #1e2633);
            --card-label: #b8c6d9;
            --card-title: #f8fafc;
            --card-text: #d7e0eb;
            border: 1px solid var(--card-border);
            border-left: 4px solid var(--card-accent);
            border-radius: 12px;
            padding: 0.8rem 0.9rem;
            height: 178px;
            background: var(--card-bg);
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .result-status-card .label {
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: var(--card-label);
            opacity: 0.92;
            margin-bottom: 0.3rem;
        }
        .result-status-card .value {
            font-size: 1.35rem;
            font-weight: 700;
            line-height: 1.15;
            margin-bottom: 0.2rem;
            color: var(--card-title);
        }
        .result-status-card .subvalue {
            font-size: 0.88rem;
            color: var(--card-text);
            opacity: 0.98;
            margin-top: auto;
            overflow: hidden;
            display: -webkit-box;
            -webkit-box-orient: vertical;
            -webkit-line-clamp: 4;
            line-clamp: 4;
        }
        .result-status-card.ok {
            --card-border: rgba(103, 203, 114, 0.34);
            --card-accent: rgba(103, 203, 114, 0.92);
            --card-bg: #314637;
        }
        .result-status-card.warn {
            --card-border: rgba(85, 131, 235, 0.34);
            --card-accent: rgba(85, 131, 235, 0.92);
            --card-bg: #2b3650;
        }
        .result-status-card.bad {
            --card-border: rgba(242, 112, 118, 0.34);
            --card-accent: rgba(242, 112, 118, 0.92);
            --card-bg: #4a2f35;
        }
        .result-status-card.info {
            --card-border: rgba(93, 147, 255, 0.34);
            --card-accent: rgba(93, 147, 255, 0.92);
            --card-bg: #2d3b57;
        }
        .result-kicker {
            font-size: 0.84rem;
            color: #5f6b7a;
            margin-bottom: 0.85rem;
        }
        .result-box {
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 12px;
            padding: 0.85rem 1rem;
            background: var(--result-box-bg, #1f2937);
            color: var(--result-box-text, #e5edf7);
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.14);
            margin: 0 0 1rem 0;
        }
        .result-box .title {
            font-size: 0.9rem;
            font-weight: 700;
            margin-bottom: 0.45rem;
            color: var(--result-box-title, #f8fafc);
        }
        .result-box .subtitle {
            font-size: 0.8rem;
            font-weight: 700;
            color: var(--result-box-subtitle, #cbd5e1);
            opacity: 0.82;
            margin: 0.55rem 0 0.25rem 0;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }
        .result-box ul {
            margin: 0.1rem 0 0 1.1rem;
            padding: 0;
        }
        .result-box li {
            margin: 0.28rem 0;
            line-height: 1.45;
        }
        .result-inline-note {
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 10px;
            padding: 0.7rem 0.9rem;
            background: var(--result-box-bg, #1f2937);
            color: var(--result-box-text, #e5edf7);
            margin: 0.55rem 0 0.2rem 0;
        }
        .result-inline-note .title {
            font-size: 0.84rem;
            font-weight: 700;
            margin-bottom: 0.2rem;
            color: var(--result-box-title, #f8fafc);
        }
        .result-inline-note .body {
            font-size: 0.93rem;
            line-height: 1.45;
            color: var(--result-box-text, #e5edf7);
            opacity: 0.9;
        }
        .result-linked-note {
            margin: 0.5rem 0 0 0;
            padding: 0.6rem 0.75rem;
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-left: 3px solid rgba(255, 255, 255, 0.22);
            border-radius: 0 10px 10px 0;
            background: var(--result-note-bg, #273142);
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.14);
        }
        .result-linked-note .title {
            font-size: 0.8rem;
            font-weight: 700;
            margin-bottom: 0.18rem;
            color: var(--result-note-title, #ffffff);
        }
        .result-linked-note .body {
            font-size: 0.86rem;
            line-height: 1.42;
            color: var(--result-note-text, #dbe4f0);
            opacity: 0.9;
        }
        .result-linked-note.ok {
            border-left-color: #52b36a;
        }
        .result-linked-note.warn {
            border-left-color: #d89224;
        }
        .result-linked-note.bad {
            border-left-color: #d95a57;
        }
        .result-linked-note.info {
            border-left-color: #5ba8e8;
        }
        .result-mini-card {
            border: 1px solid #3b475c;
            border-radius: 10px;
            padding: 0.7rem 0.85rem;
            min-height: 82px;
            background: var(--result-note-bg, #273142);
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.16);
        }
        .result-mini-card .label {
            font-size: 0.8rem;
            color: var(--text-color, #cbd5e1);
            opacity: 0.82;
            margin-bottom: 0.28rem;
        }
        .result-mini-card .value {
            font-size: 1.1rem;
            font-weight: 700;
            color: var(--text-color, #ffffff);
            line-height: 1.1;
        }
        .result-mini-card .subvalue {
            margin-top: 0.22rem;
            font-size: 0.82rem;
            color: var(--text-color, #dbe4f0);
            opacity: 0.9;
        }
        .result-row-gap {
            height: 0.8rem;
        }
        .element-container:has(.mobile-static-planning-marker),
        .element-container:has(.mobile-static-planning-marker) + .element-container,
        .element-container:has(.mobile-static-disponibilidade-marker),
        .element-container:has(.mobile-static-disponibilidade-marker) + .element-container {
            display: none !important;
        }
        .element-container:has(.desktop-plotly-planning-marker),
        .element-container:has(.desktop-plotly-disponibilidade-marker) {
            display: none !important;
        }
        .element-container:has(.scenario-meta-expander-marker) + div[data-testid="stExpander"] details {
            border: none !important;
            background: transparent !important;
            box-shadow: none !important;
            padding: 0 !important;
        }
        .element-container:has(.scenario-meta-expander-marker) + div[data-testid="stExpander"] summary {
            display: none !important;
        }
        .element-container:has(.scenario-meta-expander-marker) + div[data-testid="stExpander"] > div {
            margin-top: 0 !important;
        }
        div[data-testid="stButton"] button[kind="primary"] {
            background: #1f5f33;
            border: 1px solid #2f7a46;
            color: #ffffff;
            font-weight: 700;
        }
        div[data-testid="stButton"] button[kind="primary"]:hover {
            background: #184c29;
            border-color: #2f7a46;
            color: #ffffff;
        }
        div[data-baseweb="select"] [data-baseweb="tag"] {
            max-width: none !important;
            width: auto !important;
            min-width: max-content !important;
            flex: 0 0 auto !important;
            overflow: visible !important;
        }
        div[data-baseweb="select"] [data-baseweb="tag"] * {
            max-width: none !important;
        }
        div[data-baseweb="select"] [data-baseweb="tag"] span {
            overflow: visible !important;
            text-overflow: unset !important;
            white-space: nowrap !important;
        }
        .stApp[data-codex-theme="light"] .section-helper,
        .stApp[data-codex-theme="light"] .result-kicker,
        .stApp[data-codex-theme="light"] .scenario-meta-preview,
        body[data-codex-theme="light"] .section-helper,
        body[data-codex-theme="light"] .result-kicker,
        body[data-codex-theme="light"] .scenario-meta-preview,
        html[data-codex-theme="light"] .section-helper,
        html[data-codex-theme="light"] .result-kicker,
        html[data-codex-theme="light"] .scenario-meta-preview {
            color: #4b5563;
        }
        .stApp[data-codex-theme="light"] .result-status-card,
        .stApp[data-codex-theme="light"] .result-box,
        .stApp[data-codex-theme="light"] .result-inline-note,
        .stApp[data-codex-theme="light"] .result-linked-note,
        .stApp[data-codex-theme="light"] .result-mini-card,
        body[data-codex-theme="light"] .result-status-card,
        body[data-codex-theme="light"] .result-box,
        body[data-codex-theme="light"] .result-inline-note,
        body[data-codex-theme="light"] .result-linked-note,
        body[data-codex-theme="light"] .result-mini-card,
        html[data-codex-theme="light"] .result-status-card,
        html[data-codex-theme="light"] .result-box,
        html[data-codex-theme="light"] .result-inline-note,
        html[data-codex-theme="light"] .result-linked-note,
        html[data-codex-theme="light"] .result-mini-card {
            background: var(--result-surface-bg, var(--secondary-background-color, #eef2f7));
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
        }
        .stApp[data-codex-theme="light"] .result-status-card.ok,
        body[data-codex-theme="light"] .result-status-card.ok,
        html[data-codex-theme="light"] .result-status-card.ok {
            --card-bg: #f2fbf4;
            --card-label: #5f6b7a;
            --card-title: #0f172a;
            --card-text: #475569;
        }
        .stApp[data-codex-theme="light"] .result-status-card.bad,
        body[data-codex-theme="light"] .result-status-card.bad,
        html[data-codex-theme="light"] .result-status-card.bad {
            --card-bg: #fdf2f3;
            --card-label: #5f6b7a;
            --card-title: #0f172a;
            --card-text: #475569;
        }
        .stApp[data-codex-theme="light"] .result-status-card.info,
        body[data-codex-theme="light"] .result-status-card.info,
        html[data-codex-theme="light"] .result-status-card.info {
            --card-bg: #f1f6ff;
            --card-label: #5f6b7a;
            --card-title: #0f172a;
            --card-text: #475569;
        }
        .stApp[data-codex-theme="light"] .result-status-card.warn,
        body[data-codex-theme="light"] .result-status-card.warn,
        html[data-codex-theme="light"] .result-status-card.warn {
            --card-bg: #f1f6ff;
            --card-label: #5f6b7a;
            --card-title: #0f172a;
            --card-text: #475569;
        }
        .stApp[data-codex-theme="dark"] .result-status-card,
        .stApp[data-codex-theme="dark"] .result-box,
        .stApp[data-codex-theme="dark"] .result-inline-note,
        .stApp[data-codex-theme="dark"] .result-linked-note,
        .stApp[data-codex-theme="dark"] .result-mini-card,
        body[data-codex-theme="dark"] .result-status-card,
        body[data-codex-theme="dark"] .result-box,
        body[data-codex-theme="dark"] .result-inline-note,
        body[data-codex-theme="dark"] .result-linked-note,
        body[data-codex-theme="dark"] .result-mini-card,
        html[data-codex-theme="dark"] .result-status-card,
        html[data-codex-theme="dark"] .result-box,
        html[data-codex-theme="dark"] .result-inline-note,
        html[data-codex-theme="dark"] .result-linked-note,
        html[data-codex-theme="dark"] .result-mini-card {
            background: #2a3344;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.22);
        }
        .stApp[data-codex-theme="dark"] .result-status-card.ok,
        body[data-codex-theme="dark"] .result-status-card.ok,
        html[data-codex-theme="dark"] .result-status-card.ok {
            background: #314637;
        }
        .stApp[data-codex-theme="dark"] .result-status-card.bad,
        body[data-codex-theme="dark"] .result-status-card.bad,
        html[data-codex-theme="dark"] .result-status-card.bad {
            background: #4a2f35;
        }
        .stApp[data-codex-theme="dark"] .result-status-card.info,
        body[data-codex-theme="dark"] .result-status-card.info,
        html[data-codex-theme="dark"] .result-status-card.info {
            background: #2d3b57;
        }
        .stApp[data-codex-theme="dark"] .result-status-card.warn,
        body[data-codex-theme="dark"] .result-status-card.warn,
        html[data-codex-theme="dark"] .result-status-card.warn {
            background: #2b3650;
        }
        .stApp[data-codex-theme="dark"] .result-status-card .label,
        .stApp[data-codex-theme="dark"] .result-kicker,
        .stApp[data-codex-theme="dark"] .result-box .subtitle,
        .stApp[data-codex-theme="dark"] .result-mini-card .label,
        body[data-codex-theme="dark"] .result-status-card .label,
        body[data-codex-theme="dark"] .result-kicker,
        body[data-codex-theme="dark"] .result-box .subtitle,
        body[data-codex-theme="dark"] .result-mini-card .label,
        html[data-codex-theme="dark"] .result-status-card .label,
        html[data-codex-theme="dark"] .result-kicker,
        html[data-codex-theme="dark"] .result-box .subtitle,
        html[data-codex-theme="dark"] .result-mini-card .label {
            color: #9fb0c5;
        }
        .stApp[data-codex-theme="dark"] .result-status-card .value,
        .stApp[data-codex-theme="dark"] .result-box .title,
        .stApp[data-codex-theme="dark"] .result-inline-note .title,
        .stApp[data-codex-theme="dark"] .result-linked-note .title,
        .stApp[data-codex-theme="dark"] .result-mini-card .value,
        body[data-codex-theme="dark"] .result-status-card .value,
        body[data-codex-theme="dark"] .result-box .title,
        body[data-codex-theme="dark"] .result-inline-note .title,
        body[data-codex-theme="dark"] .result-linked-note .title,
        body[data-codex-theme="dark"] .result-mini-card .value,
        html[data-codex-theme="dark"] .result-status-card .value,
        html[data-codex-theme="dark"] .result-box .title,
        html[data-codex-theme="dark"] .result-inline-note .title,
        html[data-codex-theme="dark"] .result-linked-note .title,
        html[data-codex-theme="dark"] .result-mini-card .value {
            color: #f8fafc;
        }
        .stApp[data-codex-theme="dark"] .result-status-card .subvalue,
        .stApp[data-codex-theme="dark"] .result-box,
        .stApp[data-codex-theme="dark"] .result-inline-note .body,
        .stApp[data-codex-theme="dark"] .result-linked-note .body,
        .stApp[data-codex-theme="dark"] .result-mini-card .subvalue,
        body[data-codex-theme="dark"] .result-status-card .subvalue,
        body[data-codex-theme="dark"] .result-box,
        body[data-codex-theme="dark"] .result-inline-note .body,
        body[data-codex-theme="dark"] .result-linked-note .body,
        body[data-codex-theme="dark"] .result-mini-card .subvalue,
        html[data-codex-theme="dark"] .result-status-card .subvalue,
        html[data-codex-theme="dark"] .result-box,
        html[data-codex-theme="dark"] .result-inline-note .body,
        html[data-codex-theme="dark"] .result-linked-note .body,
        html[data-codex-theme="dark"] .result-mini-card .subvalue {
            color: #d4dde8;
        }
        @media (max-width: 768px) {
            .mobile-hidden,
            .page-title-subtitle {
                display: none !important;
            }
            .mobile-info-helper,
            .page-title-help {
                display: block;
            }
            .block-container {
                padding-left: 0.8rem !important;
                padding-right: 0.8rem !important;
                padding-top: 1rem !important;
            }
            .page-title-block {
                margin-bottom: 0.78rem;
            }
            .page-title-row {
                gap: 0.55rem;
            }
            .page-title-text {
                font-size: 1.72rem !important;
                line-height: 1.08;
                flex: 1 1 auto;
            }
            .stApp h2 {
                font-size: 1.28rem !important;
            }
            .stApp h3 {
                font-size: 1.08rem !important;
            }
            .active-scenario-box {
                min-height: unset;
                line-height: 1.3;
                align-items: flex-start;
                flex-wrap: wrap;
                font-size: 0.84rem;
                padding: 0.38rem 0.65rem;
                border-radius: 10px;
            }
            .active-scenario-box > span {
                display: block;
                width: 100%;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .element-container:has(.active-scenario-box-marker) + .element-container {
                margin-bottom: 0.45rem !important;
            }
            .section-helper,
            .scenario-meta-preview,
            .result-kicker {
                font-size: 0.88rem;
                margin-bottom: 0.65rem;
            }
            div[data-testid="stHorizontalBlock"] {
                gap: 0.55rem !important;
                row-gap: 0.55rem !important;
            }
            div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
                width: 100% !important;
                min-width: 0 !important;
                flex: 1 1 100% !important;
            }
            div[data-testid="stExpander"] details {
                border-radius: 12px;
            }
            div[data-testid="stExpander"] summary {
                padding-top: 0.15rem !important;
                padding-bottom: 0.15rem !important;
            }
            div[data-testid="stExpander"] summary p {
                font-size: 0.96rem !important;
            }
            div[data-testid="stTextInput"] label p,
            div[data-testid="stNumberInput"] label p,
            div[data-testid="stDateInput"] label p,
            div[data-testid="stTimeInput"] label p,
            div[data-testid="stSelectbox"] label p,
            div[data-testid="stMultiSelect"] label p,
            div[data-testid="stCheckbox"] label p,
            div[data-testid="stRadio"] label p {
                font-size: 0.92rem !important;
            }
            div[data-testid="stButton"] button,
            div[data-testid="stDownloadButton"] button {
                min-height: 2.7rem;
                font-size: 0.95rem !important;
            }
            div[data-testid="stButton"] button {
                width: 100%;
            }
            .element-container:has(.scenario-actions-row-two-marker) + div[data-testid="stHorizontalBlock"] {
                gap: 0.45rem !important;
                row-gap: 0.45rem !important;
                flex-wrap: wrap !important;
            }
            .element-container:has(.scenario-actions-row-two-marker) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
                width: calc(50% - 0.25rem) !important;
                min-width: calc(50% - 0.25rem) !important;
                flex: 1 1 calc(50% - 0.25rem) !important;
            }
            .element-container:has(.scenario-actions-row-two-marker) + div[data-testid="stHorizontalBlock"] button,
            .element-container:has(.scenario-actions-row-single-marker) + div[data-testid="stHorizontalBlock"] button {
                font-size: 0.78rem !important;
                min-height: 2.15rem;
                padding-left: 0.35rem !important;
                padding-right: 0.35rem !important;
                white-space: normal !important;
                line-height: 1.12 !important;
            }
            .element-container:has(.scenario-actions-row-single-marker) + div[data-testid="stHorizontalBlock"] {
                gap: 0.45rem !important;
            }
            .element-container:has(.program-actions-marker) + div[data-testid="stHorizontalBlock"],
            .element-container:has(.calc-actions-marker) + div[data-testid="stHorizontalBlock"],
            .element-container:has(.result-export-actions-marker) + div[data-testid="stHorizontalBlock"] {
                gap: 0.45rem !important;
                row-gap: 0.45rem !important;
                flex-wrap: wrap !important;
            }
            .element-container:has(.program-actions-marker) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
            .element-container:has(.calc-actions-marker) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
            .element-container:has(.result-export-actions-marker) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
                width: calc(50% - 0.25rem) !important;
                min-width: calc(50% - 0.25rem) !important;
                flex: 1 1 calc(50% - 0.25rem) !important;
            }
            .element-container:has(.program-actions-marker) + div[data-testid="stHorizontalBlock"] button,
            .element-container:has(.calc-actions-marker) + div[data-testid="stHorizontalBlock"] button,
            .element-container:has(.result-export-actions-marker) + div[data-testid="stHorizontalBlock"] button {
                font-size: 0.83rem !important;
                min-height: 2.45rem;
                padding-left: 0.35rem !important;
                padding-right: 0.35rem !important;
                white-space: normal !important;
                line-height: 1.12 !important;
            }
            .element-container:has(.scenario-meta-expander-marker) + div[data-testid="stExpander"] summary {
                display: flex !important;
            }
            .element-container:has(.scenario-meta-expander-marker) + div[data-testid="stExpander"] details {
                border-radius: 12px !important;
                border: 1px solid rgba(148, 163, 184, 0.16) !important;
                background: rgba(127, 127, 127, 0.03) !important;
                padding: 0 !important;
            }
            .element-container:has(.desktop-plotly-planning-marker),
            .element-container:has(.desktop-plotly-planning-marker) + .element-container,
            .element-container:has(.desktop-plotly-disponibilidade-marker),
            .element-container:has(.desktop-plotly-disponibilidade-marker) + .element-container {
                display: none !important;
            }
            .element-container:has(.mobile-static-planning-marker),
            .element-container:has(.mobile-static-disponibilidade-marker) {
                display: none !important;
            }
            .element-container:has(.mobile-static-planning-marker) + .element-container,
            .element-container:has(.mobile-static-disponibilidade-marker) + .element-container {
                display: block !important;
            }
            .result-status-card,
            .result-mini-card,
            .result-box,
            .result-inline-note,
            .result-linked-note {
                padding: 0.62rem 0.72rem;
            }
            .result-status-card,
            .result-mini-card {
                height: auto;
                min-height: 94px;
            }
            .result-status-card .value {
                font-size: 0.92rem;
            }
            .result-status-card .subvalue,
            .result-mini-card .subvalue,
            .result-linked-note .body {
                font-size: 0.75rem;
            }
            .result-status-card .label,
            .result-mini-card .label {
                font-size: 0.68rem;
            }
            .result-mini-card .value {
                font-size: 0.9rem;
            }
            .result-linked-note,
            .result-inline-note,
            .result-box {
                margin-top: 0.45rem;
            }
            .result-status-card {
                margin-bottom: 0.06rem;
                padding: 0.58rem 0.62rem;
            }
            .result-row-gap {
                height: 0.35rem;
            }
            .result-status-card .subvalue {
                margin-top: 0.26rem !important;
                display: -webkit-box;
                -webkit-box-orient: vertical;
                -webkit-line-clamp: 2;
                line-clamp: 2;
                overflow: hidden;
            }
            div[data-testid="stDataFrame"] {
                overflow-x: auto;
            }
            div[data-baseweb="tab-list"] {
                gap: 0.2rem !important;
                overflow-x: auto;
                scrollbar-width: thin;
                white-space: nowrap;
            }
            button[data-baseweb="tab"] {
                padding-left: 0.6rem !important;
                padding-right: 0.6rem !important;
                min-width: max-content;
            }
            button[data-baseweb="tab"] p {
                font-size: 0.92rem !important;
            }
            div[data-baseweb="select"] [data-baseweb="tag"] {
                max-width: 100% !important;
                width: auto !important;
                min-width: 0 !important;
                flex: 1 1 auto !important;
            }
            div[data-baseweb="select"] [data-baseweb="tag"] span {
                white-space: normal !important;
                line-height: 1.25 !important;
            }
            iframe[title^="streamlit"] {
                max-width: 100%;
            }
            div[data-testid="stPlotlyChart"] {
                overflow-x: hidden;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _disable_saved_scenario_search() -> None:
    components.html(
        """
        <script>
        const lockScenarioSelectSearch = () => {
          const labels = window.parent.document.querySelectorAll('label');
          labels.forEach((label) => {
            if ((label.textContent || '').trim() !== 'Cenários salvos') return;
            const container = label.closest('[data-testid="stWidgetLabel"]')?.parentElement?.parentElement;
            if (!container) return;
            const combo = container.querySelector('input[role="combobox"]');
            if (!combo || combo.dataset.searchLocked === 'true') return;
            combo.dataset.searchLocked = 'true';
            combo.setAttribute('readonly', 'readonly');
            combo.addEventListener('keydown', (event) => {
              const allowed = ['Tab', 'Escape', 'Enter', 'ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End'];
              if (!allowed.includes(event.key)) {
                event.preventDefault();
              }
            });
          });
        };
        setTimeout(lockScenarioSelectSearch, 80);
        </script>
        """,
        height=0,
    )


def _sync_theme_marker() -> None:
    components.html(
        """
        <script>
        const parseColor = (value) => {
          if (!value) return null;
          const rgbMatch = value.trim().match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/i);
          if (rgbMatch) {
            return [Number(rgbMatch[1]), Number(rgbMatch[2]), Number(rgbMatch[3])];
          }
          const hexMatch = value.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
          if (hexMatch) {
            const raw = hexMatch[1];
            const hex = raw.length === 3 ? raw.split('').map((c) => c + c).join('') : raw;
            return [
              parseInt(hex.slice(0, 2), 16),
              parseInt(hex.slice(2, 4), 16),
              parseInt(hex.slice(4, 6), 16),
            ];
          }
          return null;
        };

        const luminance = ([r, g, b]) => {
          const norm = [r, g, b].map((channel) => {
            const value = channel / 255;
            return value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4);
          });
          return 0.2126 * norm[0] + 0.7152 * norm[1] + 0.0722 * norm[2];
        };

        const syncTheme = () => {
          const localRoot = document.documentElement;
          const localBody = document.body;
          const stApp = document.querySelector('.stApp');
          const parentDoc = window.parent.document;
          const root = parentDoc.documentElement;
          const body = parentDoc.body;
          const localStyles = window.getComputedStyle(localRoot);
          const parentStyles = window.parent.getComputedStyle(root);
          const stAppStyles = stApp ? window.getComputedStyle(stApp) : null;
          const textCandidates = [
            localStyles.getPropertyValue('--text-color'),
            stAppStyles ? stAppStyles.color : '',
            window.getComputedStyle(localBody).color,
            parentStyles.getPropertyValue('--text-color'),
            window.parent.getComputedStyle(body).color,
          ];
          const colorCandidates = [
            stAppStyles ? stAppStyles.backgroundColor : '',
            localStyles.getPropertyValue('--background-color'),
            localStyles.getPropertyValue('--secondary-background-color'),
            window.getComputedStyle(localBody).backgroundColor,
            parentStyles.getPropertyValue('--background-color'),
            parentStyles.getPropertyValue('--secondary-background-color'),
            window.parent.getComputedStyle(body).backgroundColor,
          ];
          const colorValue = colorCandidates.find((value) => parseColor(value));
          const rgb = parseColor(colorValue);
          const textValue = textCandidates.find((value) => parseColor(value));
          const textRgb = parseColor(textValue);
          if (!textRgb && !rgb) return;
          const theme = rgb
            ? luminance(rgb) > 0.45
              ? 'light'
              : 'dark'
            : textRgb
              ? luminance(textRgb) < 0.45
                ? 'light'
                : 'dark'
              : 'light';
          body.setAttribute('data-codex-theme', theme);
          root.setAttribute('data-codex-theme', theme);
          localBody.setAttribute('data-codex-theme', theme);
          localRoot.setAttribute('data-codex-theme', theme);
          if (stApp) {
            stApp.setAttribute('data-codex-theme', theme);
          }
        };

        syncTheme();
        setTimeout(syncTheme, 50);
        setTimeout(syncTheme, 250);
        </script>
        """,
        height=0,
    )


def _render_section_heading(title: str, helper_text: str) -> None:
    st.subheader(title)
    st.markdown(f"<div class='section-helper'>{helper_text}</div>", unsafe_allow_html=True)


def _render_mobile_info_helper(helper_text: str, summary_text: str = "Sobre esta tela") -> None:
    st.markdown(
        (
            "<div class='mobile-info-helper'>"
            f"<details><summary>{summary_text}</summary>"
            f"<div class='body'>{helper_text}</div>"
            "</details>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _sync_expander_open_state(label_text: str, storage_key: str, mobile_default_open: bool) -> None:
    label_json = json.dumps(label_text, ensure_ascii=False)
    storage_json = json.dumps(storage_key, ensure_ascii=False)
    mobile_default = "true" if mobile_default_open else "false"
    components.html(
        f"""
        <script>
        const expanderLabel = {label_json};
        const storageKey = {storage_json};
        const mobileDefaultOpen = {mobile_default};

        const findExpanderDetails = () => {{
          const detailsList = Array.from(window.parent.document.querySelectorAll('div[data-testid="stExpander"] details'));
          return detailsList.find((details) => {{
            const summaryText = (details.querySelector('summary')?.textContent || '').trim();
            return summaryText === expanderLabel;
          }});
        }};

        const syncExpander = () => {{
          const details = findExpanderDetails();
          if (!details) return;
          const isMobile = window.parent.innerWidth <= 768;
          const stored = window.parent.sessionStorage.getItem(storageKey);

          if (stored === null) {{
            details.open = isMobile ? mobileDefaultOpen : true;
            window.parent.sessionStorage.setItem(storageKey, details.open ? '1' : '0');
          }} else {{
            details.open = stored === '1';
          }}

          if (details.dataset.openStateBound === 'true') return;
          details.dataset.openStateBound = 'true';
          details.addEventListener('toggle', () => {{
            window.parent.sessionStorage.setItem(storageKey, details.open ? '1' : '0');
          }});
        }};

        setTimeout(syncExpander, 80);
        </script>
        """,
        height=0,
    )


def _render_subsection_heading(title: str, helper_text: str) -> None:
    st.markdown(f"**{title}**")
    st.caption(helper_text)


def _apply_detail_filters(dataframe: pd.DataFrame, key_prefix: str = "base") -> pd.DataFrame:
    filtered = dataframe.copy()
    with st.expander("Filtros da tabela", expanded=False):
        st.caption("Refine o detalhamento por programação, BT, viagem, etapa ou busca textual.")
        c1, c2, c3, c4 = st.columns(4)

        programacoes = []
        if "Programação" in filtered.columns:
            programacoes = c1.multiselect(
                "Programação",
                options=sorted(filtered["Programação"].dropna().unique().tolist()),
                key=f"{key_prefix}_detalhamento_filter_programacao",
            )

        bts = []
        if "BT" in filtered.columns:
            bts = c2.multiselect(
                "BT",
                options=sorted(filtered["BT"].dropna().unique().tolist()),
                key=f"{key_prefix}_detalhamento_filter_bt",
            )

        viagens = []
        if "Viagem" in filtered.columns:
            viagens = c3.multiselect(
                "Viagem",
                options=sorted(filtered["Viagem"].dropna().unique().tolist()),
                key=f"{key_prefix}_detalhamento_filter_viagem",
            )

        etapas = []
        if "Etapa" in filtered.columns:
            etapas = c4.multiselect(
                "Etapa",
                options=sorted(filtered["Etapa"].dropna().unique().tolist()),
                key=f"{key_prefix}_detalhamento_filter_etapa",
            )

        busca_textual = st.text_input(
            "Busca textual",
            value=st.session_state.get(f"{key_prefix}_detalhamento_filter_busca", ""),
            placeholder="Ex.: descarga, bomba, V03, D20 P6, aguardando...",
            key=f"{key_prefix}_detalhamento_filter_busca",
        ).strip()

        if programacoes:
            filtered = filtered[filtered["Programação"].isin(programacoes)]
        if bts:
            filtered = filtered[filtered["BT"].isin(bts)]
        if viagens:
            filtered = filtered[filtered["Viagem"].isin(viagens)]
        if etapas:
            filtered = filtered[filtered["Etapa"].isin(etapas)]
        if busca_textual:
            search_columns = [
                column
                for column in ["Programação", "BT", "Etapa", "Início", "Fim", "Observação"]
                if column in filtered.columns
            ]
            if search_columns:
                mask = pd.Series(False, index=filtered.index)
                for column in search_columns:
                    mask = mask | filtered[column].fillna("").astype(str).str.contains(
                        busca_textual,
                        case=False,
                        regex=False,
                    )
                filtered = filtered[mask]

        st.caption(f"{len(filtered)} linha(s) exibida(s) após os filtros.")

    return filtered


def _dataframe_height_for_rows(
    row_count: int,
    *,
    row_height: int = 33,
    header_height: int = 35,
    padding: int = 2,
    min_height: int = 72,
    max_height: int = 560,
) -> int:
    estimated = header_height + (max(row_count, 1) * row_height) + padding
    return max(min_height, min(estimated, max_height))


def _render_result_status_card(label: str, value: str, subvalue: str = "", tone: str = "") -> None:
    tone_class = f" {tone}" if tone else ""
    subvalue_html = f"<div class='subvalue'>{subvalue}</div>" if subvalue else ""
    st.markdown(
        (
            f"<div class='result-status-card{tone_class}'>"
            f"<div class='label'>{label}</div>"
            f"<div class='value'>{value}</div>"
            f"{subvalue_html}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_result_box(title: str, lines: list[str]) -> None:
    content = "<ul>" + "".join(f"<li>{line}</li>" for line in lines) + "</ul>"
    st.markdown(
        f"<div class='result-box'><div class='title'>{title}</div>{content}</div>",
        unsafe_allow_html=True,
    )


def _render_result_box_sections(title: str, sections: list[tuple[str, list[str]]]) -> None:
    parts = [f"<div class='title'>{title}</div>"]
    for subtitle, lines in sections:
        if not lines:
            continue
        parts.append(f"<div class='subtitle'>{subtitle}</div>")
        parts.append("<ul>" + "".join(f"<li>{line}</li>" for line in lines) + "</ul>")
    st.markdown(
        f"<div class='result-box'>{''.join(parts)}</div>",
        unsafe_allow_html=True,
    )


def _render_result_mini_card(label: str, value: str, subvalue: str = "") -> None:
    subvalue_html = f"<div class='subvalue'>{subvalue}</div>" if subvalue else ""
    st.markdown(
        (
            "<div class='result-mini-card'>"
            f"<div class='label'>{label}</div>"
            f"<div class='value'>{value}</div>"
            f"{subvalue_html}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_result_inline_note(title: str, body: str) -> None:
    st.markdown(
        (
            "<div class='result-inline-note'>"
            f"<div class='title'>{title}</div>"
            f"<div class='body'>{body}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_result_linked_note(title: str, body: str, tone: str = "") -> None:
    tone_class = f" {tone}" if tone else ""
    st.markdown(
        (
            f"<div class='result-linked-note{tone_class}'>"
            f"<div class='title'>{title}</div>"
            f"<div class='body'>{body}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _format_priority_label(prioridade: int | None) -> str:
    prioridade = int(prioridade or 0)
    return f"P{prioridade}" if prioridade > 0 else "Sem prioridade"


def _format_inicio_offset_label(offset_days: int | None) -> str:
    return INICIO_DIA_LABELS.get(int(offset_days or 0), "D")


def _current_scenario_label() -> str:
    scenario_name = st.session_state.get("current_scenario_name", "").strip()
    return _build_scenario_label(
        scenario_name or "Nome",
        st.session_state.current_scenario_date,
        st.session_state.current_scenario_turno,
    )


def _render_active_scenario_box() -> None:
    st.markdown(
        (
            "<div class='active-scenario-box' "
            "style='background:#1f5f33;border:1px solid #2f7a46;"
            "box-shadow:inset 0 1px 0 rgba(255,255,255,0.04);'>"
            f"<span style='color:#ffffff;font-weight:700;'>{_current_scenario_label()}</span>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _is_mobile_client() -> bool:
    user_agent = ""
    try:
        user_agent = str(st.context.headers.get("user-agent", "") or "")
    except Exception:
        user_agent = ""
    if not user_agent:
        return False
    mobile_markers = [
        "android",
        "iphone",
        "ipad",
        "ipod",
        "mobile",
        "opera mini",
        "iemobile",
    ]
    ua = user_agent.lower()
    return any(marker in ua for marker in mobile_markers)


def _render_program_tabs_anchor() -> None:
    st.markdown(
        "<div class='codex-program-tabs-anchor' style='height:0; margin:0; padding:0;'></div>",
        unsafe_allow_html=True,
    )


def _default_payload(index: int) -> dict:
    return {
        "id": f"concretagem-{index}",
        "nome_programacao": f"Frente {index}",
        "local": "Serra das Araras",
        "elemento_frente": f"Frente {index}",
        "usina": "Usina Serra",
        "tipo_cimento": "CP V-ARI",
        "observacoes": "",
        "volume_total_m3": 24.0,
        "capacidade_bt_m3": 8.0,
        "numero_bts_fixo": 0,
        "inicio_primeira_mistura": "07:00",
        "inicio_primeira_mistura_offset_dias": 0,
        "prioridade": 0,
        "prazo_limite_descarga": None,
        "ciclo": {
            "mistura_min": 10.0,
            "dosagem_min": 20.0,
            "ida_min": 10.0,
            "slump_min": 10.0,
            "descarga_min": 15.0,
            "lavagem_min": 10.0,
            "volta_min": 10.0,
        },
        "restricoes": {
            "com_bomba": True,
            "max_bts_frente": 1,
            "max_bts_mistura": 1,
            "max_bts_dosagem": 1,
            "existe_intervalo_entre_misturas": False,
            "intervalo_entre_misturas_min": 0.0,
            "existe_intervalo_maximo_entre_descargas": False,
            "intervalo_maximo_entre_descargas_min": 0.0,
            "ultima_viagem_parcial_proporcional": True,
            "permitir_primeira_viagem_customizada": False,
            "volume_primeira_viagem_m3": None,
            "alocacao_bts": "dedicadas",
        },
    }


def _default_saved_scenarios_file() -> dict:
    return {"scenarios": []}


def _widget_key(index: int, name: str) -> str:
    return f"scenario_{index}_{name}"


def _time_text_widget_key(base_key: str) -> str:
    return f"{base_key}__text"


def _time_text_sync_key(base_key: str) -> str:
    return f"{base_key}__text_synced"


def _time_text_error_key(base_key: str) -> str:
    return f"{base_key}__text_error"


def _format_time_text(value: time | None) -> str:
    if value is None:
        return ""
    return value.replace(second=0, microsecond=0).strftime("%H:%M")


def _parse_time_text_input(raw_value: str) -> time | None:
    raw_value = str(raw_value or "").strip()
    if not raw_value:
        return None

    try:
        parsed_value = parse_time_value(raw_value)
    except ValueError:
        parsed_value = None
    if parsed_value is not None:
        return parsed_value.replace(second=0, microsecond=0)

    digits_only = "".join(char for char in raw_value if char.isdigit())
    if len(digits_only) == 3:
        candidate = f"0{digits_only[0]}:{digits_only[1:]}"
    elif len(digits_only) == 4:
        candidate = f"{digits_only[:2]}:{digits_only[2:]}"
    else:
        return None

    try:
        parsed_value = parse_time_value(candidate)
    except ValueError:
        return None
    return parsed_value.replace(second=0, microsecond=0)


def _sync_time_text_state(base_key: str, value: time | None, *, force: bool = False) -> None:
    text_key = _time_text_widget_key(base_key)
    sync_key = _time_text_sync_key(base_key)
    error_key = _time_text_error_key(base_key)
    formatted = _format_time_text(value)
    current_text = st.session_state.get(text_key)
    previous_synced = st.session_state.get(sync_key)
    if force or text_key not in st.session_state or current_text == previous_synced:
        st.session_state[text_key] = formatted
        st.session_state[sync_key] = formatted
        st.session_state[error_key] = ""


def _commit_time_text_value(base_key: str) -> None:
    text_key = _time_text_widget_key(base_key)
    sync_key = _time_text_sync_key(base_key)
    error_key = _time_text_error_key(base_key)
    raw_value = str(st.session_state.get(text_key, "")).strip()
    parsed_value = _parse_time_text_input(raw_value)
    if parsed_value is None:
        st.session_state[error_key] = "Use HH:MM, HMM ou HHMM."
        return
    parsed_value = parsed_value.replace(second=0, microsecond=0)
    formatted = _format_time_text(parsed_value)
    st.session_state[base_key] = parsed_value
    st.session_state[text_key] = formatted
    st.session_state[sync_key] = formatted
    st.session_state[error_key] = ""


def _render_time_text_input(
    label: str,
    base_key: str,
    *,
    disabled: bool = False,
    help_text: str | None = None,
) -> None:
    st.text_input(
        label,
        key=_time_text_widget_key(base_key),
        placeholder="HH:MM",
        disabled=disabled,
        help=help_text,
        on_change=_commit_time_text_value,
        args=(base_key,),
    )
    error_message = st.session_state.get(_time_text_error_key(base_key), "")
    if error_message:
        st.caption(error_message)


def _program_display_name(index: int) -> str:
    payloads = st.session_state.get("scenario_payloads", [])
    payload = payloads[index - 1] if 0 < index <= len(payloads) else {}
    return _current_program_name(index, payload)


def _current_program_name(index: int, payload: dict | None = None) -> str:
    payload = payload or {}
    elemento_frente = str(st.session_state.get(_widget_key(index, "elemento_frente"), "")).strip()
    if elemento_frente:
        return elemento_frente
    nome_programacao = str(st.session_state.get(_widget_key(index, "nome_programacao"), "")).strip()
    if nome_programacao:
        return nome_programacao
    return str(
        payload.get("elemento_frente") or payload.get("nome_programacao") or f"Programação {index}"
    ).strip() or f"Programação {index}"


def _current_time_text(base_key: str) -> str:
    raw_value = st.session_state.get(_time_text_widget_key(base_key))
    if raw_value is None:
        raw_value = _format_time_text(st.session_state.get(base_key))
    return str(raw_value or "").strip()


def _collect_calculation_time_errors(selected_program_numbers: list[int] | None = None) -> list[str]:
    payloads = st.session_state.get("scenario_payloads", [])
    if not payloads:
        return []

    if selected_program_numbers is None:
        program_numbers = list(range(1, len(payloads) + 1))
    else:
        program_numbers = [int(item) for item in selected_program_numbers if 0 < int(item) <= len(payloads)]

    errors: list[str] = []
    for index in program_numbers:
        program_name = _program_display_name(index)

        inicio_key = _widget_key(index, "inicio_primeira_mistura")
        inicio_text = _current_time_text(inicio_key)
        if not inicio_text or _parse_time_text_input(inicio_text) is None:
            errors.append(f"{program_name}: corrija o horário de início da 1ª mistura.")

        usar_prazo = bool(st.session_state.get(_widget_key(index, "usar_prazo"), False))
        if usar_prazo:
            prazo_key = _widget_key(index, "prazo_limite_descarga")
            prazo_text = _current_time_text(prazo_key)
            if not prazo_text or _parse_time_text_input(prazo_text) is None:
                errors.append(f"{program_name}: corrija o horário do prazo de descarga.")

    return errors


def _sanitize_browser_device_id(raw_value: str | None) -> str:
    candidate = str(raw_value or "").strip()
    if not candidate:
        return ""
    return re.sub(r"[^a-zA-Z0-9_-]", "", candidate)[:80]


def _current_browser_device_id() -> str:
    try:
        raw_value = st.query_params.get(BROWSER_DEVICE_QUERY_KEY, "")
    except Exception:
        raw_value = ""
    return _sanitize_browser_device_id(raw_value)


def _saved_scenarios_path_for_device(device_id: str) -> Path:
    safe_id = _sanitize_browser_device_id(device_id) or "anon"
    return DEVICE_SCENARIOS_DIR / f"{safe_id}.json"


def _bootstrap_browser_device_identity() -> bool:
    device_id = _current_browser_device_id()
    if device_id:
        return True

    bootstrap_id = _sanitize_browser_device_id(
        st.session_state.get("_browser_device_bootstrap_id")
    )
    if not bootstrap_id:
        bootstrap_id = uuid4().hex
        st.session_state["_browser_device_bootstrap_id"] = bootstrap_id

    st.query_params[BROWSER_DEVICE_QUERY_KEY] = bootstrap_id
    st.rerun()
    return False


def _ensure_browser_device_identity() -> None:
    query_key_json = json.dumps(BROWSER_DEVICE_QUERY_KEY, ensure_ascii=False)
    storage_key_json = json.dumps(BROWSER_DEVICE_ID_STORAGE_KEY, ensure_ascii=False)
    components.html(
        f"""
        <script>
        const queryKey = {query_key_json};
        const storageKey = {storage_key_json};
        const reloadKey = `${{storageKey}}__reloaded`;
        const appWindow = window.parent || window;

        const buildDeviceId = () => {{
          if (appWindow.crypto?.randomUUID) return appWindow.crypto.randomUUID();
          return `pcnsa_${{Date.now()}}_${{Math.random().toString(36).slice(2, 10)}}`;
        }};

        const syncDeviceCookie = () => {{
          let storage = null;
          let session = null;
          try {{
            storage = appWindow.localStorage;
            session = appWindow.sessionStorage;
          }} catch (error) {{
            return;
          }}
          const url = new URL(appWindow.location.href);
          const urlDeviceId = (url.searchParams.get(queryKey) || '').trim();
          if (!urlDeviceId) {{
            return;
          }}

          const storedDeviceId = (storage.getItem(storageKey) || '').trim();
          if (!storedDeviceId) {{
            storage.setItem(storageKey, urlDeviceId);
            session.removeItem(reloadKey);
            return;
          }}

          if (storedDeviceId === urlDeviceId) {{
            session.removeItem(reloadKey);
            return;
          }}

          url.searchParams.set(queryKey, storedDeviceId);

          if (session.getItem(reloadKey) !== storedDeviceId) {{
            session.setItem(reloadKey, storedDeviceId);
            appWindow.location.replace(url.toString());
          }}
        }};

        setTimeout(syncDeviceCookie, 20);
        </script>
        """,
        height=0,
    )


def _resolve_scenario_name(record: dict) -> str:
    explicit_name = str(record.get("name", "")).strip()
    if explicit_name:
        return explicit_name

    label = str(record.get("label", "")).strip()
    if "_" in label:
        parts = label.split("_", 2)
        if len(parts) == 3 and parts[2].strip():
            return parts[2].strip()

    return "Cenário"


def _normalize_scenario_record(record: dict) -> dict:
    normalized = deepcopy(record)
    scenario_date = str(normalized.get("date") or date.today().isoformat())
    turno = str(normalized.get("turno") or "Diurno").strip() or "Diurno"
    name = _resolve_scenario_name(normalized)

    parsed_date = date.fromisoformat(scenario_date)
    normalized["date"] = parsed_date.isoformat()
    normalized["turno"] = turno
    normalized["name"] = name
    normalized["label"] = _build_scenario_label(name, parsed_date, turno)
    normalized["id"] = _build_scenario_id(name, parsed_date, turno)
    normalized["payloads"] = normalized.get("payloads") or []
    return normalized


def _parse_saved_scenarios_payload(raw_payload: str | None) -> list[dict]:
    raw_payload = str(raw_payload or "").strip()
    if not raw_payload:
        return []

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return []

    if not isinstance(payload, dict):
        return []

    raw_scenarios = payload.get("scenarios", [])
    if not isinstance(raw_scenarios, list):
        return []

    return [_normalize_scenario_record(item) for item in raw_scenarios if isinstance(item, dict)]


def _load_saved_scenarios() -> list[dict]:
    device_id = _current_browser_device_id()
    if not device_id:
        return st.session_state.get("_pending_saved_scenarios_without_device", [])

    scenarios_path = _saved_scenarios_path_for_device(device_id)
    if not scenarios_path.exists():
        return []

    try:
        raw_payload = scenarios_path.read_text(encoding="utf-8")
    except OSError:
        return []

    normalized_scenarios = _parse_saved_scenarios_payload(raw_payload)
    normalized_blob = json.dumps({"scenarios": normalized_scenarios}, ensure_ascii=False)
    if raw_payload and raw_payload != normalized_blob:
        _write_saved_scenarios(normalized_scenarios)
    return normalized_scenarios


def _write_saved_scenarios(scenarios: list[dict]) -> None:
    scenarios = [_normalize_scenario_record(item) for item in scenarios]
    device_id = _current_browser_device_id()
    if not device_id:
        st.session_state["_pending_saved_scenarios_without_device"] = scenarios
        return

    st.session_state["_pending_saved_scenarios_without_device"] = []
    DEVICE_SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    scenarios_path = _saved_scenarios_path_for_device(device_id)
    scenarios_path.write_text(
        json.dumps({"scenarios": scenarios}, ensure_ascii=False),
        encoding="utf-8",
    )


def _flush_pending_saved_scenarios_if_needed() -> None:
    pending = st.session_state.get("_pending_saved_scenarios_without_device", [])
    if not pending:
        return
    if not _current_browser_device_id():
        return
    _write_saved_scenarios(pending)


def _build_scenario_label(scenario_name: str, scenario_date: date, turno: str) -> str:
    nome_limpo = scenario_name.strip() or "Cenário"
    turno_limpo = turno.strip() or "Sem turno"
    return f"{scenario_date.strftime('%d-%m-%Y')}_{turno_limpo}_{nome_limpo}"


def _build_scenario_id(scenario_name: str, scenario_date: date, turno: str) -> str:
    return "::".join(
        [
            safe_identifier(scenario_name.strip() or "cenario"),
            scenario_date.isoformat(),
            safe_identifier(turno.strip() or "sem-turno"),
        ]
    )


def _turno_index(turno: str) -> int:
    try:
        return TURNO_OPTIONS.index(turno)
    except ValueError:
        return 0


def _normalize_duplicate_name(name: str) -> str:
    return re.sub(r"\s+\(cópia(?:\s+\d+)?\)$", "", name.strip(), flags=re.IGNORECASE)


def _next_program_copy_name(base_name: str, existing_names: list[str]) -> str:
    clean_name = _normalize_duplicate_name(base_name) or "Programação"
    if f"{clean_name} (cópia)" not in existing_names:
        return f"{clean_name} (cópia)"

    copy_number = 2
    while True:
        candidate = f"{clean_name} (cópia {copy_number})"
        if candidate not in existing_names:
            return candidate
        copy_number += 1


def _next_duplicate_identity(
    base_id: str,
    base_name: str,
    scenario_date: date,
    turno: str,
    scenarios: list[dict],
) -> tuple[str, str, str]:
    used_ids = {item.get("id", "") for item in scenarios}
    clean_name = _normalize_duplicate_name(base_name) or "Cenário"
    copy_number = 1
    while True:
        candidate_id = f"{base_id}::copia-{copy_number}"
        if candidate_id not in used_ids:
            candidate_name = f"{clean_name} (cópia {copy_number})"
            return (
                candidate_id,
                candidate_name,
                _build_scenario_label(candidate_name, scenario_date, turno),
            )
        copy_number += 1


def _next_scenario_copy_name(
    base_name: str,
    scenario_date: date,
    turno: str,
    scenarios: list[dict],
) -> str:
    clean_name = _normalize_duplicate_name(base_name) or "Cenário"
    used_labels = {
        item.get("label", "")
        for item in scenarios
        if item.get("date") == scenario_date.isoformat() and item.get("turno") == turno
    }

    first_candidate = f"{clean_name} (cópia)"
    if _build_scenario_label(first_candidate, scenario_date, turno) not in used_labels:
        return first_candidate

    copy_number = 1
    while True:
        candidate = f"{clean_name} (cópia {copy_number})"
        if _build_scenario_label(candidate, scenario_date, turno) not in used_labels:
            return candidate
        copy_number += 1


def _apply_payloads(
    payloads: list[dict],
    mode: str | None = None,
    max_total_bts: int | None = None,
    sequenciar_por_prioridade: bool | None = None,
    liberar_bt_compartilhada_parcialmente: bool | None = None,
) -> None:
    st.session_state.scenario_payloads = payloads

    for index, payload in enumerate(payloads, start=1):
        ciclo = payload.get("ciclo", {})
        restricoes = payload.get("restricoes", {})
        nome_programacao = (
            payload.get("elemento_frente")
            or payload.get("nome_programacao")
            or f"Frente {index}"
        )
        st.session_state[_widget_key(index, "nome_programacao")] = nome_programacao
        st.session_state[_widget_key(index, "local")] = payload.get("local", "")
        st.session_state[_widget_key(index, "elemento_frente")] = (
            payload.get("elemento_frente") or nome_programacao
        )
        st.session_state[_widget_key(index, "usina")] = payload.get("usina", "")
        st.session_state[_widget_key(index, "tipo_cimento")] = payload.get("tipo_cimento", "")
        st.session_state[_widget_key(index, "observacoes")] = payload.get("observacoes", "")
        st.session_state[_widget_key(index, "volume_total_m3")] = float(payload.get("volume_total_m3", 0.0))
        st.session_state[_widget_key(index, "capacidade_bt_m3")] = float(
            payload.get("capacidade_bt_m3", 0.0)
        )
        st.session_state[_widget_key(index, "numero_bts_fixo")] = int(
            payload.get("numero_bts_fixo") or 0
        )
        st.session_state[_widget_key(index, "inicio_primeira_mistura")] = parse_time_value(
            payload.get("inicio_primeira_mistura")
        ) or time(7, 0)
        _sync_time_text_state(
            _widget_key(index, "inicio_primeira_mistura"),
            st.session_state[_widget_key(index, "inicio_primeira_mistura")],
            force=True,
        )
        st.session_state[_widget_key(index, "inicio_primeira_mistura_offset_dias")] = max(
            0, int(payload.get("inicio_primeira_mistura_offset_dias", 0) or 0)
        )
        st.session_state[_widget_key(index, "prioridade")] = int(payload.get("prioridade", 0) or 0)
        st.session_state[_widget_key(index, "usar_prazo")] = payload.get("prazo_limite_descarga") is not None
        st.session_state[_widget_key(index, "prazo_limite_descarga")] = parse_time_value(
            payload.get("prazo_limite_descarga")
        ) or time(12, 0)
        _sync_time_text_state(
            _widget_key(index, "prazo_limite_descarga"),
            st.session_state[_widget_key(index, "prazo_limite_descarga")],
            force=True,
        )

        st.session_state[_widget_key(index, "mistura_min")] = float(ciclo.get("mistura_min", 0.0))
        st.session_state[_widget_key(index, "dosagem_min")] = float(ciclo.get("dosagem_min", 0.0))
        st.session_state[_widget_key(index, "ida_min")] = float(ciclo.get("ida_min", 0.0))
        st.session_state[_widget_key(index, "slump_min")] = float(ciclo.get("slump_min", 0.0))
        st.session_state[_widget_key(index, "descarga_min")] = float(ciclo.get("descarga_min", 0.0))
        st.session_state[_widget_key(index, "lavagem_min")] = float(ciclo.get("lavagem_min", 0.0))
        st.session_state[_widget_key(index, "volta_min")] = float(ciclo.get("volta_min", 0.0))

        st.session_state[_widget_key(index, "com_bomba")] = (
            "Com bomba" if restricoes.get("com_bomba", False) else "Sem bomba"
        )
        st.session_state[_widget_key(index, "max_bts_frente")] = int(
            restricoes.get("max_bts_frente", 1)
        )
        st.session_state[_widget_key(index, "max_bts_mistura")] = int(
            restricoes.get("max_bts_mistura", 1)
        )
        st.session_state[_widget_key(index, "max_bts_dosagem")] = int(
            restricoes.get("max_bts_dosagem", 1)
        )
        st.session_state[_widget_key(index, "existe_intervalo_entre_misturas")] = bool(
            restricoes.get("existe_intervalo_entre_misturas", False)
        )
        st.session_state[_widget_key(index, "intervalo_entre_misturas_min")] = float(
            restricoes.get("intervalo_entre_misturas_min", 0.0)
        )
        st.session_state[_widget_key(index, "existe_intervalo_maximo_entre_descargas")] = bool(
            restricoes.get("existe_intervalo_maximo_entre_descargas", False)
        )
        st.session_state[_widget_key(index, "intervalo_maximo_entre_descargas_min")] = float(
            restricoes.get("intervalo_maximo_entre_descargas_min", 0.0)
        )
        st.session_state[_widget_key(index, "ultima_viagem_parcial_proporcional")] = bool(
            restricoes.get("ultima_viagem_parcial_proporcional", True)
        )
        st.session_state[_widget_key(index, "permitir_primeira_viagem_customizada")] = bool(
            restricoes.get("permitir_primeira_viagem_customizada", False)
        )
        st.session_state[_widget_key(index, "volume_primeira_viagem_m3")] = float(
            restricoes.get("volume_primeira_viagem_m3") or 0.0
        )
        st.session_state[_widget_key(index, "alocacao_bts")] = restricoes.get(
            "alocacao_bts",
            "dedicadas",
        )

    if mode is not None:
        st.session_state.calc_mode = mode
    if max_total_bts is not None:
        st.session_state.max_total_bts = int(max_total_bts)
    if sequenciar_por_prioridade is not None:
        st.session_state.sequenciar_por_prioridade = bool(sequenciar_por_prioridade)
    if liberar_bt_compartilhada_parcialmente is not None:
        st.session_state.liberar_bt_compartilhada_parcialmente = bool(
            liberar_bt_compartilhada_parcialmente
        )


def _ensure_defaults(index: int, payload: dict) -> None:
    if _widget_key(index, "nome_programacao") in st.session_state:
        return
    _apply_payloads(st.session_state.scenario_payloads)


def _program_widgets_ready(index: int) -> bool:
    required_suffixes = [
        "nome_programacao",
        "elemento_frente",
        "local",
        "usina",
        "observacoes",
        "volume_total_m3",
        "capacidade_bt_m3",
        "numero_bts_fixo",
        "inicio_primeira_mistura",
        "inicio_primeira_mistura_offset_dias",
        "prioridade",
        "usar_prazo",
        "prazo_limite_descarga",
        "mistura_min",
        "dosagem_min",
        "ida_min",
        "slump_min",
        "descarga_min",
        "lavagem_min",
        "volta_min",
        "com_bomba",
        "max_bts_frente",
        "max_bts_mistura",
        "max_bts_dosagem",
        "existe_intervalo_entre_misturas",
        "intervalo_entre_misturas_min",
        "existe_intervalo_maximo_entre_descargas",
        "intervalo_maximo_entre_descargas_min",
        "ultima_viagem_parcial_proporcional",
        "permitir_primeira_viagem_customizada",
        "volume_primeira_viagem_m3",
        "alocacao_bts",
    ]
    return all(_widget_key(index, suffix) in st.session_state for suffix in required_suffixes)


def _snapshot_payloads_from_state() -> list[dict]:
    payloads = []
    for index, payload in enumerate(st.session_state.scenario_payloads, start=1):
        if _program_widgets_ready(index):
            payloads.append(_read_payload_from_widgets(index))
        else:
            payloads.append(payload)
    return payloads


def _set_current_scenario_metadata(scenario_date: date, turno: str, scenario_id: str | None = None) -> None:
    st.session_state.current_scenario_date = scenario_date
    st.session_state.current_scenario_turno = turno
    st.session_state.current_scenario_id = scenario_id or ""


def _build_current_scenario_record() -> dict:
    payloads = _snapshot_payloads_from_state()
    scenario_name = st.session_state.get("current_scenario_name", "").strip()
    scenario_date = st.session_state.current_scenario_date
    turno = st.session_state.current_scenario_turno.strip()
    if not scenario_name:
        raise ValueError("Informe o nome do cenário antes de continuar.")
    if not turno:
        raise ValueError("Informe o turno do cenário antes de salvar.")
    current_label = _current_scenario_label()
    scenario_id = _build_scenario_id(
        scenario_name,
        scenario_date,
        turno,
    )
    return {
        "id": scenario_id,
        "name": scenario_name,
        "label": current_label,
        "date": scenario_date.isoformat(),
        "turno": turno,
        "calc_mode": st.session_state.calc_mode,
        "max_total_bts": int(st.session_state.max_total_bts),
        "sequenciar_por_prioridade": bool(st.session_state.sequenciar_por_prioridade),
        "liberar_bt_compartilhada_parcialmente": bool(
            st.session_state.liberar_bt_compartilhada_parcialmente
        ),
        "payloads": payloads,
    }


def _scenario_record_signature(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)


def _reset_calculation_program_selection() -> None:
    st.session_state.calc_selected_programs = []
    st.session_state.calc_selected_programs_total = 0
    st.session_state.pop("calc_selected_programs_widget", None)


def _store_calculation_program_selection_from_widget() -> None:
    raw_selection = st.session_state.get("calc_selected_programs_widget", [])
    normalized: list[int] = []
    total_programs = int(st.session_state.get("calc_selected_programs_total", 0) or 0)
    for item in raw_selection:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= value <= total_programs and value not in normalized:
            normalized.append(value)
    st.session_state.calc_selected_programs = normalized


def _sync_calculation_program_selection(total_programs: int) -> list[int]:
    previous_total = int(st.session_state.get("calc_selected_programs_total", 0) or 0)
    current_selection = st.session_state.get("calc_selected_programs", [])
    normalized = []
    for item in current_selection:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= value <= total_programs and value not in normalized:
            normalized.append(value)

    if (
        previous_total > 0
        and total_programs > previous_total
        and normalized == list(range(1, previous_total + 1))
    ):
        normalized = list(range(1, total_programs + 1))

    if total_programs > 0 and not normalized:
        normalized = list(range(1, total_programs + 1))

    st.session_state.calc_selected_programs = normalized
    st.session_state.calc_selected_programs_total = total_programs
    widget_selection = st.session_state.get("calc_selected_programs_widget")
    if widget_selection is None or [int(item) for item in widget_selection if str(item).isdigit()] != normalized:
        st.session_state["calc_selected_programs_widget"] = normalized.copy()
    return normalized


def _current_calculation_signature() -> str:
    try:
        payloads = _snapshot_payloads_from_state()
    except Exception:
        return ""
    envelope = {
        "version": CALCULATION_SIGNATURE_VERSION,
        "date": st.session_state.get("current_scenario_date"),
        "turno": st.session_state.get("current_scenario_turno", ""),
        "name": st.session_state.get("current_scenario_name", "").strip(),
        "calc_mode": st.session_state.get("calc_mode", "fixo"),
        "max_total_bts": int(st.session_state.get("max_total_bts", 12)),
        "sequenciar_por_prioridade": bool(st.session_state.get("sequenciar_por_prioridade", False)),
        "liberar_bt_compartilhada_parcialmente": bool(
            st.session_state.get("liberar_bt_compartilhada_parcialmente", False)
        ),
        "selected_programs": list(st.session_state.get("calc_selected_programs", [])),
        "payloads": payloads,
    }
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True, default=str)


def _invalidate_stale_result_if_needed() -> None:
    if st.session_state.get("resultado") is None:
        return
    current_signature = _current_calculation_signature()
    last_signature = st.session_state.get("last_calculated_signature", "")
    if current_signature and current_signature != last_signature:
        st.session_state.resultado = None
        st.session_state.resultado_reprogramado = None
        st.session_state.reprogramacao_meta = None


def _has_synced_base_result() -> bool:
    if st.session_state.get("resultado") is None:
        return False
    current_signature = _current_calculation_signature()
    last_signature = st.session_state.get("last_calculated_signature", "")
    return bool(current_signature and last_signature and current_signature == last_signature)


def _sync_reprogramming_visibility() -> None:
    if _has_synced_base_result():
        return
    st.session_state.show_reprogramming_section = False
    st.session_state.resultado_reprogramado = None
    st.session_state.reprogramacao_meta = None


def _reset_delete_confirmation_state() -> None:
    st.session_state.confirm_delete_scenario = False
    st.session_state.delete_target_scenario_id = ""
    st.session_state.delete_target_scenario_label = ""
    st.session_state.delete_target_previous_scenario_id = ""
    st.session_state.delete_target_scenario_date = None
    st.session_state.delete_target_scenario_turno = ""
    st.session_state.delete_target_scenario_name = ""
    st.session_state.pending_delete_preview_record = None


def _apply_saved_scenario(record: dict) -> None:
    record = _normalize_scenario_record(record)
    _reset_calculation_program_selection()
    _apply_payloads(
        record.get("payloads") or [_default_payload(1)],
        mode=record.get("calc_mode", "fixo"),
        max_total_bts=record.get("max_total_bts", 12),
        sequenciar_por_prioridade=record.get("sequenciar_por_prioridade", False),
        liberar_bt_compartilhada_parcialmente=record.get(
            "liberar_bt_compartilhada_parcialmente", False
        ),
    )
    st.session_state.pending_focus_program_index = 0
    st.session_state.resultado = None
    st.session_state.resultado_reprogramado = None
    st.session_state.reprogramacao_meta = None
    _set_current_scenario_metadata(
        scenario_date=date.fromisoformat(record.get("date", date.today().isoformat())),
        turno=record.get("turno", "Diurno"),
        scenario_id=record.get("id"),
    )
    st.session_state.current_scenario_name = (record.get("name") or "").strip() or "Cenário"
    st.session_state.selected_saved_scenario_id = record.get("id", "")
    st.session_state.last_saved_scenario_signature = _scenario_record_signature(record)
    _reset_delete_confirmation_state()
    st.session_state.current_page = "planejamento"


def _save_current_scenario() -> str:
    record = _build_current_scenario_record()
    scenarios = _load_saved_scenarios()
    previous_id = st.session_state.get("current_scenario_id", "").strip()
    current_record_exists = any(item.get("id") == previous_id for item in scenarios) if previous_id else False
    if previous_id and previous_id != record["id"]:
        scenarios = [item for item in scenarios if item.get("id") != previous_id]

    target_id_exists = any(item.get("id") == record["id"] for item in scenarios)
    if target_id_exists and (not current_record_exists or previous_id != record["id"]):
        record["id"], record["name"], record["label"] = _next_duplicate_identity(
            record["id"],
            record["name"],
            date.fromisoformat(record["date"]),
            record["turno"],
            scenarios,
        )
    updated = False
    for index, item in enumerate(scenarios):
        if item.get("id") == record["id"]:
            scenarios[index] = record
            updated = True
            break
    if not updated:
        scenarios.append(record)
    scenarios.sort(key=lambda item: (item.get("date", ""), item.get("turno", ""), item.get("label", "")))
    _write_saved_scenarios(scenarios)
    st.session_state.current_scenario_id = record["id"]
    st.session_state.selected_saved_scenario_id = record["id"]
    st.session_state.last_saved_scenario_signature = _scenario_record_signature(record)
    return record["id"]


def _autosave_current_scenario_if_needed() -> None:
    if st.session_state.get("current_page") != "planejamento":
        return
    if not _has_active_scenario():
        return
    if st.session_state.get("confirm_delete_scenario"):
        return

    try:
        record = _build_current_scenario_record()
    except ValueError:
        return

    signature = _scenario_record_signature(record)
    if signature == st.session_state.get("last_saved_scenario_signature", ""):
        return

    _save_current_scenario()


def _create_new_scenario() -> None:
    scenario_date = st.session_state.get("current_scenario_date", date.today())
    turno = st.session_state.get("current_scenario_turno", "Diurno")
    scenario_name = st.session_state.get("current_scenario_name", "").strip()
    if not scenario_name:
        raise ValueError("Informe o nome do cenário para criar a programação.")
    _apply_payloads(
        [_default_payload(1)],
        mode="fixo",
        max_total_bts=12,
        sequenciar_por_prioridade=False,
        liberar_bt_compartilhada_parcialmente=False,
    )
    _reset_calculation_program_selection()
    st.session_state.pending_focus_program_index = 0
    _set_current_scenario_metadata(scenario_date, turno, "")
    st.session_state.current_scenario_name = scenario_name
    saved_id = _save_current_scenario()
    st.session_state.selected_saved_scenario_id = saved_id
    st.session_state.resultado = None
    st.session_state.resultado_reprogramado = None
    st.session_state.reprogramacao_meta = None
    _reset_delete_confirmation_state()
    st.session_state.current_page = "planejamento"
    st.session_state.toast_message = "Cenário criado com sucesso."


def _clear_active_scenario() -> None:
    st.session_state.scenario_payloads = []
    st.session_state.resultado = None
    st.session_state.resultado_reprogramado = None
    st.session_state.reprogramacao_meta = None
    st.session_state.current_scenario_id = ""
    st.session_state.current_scenario_name = ""
    st.session_state.selected_saved_scenario_id = ""
    st.session_state.last_saved_scenario_signature = ""
    st.session_state.pending_focus_program_index = None
    _reset_calculation_program_selection()
    _reset_delete_confirmation_state()
    st.session_state.current_page = "cenario"


def _duplicate_saved_scenario(record: dict) -> None:
    scenarios = _load_saved_scenarios()
    scenario_date = date.fromisoformat(record.get("date", date.today().isoformat()))
    turno = record.get("turno", "Diurno")
    _reset_calculation_program_selection()
    _apply_payloads(
        record.get("payloads") or [_default_payload(1)],
        mode=record.get("calc_mode", "fixo"),
        max_total_bts=record.get("max_total_bts", 12),
        sequenciar_por_prioridade=record.get("sequenciar_por_prioridade", False),
        liberar_bt_compartilhada_parcialmente=record.get(
            "liberar_bt_compartilhada_parcialmente", False
        ),
    )
    st.session_state.pending_focus_program_index = 0
    _set_current_scenario_metadata(
        scenario_date=scenario_date,
        turno=turno,
        scenario_id="",
    )
    base_name = (record.get("name") or "").strip() or "Cenário"
    st.session_state.current_scenario_name = _next_scenario_copy_name(
        base_name,
        scenario_date,
        turno,
        scenarios,
    )
    saved_id = _save_current_scenario()
    st.session_state.selected_saved_scenario_id = saved_id
    st.session_state.resultado = None
    st.session_state.resultado_reprogramado = None
    st.session_state.reprogramacao_meta = None
    _reset_delete_confirmation_state()
    st.session_state.current_page = "planejamento"
    st.session_state.toast_message = (
        "Cenário duplicado. Ajuste os dados e salve para criar uma nova simulação."
    )


def _import_scenario_record(record: dict) -> None:
    _reset_calculation_program_selection()
    _apply_payloads(
        record.get("payloads") or [_default_payload(1)],
        mode=record.get("calc_mode", "fixo"),
        max_total_bts=record.get("max_total_bts", 12),
        sequenciar_por_prioridade=record.get("sequenciar_por_prioridade", False),
        liberar_bt_compartilhada_parcialmente=record.get(
            "liberar_bt_compartilhada_parcialmente", False
        ),
    )
    st.session_state.pending_focus_program_index = 0
    _set_current_scenario_metadata(
        scenario_date=date.fromisoformat(record.get("date", date.today().isoformat())),
        turno=record.get("turno", "Diurno"),
        scenario_id="",
    )
    st.session_state.current_scenario_name = (record.get("name") or "").strip() or "Cenário"
    saved_id = _save_current_scenario()
    st.session_state.selected_saved_scenario_id = saved_id
    st.session_state.resultado = None
    st.session_state.resultado_reprogramado = None
    st.session_state.reprogramacao_meta = None
    _reset_delete_confirmation_state()
    st.session_state.current_page = "planejamento"
    st.session_state.toast_message = "Cenário importado com sucesso."


def _run_current_calculation(selected_programs: list[int] | None = None):
    available_programs = list(range(1, len(st.session_state.scenario_payloads) + 1))
    if not available_programs:
        raise ValueError("Cadastre ao menos uma programação para calcular.")

    _sync_calculation_program_selection(len(available_programs))
    if selected_programs is None:
        selected_programs = [
            int(item)
            for item in st.session_state.get("calc_selected_programs", available_programs)
            if int(item) in available_programs
        ]
    else:
        selected_programs = [int(item) for item in selected_programs if int(item) in available_programs]

    if not selected_programs:
        raise ValueError("Selecione ao menos uma programação para calcular.")

    concretagens = _build_concretagens_from_form(selected_programs)
    if st.session_state.calc_mode == "automatico":
        resultado = calcular_dimensionamento_minimo(
            concretagens,
            base_date=st.session_state.current_scenario_date,
            max_total_bts=int(st.session_state.max_total_bts),
            sequenciar_por_prioridade=bool(st.session_state.sequenciar_por_prioridade),
            liberar_bt_compartilhada_parcialmente=bool(
                st.session_state.liberar_bt_compartilhada_parcialmente
            ),
        )
    else:
        resultado = simular_ciclo_bt(
            concretagens,
            base_date=st.session_state.current_scenario_date,
            sequenciar_por_prioridade=bool(st.session_state.sequenciar_por_prioridade),
            liberar_bt_compartilhada_parcialmente=bool(
                st.session_state.liberar_bt_compartilhada_parcialmente
            ),
        )

    st.session_state.resultado = resultado
    st.session_state.last_calculated_signature = _current_calculation_signature()
    st.session_state.show_reprogramming_section = False
    st.session_state.resultado_reprogramado = None
    st.session_state.reprogramacao_meta = None
    st.session_state["base_result_default_tab"] = "Gantt operacional"
    return resultado


def _delete_scenario_by_id(scenario_id: str) -> None:
    target_id = scenario_id.strip()
    if target_id:
        scenarios = _load_saved_scenarios()
        scenarios = [item for item in scenarios if item.get("id") != target_id]
        _write_saved_scenarios(scenarios)
    _clear_active_scenario()
    st.session_state.toast_message = "Cenário excluído com sucesso."


def _has_active_scenario() -> bool:
    return bool(st.session_state.get("scenario_payloads"))


def _queue_new_scenario() -> None:
    st.session_state.pending_scenario_action = {"type": "new"}


def _queue_load_scenario(scenario_id: str) -> None:
    st.session_state.pending_scenario_action = {"type": "load", "id": scenario_id}


def _queue_duplicate_scenario(scenario_id: str) -> None:
    st.session_state.pending_scenario_action = {"type": "duplicate", "id": scenario_id}


def _queue_import_scenario(record: dict, *, auto_calculate: bool = False) -> None:
    st.session_state.pending_scenario_action = {
        "type": "import",
        "record": record,
        "auto_calculate": bool(auto_calculate),
    }


def _queue_delete_scenario(scenario_id: str) -> None:
    st.session_state.pending_scenario_action = {"type": "delete", "id": scenario_id}


def _queue_delete_scenario_targets(target_ids: list[str]) -> None:
    st.session_state.pending_scenario_action = {"type": "delete_targets", "ids": target_ids}


def _queue_duplicate_program(index: int) -> None:
    st.session_state.pending_program_action = {"type": "duplicate", "index": int(index)}


def _queue_remove_program(index: int) -> None:
    st.session_state.pending_program_action = {"type": "remove", "index": int(index)}


def _queue_move_program(index: int, direction: str) -> None:
    st.session_state.pending_program_action = {
        "type": "move",
        "index": int(index),
        "direction": direction,
    }


def _process_pending_scenario_action() -> None:
    pending = st.session_state.pop("pending_scenario_action", None)
    if not pending:
        return

    action_type = pending.get("type")
    if action_type == "new":
        _create_new_scenario()
        return

    if action_type == "load":
        scenario_id = pending.get("id", "")
        if not scenario_id:
            return
        record = next(
            (item for item in _load_saved_scenarios() if item.get("id") == scenario_id),
            None,
        )
        if record is not None:
            _apply_saved_scenario(record)
        return

    if action_type == "duplicate":
        scenario_id = pending.get("id", "")
        if not scenario_id:
            return
        record = next(
            (item for item in _load_saved_scenarios() if item.get("id") == scenario_id),
            None,
        )
        if record is not None:
            _duplicate_saved_scenario(record)
        return

    if action_type == "import":
        record = pending.get("record")
        if record is not None:
            _import_scenario_record(record)
            if bool(pending.get("auto_calculate", False)):
                _run_current_calculation()
                st.session_state.toast_message = (
                    "Simulação exemplo carregada e calculada com sucesso."
                )
        return

    if action_type == "delete":
        scenario_id = pending.get("id", "")
        if scenario_id:
            _delete_scenario_by_id(scenario_id)
        return

    if action_type == "delete_targets":
        target_ids = [item.strip() for item in pending.get("ids", []) if str(item).strip()]
        if target_ids:
            scenarios = _load_saved_scenarios()
            scenarios = [item for item in scenarios if item.get("id") not in set(target_ids)]
            _write_saved_scenarios(scenarios)
            _clear_active_scenario()
            st.session_state.toast_message = "Cenário excluído com sucesso."
        return


def _process_pending_program_action() -> None:
    pending = st.session_state.pop("pending_program_action", None)
    if not pending:
        return

    action_type = pending.get("type")
    index = int(pending.get("index", 0))
    payloads = _snapshot_payloads_from_state()
    if not payloads:
        return
    index = max(0, min(index, len(payloads) - 1))

    if action_type == "duplicate":
        duplicated_payload = deepcopy(payloads[index])
        existing_names = [
            _current_program_name(item_index, item)
            for item_index, item in enumerate(payloads, start=1)
        ]
        duplicated_name = _next_program_copy_name(
            _current_program_name(index + 1, duplicated_payload),
            existing_names,
        )
        duplicated_payload["nome_programacao"] = duplicated_name
        duplicated_payload["elemento_frente"] = duplicated_name
        payloads.insert(index + 1, duplicated_payload)
        _apply_payloads(payloads)
        st.session_state.pending_focus_program_index = index + 1
        return

    if action_type == "remove":
        if len(payloads) <= 1:
            return
        updated_payloads = payloads[:index] + payloads[index + 1 :]
        _apply_payloads(updated_payloads)
        next_index = min(index, len(updated_payloads) - 1)
        st.session_state.pending_focus_program_index = max(0, next_index)
        return

    if action_type == "move":
        direction = str(pending.get("direction", "")).strip().lower()
        if direction not in {"left", "right"}:
            return
        target_index = index - 1 if direction == "left" else index + 1
        if target_index < 0 or target_index >= len(payloads):
            st.session_state.pending_focus_program_index = index
            return
        payloads[index], payloads[target_index] = payloads[target_index], payloads[index]
        _apply_payloads(payloads)
        st.session_state.pending_focus_program_index = target_index
        return


def _process_pending_selected_scenario() -> None:
    selected_id = st.session_state.pop("pending_selected_saved_scenario_id", None)
    if selected_id is not None:
        st.session_state.selected_saved_scenario_id = selected_id


def _process_pending_delete_preview() -> None:
    pending = st.session_state.pop("pending_delete_preview_record", None)
    if not pending:
        return

    record = pending.get("record") or {}
    if not record:
        return

    previous_id = str(pending.get("previous_id", "")).strip()
    scenario_id = str(record.get("id", "")).strip()
    scenario_date = date.fromisoformat(str(record.get("date", date.today().isoformat())))
    turno = str(record.get("turno", "Diurno")).strip() or "Diurno"
    scenario_name = str(record.get("name", "")).strip() or "Cenário"
    scenario_label = str(record.get("label", "")).strip() or _build_scenario_label(
        scenario_name,
        scenario_date,
        turno,
    )

    st.session_state.current_scenario_id = scenario_id
    st.session_state.current_scenario_date = scenario_date
    st.session_state.current_scenario_turno = turno
    st.session_state.current_scenario_name = scenario_name
    st.session_state.selected_saved_scenario_id = scenario_id
    st.session_state.delete_target_scenario_id = scenario_id
    st.session_state.delete_target_previous_scenario_id = previous_id
    st.session_state.delete_target_scenario_label = scenario_label
    st.session_state.delete_target_scenario_date = scenario_date
    st.session_state.delete_target_scenario_turno = turno
    st.session_state.delete_target_scenario_name = scenario_name
    st.session_state.scenario_form_synced_from_active = True
    st.session_state.confirm_delete_scenario = True


def _sync_scenario_form_from_active(saved_scenarios: list[dict]) -> None:
    if st.session_state.get("scenario_form_synced_from_active", False):
        return

    current_id = st.session_state.get("current_scenario_id", "").strip()
    if not current_id:
        return

    record = next((item for item in saved_scenarios if item.get("id") == current_id), None)
    if record is None:
        return

    if not st.session_state.get("current_scenario_name", "").strip():
        st.session_state.current_scenario_name = (record.get("name") or "").strip()
    if not st.session_state.get("selected_saved_scenario_id", "").strip():
        st.session_state.selected_saved_scenario_id = current_id

    st.session_state.current_scenario_date = date.fromisoformat(
        record.get("date", date.today().isoformat())
    )
    st.session_state.current_scenario_turno = record.get("turno", "Diurno")
    st.session_state.scenario_form_synced_from_active = True


def _go_to_page(page_name: str) -> None:
    st.session_state.current_page = page_name
    if page_name == "cenario":
        st.session_state.current_scenario_date = date.today()
        st.session_state.current_scenario_turno = "Diurno"
        st.session_state.current_scenario_name = ""
        st.session_state.resultado_reprogramado = None
        st.session_state.reprogramacao_meta = None
        st.session_state.selected_saved_scenario_id = ""
        st.session_state.scenario_form_synced_from_active = True
        _reset_delete_confirmation_state()
        st.query_params["programa"] = str(st.session_state.get("active_program_index", 0))


def _sync_active_program_from_query(total_programs: int) -> None:
    raw_value = st.query_params.get("programa")
    try:
        index = int(raw_value) if raw_value is not None else 0
    except (TypeError, ValueError):
        index = 0
    index = max(0, min(index, max(total_programs - 1, 0)))
    st.session_state.active_program_index = index
    if raw_value != str(index):
        st.query_params["programa"] = str(index)


def _render_program_tab_tracking() -> None:
    components.html(
        """
        <script>
        const storageKey = "codex_active_program_index";
        const findProgramTablist = () => {{
          const anchors = Array.from(window.parent.document.querySelectorAll('.codex-program-tabs-anchor'));
          const anchor = anchors.length ? anchors[anchors.length - 1] : null;
          if (!anchor) return null;
          const tablists = Array.from(window.parent.document.querySelectorAll('[role="tablist"]'));
          return tablists.find((tablist) =>
            Boolean(anchor.compareDocumentPosition(tablist) & Node.DOCUMENT_POSITION_FOLLOWING)
          );
        }};

        const bindProgramTabs = () => {{
          const tablist = findProgramTablist();
          if (!tablist) return;
          const buttons = tablist.querySelectorAll('button[role="tab"]');
          buttons.forEach((button, index) => {{
            if (button.dataset.programTrackingBound === "true") return;
            button.dataset.programTrackingBound = "true";
            button.addEventListener("click", () => {{
              const parentWindow = window.parent;
              try {{
                parentWindow.sessionStorage.setItem(storageKey, String(index));
              }} catch (e) {{}}
              const url = new URL(parentWindow.location.href);
              if (url.searchParams.get("programa") !== String(index)) {{
                url.searchParams.set("programa", String(index));
                parentWindow.history.replaceState({{}}, "", url.toString());
              }}
            }});
          }});
        }};

        setTimeout(bindProgramTabs, 80);
        </script>
        """,
        height=0,
    )


def _render_active_program_focus() -> None:
    target_index = st.session_state.get("pending_focus_program_index")
    force_target_index = target_index is not None
    if target_index is None:
        target_index = st.session_state.get("active_program_index", 0)
    target_index = int(target_index or 0)

    target_index = max(0, min(target_index, len(st.session_state.scenario_payloads) - 1))
    st.session_state.active_program_index = target_index
    st.query_params["programa"] = str(target_index)
    components.html(
        f"""
        <script>
        const targetIndex = {int(target_index)};
        const forceTargetIndex = {str(force_target_index).lower()};
        const storageKey = "codex_active_program_index";
        const findProgramTablist = () => {{
          const anchors = Array.from(window.parent.document.querySelectorAll('.codex-program-tabs-anchor'));
          const anchor = anchors.length ? anchors[anchors.length - 1] : null;
          if (!anchor) return null;
          const tablists = Array.from(window.parent.document.querySelectorAll('[role="tablist"]'));
          return tablists.find((tablist) =>
            Boolean(anchor.compareDocumentPosition(tablist) & Node.DOCUMENT_POSITION_FOLLOWING)
          );
        }};

        const resolveTargetIndex = () => {{
          const parentWindow = window.parent;
          let resolved = targetIndex;
          if (forceTargetIndex) {{
            try {{
              parentWindow.sessionStorage.setItem(storageKey, String(targetIndex));
            }} catch (e) {{}}
          }} else {{
            try {{
              const stored = parentWindow.sessionStorage.getItem(storageKey);
              if (stored !== null && !Number.isNaN(Number(stored))) {{
                resolved = Number(stored);
              }}
            }} catch (e) {{}}
          }}
          const url = new URL(parentWindow.location.href);
          if (url.searchParams.get("programa") !== String(resolved)) {{
            url.searchParams.set("programa", String(resolved));
            parentWindow.history.replaceState({{}}, "", url.toString());
          }}
          return resolved;
        }};

        const focusProgramTab = () => {{
          const tablist = findProgramTablist();
          if (!tablist) return;
          const buttons = tablist.querySelectorAll('button[role="tab"]');
          const resolvedTargetIndex = Math.max(0, Math.min(resolveTargetIndex(), buttons.length - 1));
          const target = buttons[resolvedTargetIndex];
          if (!target) return;
          if (target.getAttribute("aria-selected") !== "true") target.click();
        }};

        let attempts = 0;
        const intervalId = setInterval(() => {{
          attempts += 1;
          focusProgramTab();
          const tablist = findProgramTablist();
          const buttons = tablist ? tablist.querySelectorAll('button[role="tab"]') : [];
          const resolvedTargetIndex = buttons.length
            ? Math.max(0, Math.min(resolveTargetIndex(), buttons.length - 1))
            : 0;
          const target = buttons[resolvedTargetIndex];
          if ((target && target.getAttribute("aria-selected") === "true") || attempts >= 12) {{
            clearInterval(intervalId);
          }}
        }}, 120);
        </script>
        """,
        height=0,
    )
    st.session_state.pending_focus_program_index = None


def _read_payload_from_widgets(index: int) -> dict:
    usar_prazo = st.session_state[_widget_key(index, "usar_prazo")]
    primeira_custom = st.session_state[_widget_key(index, "permitir_primeira_viagem_customizada")]
    elemento_frente = st.session_state[_widget_key(index, "elemento_frente")].strip()
    nome_programacao = elemento_frente or f"Programação {index}"
    return {
        "id": f"concretagem-{index}",
        "nome_programacao": nome_programacao,
        "local": st.session_state[_widget_key(index, "local")],
        "elemento_frente": elemento_frente,
        "usina": st.session_state[_widget_key(index, "usina")],
        "tipo_cimento": st.session_state[_widget_key(index, "tipo_cimento")],
        "observacoes": st.session_state[_widget_key(index, "observacoes")],
        "volume_total_m3": st.session_state[_widget_key(index, "volume_total_m3")],
        "capacidade_bt_m3": st.session_state[_widget_key(index, "capacidade_bt_m3")],
        "numero_bts_fixo": st.session_state[_widget_key(index, "numero_bts_fixo")],
        "inicio_primeira_mistura": st.session_state[_widget_key(index, "inicio_primeira_mistura")].strftime(
            "%H:%M"
        ),
        "inicio_primeira_mistura_offset_dias": st.session_state[
            _widget_key(index, "inicio_primeira_mistura_offset_dias")
        ],
        "prioridade": st.session_state[_widget_key(index, "prioridade")],
        "prazo_limite_descarga": (
            st.session_state[_widget_key(index, "prazo_limite_descarga")].strftime("%H:%M")
            if usar_prazo
            else None
        ),
        "ciclo": {
            "mistura_min": st.session_state[_widget_key(index, "mistura_min")],
            "dosagem_min": st.session_state[_widget_key(index, "dosagem_min")],
            "ida_min": st.session_state[_widget_key(index, "ida_min")],
            "slump_min": st.session_state[_widget_key(index, "slump_min")],
            "descarga_min": st.session_state[_widget_key(index, "descarga_min")],
            "lavagem_min": st.session_state[_widget_key(index, "lavagem_min")],
            "volta_min": st.session_state[_widget_key(index, "volta_min")],
        },
        "restricoes": {
            "com_bomba": st.session_state[_widget_key(index, "com_bomba")] == "Com bomba",
            "max_bts_frente": st.session_state[_widget_key(index, "max_bts_frente")],
            "max_bts_mistura": st.session_state[_widget_key(index, "max_bts_mistura")],
            "max_bts_dosagem": st.session_state[_widget_key(index, "max_bts_dosagem")],
            "existe_intervalo_entre_misturas": st.session_state[
                _widget_key(index, "existe_intervalo_entre_misturas")
            ],
            "intervalo_entre_misturas_min": st.session_state[
                _widget_key(index, "intervalo_entre_misturas_min")
            ],
            "existe_intervalo_maximo_entre_descargas": st.session_state[
                _widget_key(index, "existe_intervalo_maximo_entre_descargas")
            ],
            "intervalo_maximo_entre_descargas_min": st.session_state[
                _widget_key(index, "intervalo_maximo_entre_descargas_min")
            ],
            "ultima_viagem_parcial_proporcional": st.session_state[
                _widget_key(index, "ultima_viagem_parcial_proporcional")
            ],
            "permitir_primeira_viagem_customizada": primeira_custom,
            "volume_primeira_viagem_m3": (
                st.session_state[_widget_key(index, "volume_primeira_viagem_m3")]
                if primeira_custom
                else None
            ),
            "alocacao_bts": st.session_state[_widget_key(index, "alocacao_bts")],
        },
    }


def _sync_program_name_from_element(index: int) -> None:
    elemento_frente = st.session_state.get(_widget_key(index, "elemento_frente"), "").strip()
    st.session_state[_widget_key(index, "nome_programacao")] = (
        elemento_frente or f"Programação {index}"
    )


def _sync_operation_mode(index: int) -> None:
    if st.session_state.get(_widget_key(index, "com_bomba")) == "Sem bomba":
        st.session_state[_widget_key(index, "max_bts_frente")] = 1


def _render_scenario_form(index: int, payload: dict) -> None:
    _ensure_defaults(index, payload)

    with st.expander("Identificação", expanded=True):
        id1, id2, id3 = st.columns([1.35, 1.0, 1.45])
        id1.text_input(
            "Elemento / frente",
            key=_widget_key(index, "elemento_frente"),
            on_change=_sync_program_name_from_element,
            args=(index,),
        )
        id2.text_input("Local", key=_widget_key(index, "local"))
        id3.text_input("Observações", key=_widget_key(index, "observacoes"))

    st.write("")

    with st.expander("Dados da concretagem", expanded=True):
        op1, op2, op3, op4, op5, op6, op7 = st.columns([1.05, 1.0, 1.0, 0.8, 0.8, 1.0, 0.9])
        op1.number_input(
            "Volume total (m³)",
            min_value=0.0,
            step=1.0,
            key=_widget_key(index, "volume_total_m3"),
        )
        op2.number_input(
            "Capacidade BT (m³)",
            min_value=0.0,
            step=0.5,
            key=_widget_key(index, "capacidade_bt_m3"),
        )
        _sync_time_text_state(
            _widget_key(index, "inicio_primeira_mistura"),
            st.session_state[_widget_key(index, "inicio_primeira_mistura")],
        )
        with op3:
            _render_time_text_input(
                "Início 1ª mistura",
                _widget_key(index, "inicio_primeira_mistura"),
                help_text="Digite no formato HH:MM.",
            )
        op4.selectbox(
            "Dia início",
            options=INICIO_DIA_OPTIONS,
            format_func=_format_inicio_offset_label,
            key=_widget_key(index, "inicio_primeira_mistura_offset_dias"),
            help="Use D para o dia-base do cenário, D+1 para o dia seguinte.",
        )
        op5.checkbox(
            "Usar prazo",
            key=_widget_key(index, "usar_prazo"),
        )
        _sync_time_text_state(
            _widget_key(index, "prazo_limite_descarga"),
            st.session_state[_widget_key(index, "prazo_limite_descarga")],
        )
        with op6:
            _render_time_text_input(
                "Prazo descarga",
                _widget_key(index, "prazo_limite_descarga"),
                disabled=not st.session_state[_widget_key(index, "usar_prazo")],
                help_text="Digite no formato HH:MM.",
            )
        op7.number_input(
            "Prioridade",
            min_value=0,
            step=1,
            key=_widget_key(index, "prioridade"),
            help="Use 0 quando a programação não precisar de prioridade no sequenciamento.",
        )

    st.write("")

    with st.expander("Configuração da operação", expanded=True):
        cfg1, cfg2, cfg3, cfg4, cfg5, cfg6 = st.columns([1.0, 0.9, 0.95, 1.0, 0.95, 1.0])
        cfg1.selectbox(
            "Operação",
            options=["Com bomba", "Sem bomba"],
            key=_widget_key(index, "com_bomba"),
            on_change=_sync_operation_mode,
            args=(index,),
        )
        com_bomba = st.session_state[_widget_key(index, "com_bomba")] == "Com bomba"
        cfg2.number_input(
            "BTs na bomba",
            min_value=1,
            step=1,
            key=_widget_key(index, "max_bts_frente"),
            disabled=not com_bomba,
            help="Quando a operação estiver sem bomba, este campo permanece desabilitado.",
        )
        cfg3.checkbox(
            "Controlar intervalo",
            key=_widget_key(index, "existe_intervalo_maximo_entre_descargas"),
            help="Ative quando quiser limitar o tempo máximo permitido entre uma descarga e a próxima.",
        )
        cfg4.number_input(
            "Intervalo máx. descargas (min)",
            min_value=0.0,
            step=1.0,
            key=_widget_key(index, "intervalo_maximo_entre_descargas_min"),
            disabled=not st.session_state[
                _widget_key(index, "existe_intervalo_maximo_entre_descargas")
            ],
        )
        cfg5.number_input(
            "BTs fixas",
            min_value=0,
            step=1,
            key=_widget_key(index, "numero_bts_fixo"),
        )
        cfg6.selectbox(
            "Alocação BTs",
            options=["dedicadas", "compartilhadas"],
            key=_widget_key(index, "alocacao_bts"),
        )

    st.write("")

    with st.expander("Configurações da usina", expanded=True):
        us1, us2, us3, us4, us5 = st.columns([1.5, 0.95, 0.95, 0.95, 1.05])
        us1.text_input("Usina responsável", key=_widget_key(index, "usina"))
        us2.number_input(
            "BTs mistura",
            min_value=1,
            step=1,
            key=_widget_key(index, "max_bts_mistura"),
            help="Quantidade máxima de BTs que podem estar simultaneamente na etapa de mistura.",
        )
        us3.number_input(
            "BTs dosagem",
            min_value=1,
            step=1,
            key=_widget_key(index, "max_bts_dosagem"),
            help="Quantidade máxima de BTs que podem estar simultaneamente na etapa de dosagem.",
        )
        us4.checkbox(
            "Intervalo entre misturas",
            key=_widget_key(index, "existe_intervalo_entre_misturas"),
            help="Ative para impor um espaçamento fixo entre o início de uma mistura e a próxima.",
        )
        us5.number_input(
            "Intervalo mistura (min)",
            min_value=0.0,
            step=1.0,
            key=_widget_key(index, "intervalo_entre_misturas_min"),
            disabled=not st.session_state[_widget_key(index, "existe_intervalo_entre_misturas")],
        )

    st.write("")

    with st.expander("Tempos do ciclo (minutos)", expanded=True):
        ciclo1, ciclo2, ciclo3, ciclo4, ciclo5, ciclo6, ciclo7 = st.columns(7)
        ciclo1.number_input("Mistura", min_value=0.0, step=1.0, key=_widget_key(index, "mistura_min"))
        ciclo2.number_input("Dosagem", min_value=0.0, step=1.0, key=_widget_key(index, "dosagem_min"))
        ciclo3.number_input("Ida", min_value=0.0, step=1.0, key=_widget_key(index, "ida_min"))
        ciclo4.number_input("Slump", min_value=0.0, step=1.0, key=_widget_key(index, "slump_min"))
        ciclo5.number_input("Descarga", min_value=0.0, step=1.0, key=_widget_key(index, "descarga_min"))
        ciclo6.number_input("Lavagem", min_value=0.0, step=1.0, key=_widget_key(index, "lavagem_min"))
        ciclo7.number_input("Volta", min_value=0.0, step=1.0, key=_widget_key(index, "volta_min"))

    st.write("")

    with st.expander("Configurações adicionais", expanded=False):
        add1, add2, add3 = st.columns([1.15, 1.15, 0.95])
        add1.checkbox(
            "Última viagem parcial proporcional",
            key=_widget_key(index, "ultima_viagem_parcial_proporcional"),
            help="Quando o volume final for menor que a capacidade da BT, ajusta a última viagem de forma proporcional ao ciclo.",
        )
        add2.checkbox(
            "Permitir 1ª viagem customizada",
            key=_widget_key(index, "permitir_primeira_viagem_customizada"),
            help="Use quando a primeira viagem precisar sair com um volume diferente do padrão das demais viagens.",
        )
        add3.number_input(
            "Volume 1ª viagem (m³)",
            min_value=0.0,
            step=0.5,
            key=_widget_key(index, "volume_primeira_viagem_m3"),
            disabled=not st.session_state[_widget_key(index, "permitir_primeira_viagem_customizada")],
        )


def _build_concretagens_from_form(selected_program_numbers: list[int] | None = None) -> list[Concretagem]:
    payloads = []
    for index, _payload in enumerate(st.session_state.scenario_payloads, start=1):
        payloads.append(_read_payload_from_widgets(index))
    st.session_state.scenario_payloads = payloads
    selected_set = {
        int(item)
        for item in (selected_program_numbers or [])
        if 1 <= int(item) <= len(payloads)
    }
    filtered_payloads = (
        [payload for index, payload in enumerate(payloads, start=1) if index in selected_set]
        if selected_set
        else payloads
    )
    return [
        Concretagem.from_dict(payload, ordem=index - 1)
        for index, payload in enumerate(filtered_payloads, start=1)
    ]


def _clone_concretagens(concretagens: list[Concretagem]) -> list[Concretagem]:
    return [
        Concretagem.from_dict(concretagem.to_dict(), ordem=index)
        for index, concretagem in enumerate(concretagens)
    ]


def _find_trip_for_reprogramming(resultado, concretagem_id: str, numero_viagem: int):
    viagem = next(
        (
            item
            for item in resultado.viagens
            if item.concretagem_id == concretagem_id and item.numero_viagem == numero_viagem
        ),
        None,
    )
    if viagem is None:
        raise ValueError("Não foi possível localizar a viagem informada para a reprogramação.")
    return viagem


def _reference_option_label(reference_type: str) -> str:
    boundary, etapa = reference_type.split("|", 1)
    prefix = "Início da" if boundary == "inicio" else "Fim da"
    return f"{prefix} {etapa}"


def _preserve_label_case(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return value
    return value[:1].upper() + value[1:]


def _trip_stage_options(resultado, concretagem_id: str, numero_viagem: int) -> list[str]:
    viagem = _find_trip_for_reprogramming(resultado, concretagem_id, numero_viagem)
    options: list[str] = []
    seen: set[str] = set()
    for etapa in viagem.etapas:
        etapa_nome = etapa.etapa
        if etapa_nome.startswith("Espera") or etapa_nome in seen:
            continue
        seen.add(etapa_nome)
        options.append(etapa_nome)
    if not options:
        raise ValueError("A viagem informada não possui etapas operacionais disponíveis.")
    return options


def _find_trip_reference_datetime(
    resultado,
    concretagem_id: str,
    numero_viagem: int,
    reference_type: str,
) -> datetime:
    viagem = _find_trip_for_reprogramming(resultado, concretagem_id, numero_viagem)
    boundary, etapa_nome = reference_type.split("|", 1)
    etapa = next((item for item in viagem.etapas if item.etapa == etapa_nome), None)
    if etapa is None:
        raise ValueError(f"A viagem informada não possui etapa de {etapa_nome.lower()} disponível.")
    return etapa.inicio if boundary == "inicio" else etapa.fim


def _apply_fixed_bt_counts(
    concretagens: list[Concretagem],
    bt_counts: dict[str, int],
) -> None:
    for concretagem in concretagens:
        concretagem.numero_bts_fixo = int(bt_counts.get(concretagem.grupo_bt, 1))


def _recalculate_reprogramming(
    base_resultado,
    concretagem_id: str,
    numero_viagem: int,
    reference_type: str,
    observed_datetime: datetime,
    execution_mode: str,
    max_total_bts: int,
    override_group_bt_count: int | None = None,
):
    concretagens = _clone_concretagens(base_resultado.concretagens)
    target = next(
        (concretagem for concretagem in concretagens if concretagem.id == concretagem_id),
        None,
    )
    if target is None:
        raise ValueError("Não foi possível localizar a programação selecionada.")

    planned_reference = _find_trip_reference_datetime(
        base_resultado,
        concretagem_id,
        numero_viagem,
        reference_type,
    )
    delta = observed_datetime - planned_reference
    novo_inicio = target.inicio_datetime(base_resultado.data_base) + delta
    target.inicio_primeira_mistura = novo_inicio.time()
    target.inicio_primeira_mistura_offset_dias = max(
        0, (novo_inicio.date() - base_resultado.data_base).days
    )

    should_force_fixed = execution_mode == "fixar_atual" or override_group_bt_count is not None
    if should_force_fixed:
        bt_counts = dict(base_resultado.bt_counts)
        if override_group_bt_count is not None:
            bt_counts[target.grupo_bt] = int(override_group_bt_count)
        _apply_fixed_bt_counts(concretagens, bt_counts)
        resultado = simular_ciclo_bt(
            concretagens,
            base_date=base_resultado.data_base,
            sequenciar_por_prioridade=bool(base_resultado.sequenciamento_prioridade_ativo),
            liberar_bt_compartilhada_parcialmente=bool(
                st.session_state.get("liberar_bt_compartilhada_parcialmente", False)
            ),
        )
    elif base_resultado.automatico:
        resultado = calcular_dimensionamento_minimo(
            concretagens,
            base_date=base_resultado.data_base,
            max_total_bts=max_total_bts,
            sequenciar_por_prioridade=bool(base_resultado.sequenciamento_prioridade_ativo),
            liberar_bt_compartilhada_parcialmente=bool(
                st.session_state.get("liberar_bt_compartilhada_parcialmente", False)
            ),
        )
    else:
        resultado = simular_ciclo_bt(
            concretagens,
            base_date=base_resultado.data_base,
            sequenciar_por_prioridade=bool(base_resultado.sequenciamento_prioridade_ativo),
            liberar_bt_compartilhada_parcialmente=bool(
                st.session_state.get("liberar_bt_compartilhada_parcialmente", False)
            ),
        )

    return resultado, {
        "programacao": target.nome_programacao,
        "numero_viagem": numero_viagem,
        "reference_type": reference_type,
        "reference_label": _reference_option_label(reference_type),
        "planned_reference": planned_reference,
        "observed_reference": observed_datetime,
        "delta_minutes": delta.total_seconds() / 60.0,
        "novo_inicio_primeira_mistura": novo_inicio,
        "execution_mode": execution_mode,
        "group_override": override_group_bt_count,
    }


def _render_reprogramming_section(base_resultado) -> None:
    with st.expander(
        "Seção 2A — Reprogramação por marco observado",
        expanded=bool(st.session_state.get("show_reprogramming_section", False)),
    ):
        st.markdown(
            "<div class='section-helper'>Use um marco real de início ou fim de qualquer etapa operacional de uma viagem para recalcular a programação e avaliar o impacto no restante do ciclo.</div>",
            unsafe_allow_html=True,
        )

        program_options = {item.id: item.nome_programacao for item in base_resultado.concretagens}
        selected_program_id = st.selectbox(
            "Programação para reprogramar",
            options=list(program_options.keys()),
            format_func=lambda item: program_options[item],
            key="reprog_program_id",
        )
        trip_options = sorted(
            {
                viagem.numero_viagem
                for viagem in base_resultado.viagens
                if viagem.concretagem_id == selected_program_id
            }
        )
        r1, r2, r3, r4 = st.columns([0.8, 0.7, 0.95, 1.05])
        selected_trip = r1.selectbox(
            "Viagem observada",
            options=trip_options,
            key="reprog_trip_number",
        )
        reference_boundary = r2.selectbox(
            "Marco",
            options=["inicio", "fim"],
            format_func=lambda item: "Início" if item == "inicio" else "Fim",
            key="reprog_reference_boundary",
        )
        stage_options = _trip_stage_options(
            base_resultado,
            selected_program_id,
            int(selected_trip),
        )
        reference_stage = r3.selectbox(
            "Etapa",
            options=stage_options,
            key="reprog_reference_stage",
        )
        reference_type = f"{reference_boundary}|{reference_stage}"
        execution_mode = r4.selectbox(
            "Modo da reprogramação",
            options=["manter_atual", "fixar_atual"],
            format_func=lambda item: (
                "Manter regra atual do cenário"
                if item == "manter_atual"
                else "Fixar BTs do cálculo atual"
            ),
            key="reprog_execution_mode",
            help=(
                "Escolha como o recálculo será feito depois do marco observado. "
                "'Manter regra atual do cenário' repete a lógica do cálculo-base. "
                "'Fixar BTs do cálculo atual' congela a frota usada no resultado-base."
            ),
        )
        r4.caption(
            (
                "Reroda o cenário com a mesma lógica do cálculo-base."
                if execution_mode == "manter_atual"
                else "Usa a mesma quantidade de BTs do cálculo-base para reprogramar."
            )
        )

        planned_reference = _find_trip_reference_datetime(
            base_resultado,
            selected_program_id,
            int(selected_trip),
            reference_type,
        )
        reprog_time_context = (
            selected_program_id,
            int(selected_trip),
            reference_type,
            planned_reference.date().isoformat(),
            _format_time_text(planned_reference.time()),
        )
        if st.session_state.get("reprog_observed_time_context") != reprog_time_context:
            st.session_state["reprog_observed_time_value"] = planned_reference.time().replace(
                second=0,
                microsecond=0,
            )
            _sync_time_text_state(
                "reprog_observed_time_value",
                st.session_state["reprog_observed_time_value"],
                force=True,
            )
            st.session_state["reprog_observed_time_context"] = reprog_time_context
        d1, d2, d3 = st.columns([1.0, 0.9, 1.1])
        observed_date = d1.date_input(
            "Data observada do marco",
            value=planned_reference.date(),
            format="DD/MM/YYYY",
            key="reprog_observed_date",
        )
        with d2:
            _render_time_text_input(
                "Horário observado",
                "reprog_observed_time_value",
                help_text="Digite no formato HH:MM. Referência operacional preferencial em passos de 5 min.",
            )
        observed_time = st.session_state["reprog_observed_time_value"]
        override_enabled = d3.checkbox(
            "Sobrescrever BTs do grupo reprogramado",
            key="reprog_override_enabled",
            help=(
                "Use quando quiser testar uma quantidade diferente de BTs só para o grupo da programação "
                "reprogramada, sem alterar o cenário-base salvo."
            ),
        )
        d3.caption(
            (
                "Opcional. Mantém a frota atual do grupo reprogramado."
                if not override_enabled
                else "Ao ativar, a reprogramação passa a usar a quantidade de BTs informada abaixo."
            )
        )

        override_group_bt_count = None
        if override_enabled:
            override_group_bt_count = st.number_input(
                "BTs do grupo reprogramado",
                min_value=1,
                step=1,
                value=int(base_resultado.bt_counts.get(
                    next(
                        concretagem.grupo_bt
                        for concretagem in base_resultado.concretagens
                        if concretagem.id == selected_program_id
                    ),
                    1,
                )),
                key="reprog_override_bt_count",
            )

        observed_datetime = datetime.combine(observed_date, observed_time)
        delta_minutes = (observed_datetime - planned_reference).total_seconds() / 60.0
        target = next(
            concretagem for concretagem in base_resultado.concretagens if concretagem.id == selected_program_id
        )
        novo_inicio_estimado = target.inicio_datetime(base_resultado.data_base) + timedelta(
            minutes=delta_minutes
        )
        st.caption(
            "Marco: "
            f"{_reference_option_label(reference_type)} | "
            "Planejado: "
            f"{format_clock(planned_reference, base_resultado.data_base)} | "
            "Observado: "
            f"{format_clock(observed_datetime, base_resultado.data_base)} | "
            "Desvio aplicado: "
            f"{round_minutes(delta_minutes, 1)} min | "
            "Novo início estimado da 1ª mistura: "
            f"{format_clock(novo_inicio_estimado, base_resultado.data_base)}"
        )

        if st.button("Recalcular reprogramação", use_container_width=True, type="primary"):
            try:
                resultado_reprogramado, reprog_meta = _recalculate_reprogramming(
                    base_resultado,
                    concretagem_id=selected_program_id,
                    numero_viagem=int(selected_trip),
                    reference_type=reference_type,
                    observed_datetime=observed_datetime,
                    execution_mode=execution_mode,
                    max_total_bts=int(st.session_state.max_total_bts),
                    override_group_bt_count=(
                        int(override_group_bt_count) if override_enabled and override_group_bt_count else None
                    ),
                )
                st.session_state.resultado_reprogramado = resultado_reprogramado
                st.session_state.reprogramacao_meta = reprog_meta
                st.session_state["reprog_result_default_tab"] = "Gantt operacional"
            except Exception as exc:
                st.session_state.resultado_reprogramado = None
                st.session_state.reprogramacao_meta = None
                st.error(str(exc))


def _render_result(
    resultado,
    *,
    section_title: str = "Seção 3 — Resultados",
    helper_text: str = "Resumo executivo, detalhamento operacional, gráfico de gantt e exportações.",
    widget_prefix: str = "base",
    gantt_observed_marker: dict | None = None,
    expanded: bool = True,
) -> None:
    mobile_client = _is_mobile_client()
    with st.expander(section_title, expanded=expanded):
        st.markdown(
            f"<div class='section-helper'>{helper_text}</div>",
            unsafe_allow_html=True,
        )

        total_volume = sum(item.volume_total_m3 for item in resultado.concretagens)
        total_bt = sum(resultado.bt_counts.values())
        bt_summary = ", ".join(
            f"{label}: {count}"
            for key, count in resultado.bt_counts.items()
            for label in [resultado.bt_group_labels[key]]
        )
        prazo_labels = sorted(
            {
                format_clock(resumo["prazo_raw"], resultado.data_base)
                for resumo in resultado.resumo
                if resumo.get("prazo_raw") is not None
            }
        )
        intervalo_labels = sorted(
            {
                f"{round_minutes(resumo['intervalo_maximo_descargas_min'], 1)} min"
                for resumo in resultado.resumo
                if resumo.get("intervalo_maximo_descargas_min") is not None
            }
        )
        intervalo_atingido_labels = sorted(
            {
                f"{round_minutes(resumo['maior_intervalo_descargas_min'], 1)} min"
                for resumo in resultado.resumo
                if resumo.get("maior_intervalo_descargas_min") is not None
            }
        )
        intervalo_configurado_text = ", ".join(intervalo_labels) if intervalo_labels else "-"
        intervalo_atingido_text = ", ".join(intervalo_atingido_labels) if intervalo_atingido_labels else "-"
        prazo_configurado = any(resumo.get("prazo_raw") is not None for resumo in resultado.resumo)
        restricao_intervalo_ativa = any(
            resumo.get("intervalo_maximo_descargas_min") is not None
            for resumo in resultado.resumo
        )
        continuidade_por_programacao = [
            (
                resumo.get("nome_programacao", "Programação"),
                f"{round_minutes(resumo['intervalo_maximo_descargas_min'], 1)} min",
                f"{round_minutes(resumo['maior_intervalo_descargas_min'], 1)} min",
            )
            for resumo in resultado.resumo
            if resumo.get("intervalo_maximo_descargas_min") is not None
            and resumo.get("maior_intervalo_descargas_min") is not None
        ]
        bts_sugeridas_continuidade = [
            int(resumo["bts_sugeridas_continuidade"])
            for resumo in resultado.resumo
            if resumo.get("atende_intervalo_descargas") is False
            and resumo.get("bts_sugeridas_continuidade") is not None
        ]
        bt_sugerida_card = max(bts_sugeridas_continuidade) if bts_sugeridas_continuidade else None
        report_label = _current_scenario_label()
        report_filename_base = safe_identifier(report_label) or "cenario"
        if widget_prefix == "reprog":
            report_filename_base = f"{report_filename_base}_reprogramacao"
        relatorio_pdf_bytes = exportar_relatorio_operacional_pdf(
            resultado,
            scenario_label=report_label,
            helper_text=helper_text,
            observed_marker=gantt_observed_marker,
        )

        cards1 = st.columns(5) if not mobile_client else None
        modo_valor = "Automático" if resultado.automatico else "Fixo"
        modo_sub = (
            "Menor frota encontrada"
            if resultado.automatico and resultado.dimensionamento_encontrado
            else bt_summary
        )
        if cards1 is not None:
            card_targets = cards1
        else:
            card_targets = [st.container() for _ in range(5)]
        with card_targets[0]:
            _render_result_status_card(
                "Prazo de descarga",
                (
                    "Atende"
                    if resultado.prazo_atendido
                    else "Não atende"
                ) if prazo_configurado else "N/A",
                (
                    "Prazo limite: "
                    + ", ".join(prazo_labels)
                    + f"<br>Última descarga: {format_clock(resultado.termino_ultima_descarga, resultado.data_base)}"
                    if prazo_configurado
                    else "Nenhum prazo de descarga foi informado"
                ),
                "info" if not prazo_configurado else ("ok" if resultado.prazo_atendido else "bad"),
            )
        with card_targets[1]:
            continuidade_value = (
                "Atende"
                if resultado.atende_intervalo_descargas
                else "Não atende"
            ) if restricao_intervalo_ativa else "N/A"
            continuidade_sub = (
                "Sem restrição configurada"
                if not restricao_intervalo_ativa
                else "<br>".join(
                    f"{nome}: limite {configurado} | maior {atingido}"
                    for nome, configurado, atingido in continuidade_por_programacao
                )
            )
            _render_result_status_card(
                "Continuidade operacional",
                continuidade_value,
                continuidade_sub,
                "info" if not restricao_intervalo_ativa else ("ok" if resultado.atende_intervalo_descargas else "bad"),
            )
        with card_targets[2]:
            bts_card_sub = bt_summary
            if not resultado.atende_intervalo_descargas and bt_sugerida_card is not None:
                bts_card_sub = f"Atual: {bt_summary}<br>Sugestão para continuidade: {bt_sugerida_card} BTs"
            _render_result_status_card(
                "BTs utilizadas",
                str(total_bt),
                bts_card_sub,
                "info",
            )
        with card_targets[3]:
            _render_result_status_card(
                "Gargalo por espera",
                (
                    "Sem espera relevante"
                    if resultado.gargalo_por_espera == "sem espera"
                    else _preserve_label_case(resultado.gargalo_por_espera)
                ),
                (
                    "Sem espera acumulada relevante"
                    if resultado.gargalo_por_espera == "sem espera"
                    else "Recurso com maior espera acumulada"
                ),
                "info" if resultado.gargalo_por_espera == "sem espera" else "bad",
            )
        with card_targets[4]:
            _render_result_status_card(
                "Recurso mais ocupado",
                _preserve_label_case(resultado.recurso_mais_ocupado),
                "Maior taxa de ocupação relativa",
                "info",
            )

        st.markdown("<div class='result-row-gap'></div>", unsafe_allow_html=True)

        programacoes_calculadas = [
            resumo.get("nome_programacao", "-")
            for resumo in resultado.resumo
            if resumo.get("nome_programacao")
        ]
        resumo_apoio_rows = [
            {"Indicador": "Modo de cálculo", "Valor": modo_valor, "Detalhe": modo_sub},
            {
                "Indicador": "Programações calculadas",
                "Valor": str(len(programacoes_calculadas)),
                "Detalhe": ", ".join(programacoes_calculadas),
            },
            {
                "Indicador": "Volume total",
                "Valor": f"{round_minutes(total_volume, 2)} m³",
                "Detalhe": "Somatório das programações calculadas",
            },
            {
                "Indicador": "Viagens",
                "Valor": str(len(resultado.viagens)),
                "Detalhe": "Total de viagens geradas",
            },
            {
                "Indicador": "Última viagem",
                "Valor": format_clock(resultado.termino_ultima_viagem, resultado.data_base),
                "Detalhe": "Inclui lavagem e retorno",
            },
        ]
        prazos_resumo = [
            resumo.get("prazo_raw")
            for resumo in resultado.resumo
            if resumo.get("prazo_raw") is not None
        ]
        if prazos_resumo:
            resumo_apoio_rows.append(
                {
                    "Indicador": "Prazo limite",
                    "Valor": ", ".join(
                        sorted(
                            {
                                format_clock(prazo, resultado.data_base)
                                for prazo in prazos_resumo
                            }
                        )
                    ),
                    "Detalhe": "Horário limite configurado",
                }
            )
        if restricao_intervalo_ativa:
            resumo_apoio_rows.append(
                {
                    "Indicador": "Intervalo configurado",
                    "Valor": intervalo_configurado_text,
                    "Detalhe": "Limite adotado entre descargas",
                }
            )
            resumo_apoio_rows.append(
                {
                    "Indicador": "Maior intervalo atingido",
                    "Valor": intervalo_atingido_text,
                    "Detalhe": "Maior intervalo calculado no cenário",
                }
            )
        resumo_apoio_rows.append(
            {
                "Indicador": "Última descarga",
                "Valor": format_clock(resultado.termino_ultima_descarga, resultado.data_base),
                "Detalhe": "Referência principal para prazo",
            }
        )
        if bt_sugerida_card is not None:
            resumo_apoio_rows.append(
                {
                    "Indicador": "BTs sugeridas",
                    "Valor": str(bt_sugerida_card),
                    "Detalhe": "Referência visual para continuidade",
                }
            )
        st.markdown("<div class='result-row-gap'></div>", unsafe_allow_html=True)

        if resultado.recomendacoes_ajuste:
            _render_result_box(
                "O que pode ser alterado para atender as restrições do cenário",
                resultado.recomendacoes_ajuste,
            )

        result_tab_labels = [
            "Planejamento",
            "Disponibilidade",
            "Resumo",
            "Premissas",
        ]
        default_result_tab = st.session_state.get(f"{widget_prefix}_result_default_tab")
        if default_result_tab not in result_tab_labels:
            default_result_tab = None
        gantt_tab, disponibilidade_tab, resumo_tab, premissas_tab = st.tabs(
            result_tab_labels,
            default=default_result_tab,
        )
        if default_result_tab is not None:
            st.session_state[f"{widget_prefix}_result_default_tab"] = None

        with resumo_tab:
            concretagem_lookup = {concretagem.id: concretagem for concretagem in resultado.concretagens}
            for resumo in resultado.resumo:
                with st.expander(resumo["nome_programacao"], expanded=False):
                        concretagem = concretagem_lookup.get(str(resumo["id"]))
                        viagens_programacao = [
                            viagem for viagem in resultado.viagens if viagem.concretagem_id == resumo["id"]
                        ]
                        restricoes = concretagem.restricoes if concretagem else None
                        prazo_delta = None
                        if resumo["prazo_raw"] is not None and resumo["termino_ultima_descarga_raw"] is not None:
                            prazo_delta = (
                                resumo["termino_ultima_descarga_raw"] - resumo["prazo_raw"]
                            ).total_seconds() / 60

                        espera_mistura = sum(viagem.espera_mistura_min for viagem in viagens_programacao)
                        espera_dosagem = sum(viagem.espera_dosagem_min for viagem in viagens_programacao)
                        espera_bomba = sum(viagem.espera_bomba_min for viagem in viagens_programacao)
                        espera_frente = sum(viagem.espera_frente_min for viagem in viagens_programacao)
                        esperas = {
                            "mistura": espera_mistura,
                            "dosagem": espera_dosagem,
                            "bomba": espera_bomba,
                            "frente": espera_frente,
                        }
                        gargalo_programacao = max(esperas, key=esperas.get)
                        gargalo_programacao_label = (
                            "Sem espera relevante"
                            if esperas[gargalo_programacao] <= 0
                            else _preserve_label_case(gargalo_programacao)
                        )

                        status_prazo = "Atende" if resumo["atende_prazo"] else "Não atende"
                        status_continuidade = (
                            "Atende"
                            if resumo["atende_intervalo_descargas"]
                            else "Não atende"
                        ) if resumo["intervalo_maximo_descargas_min"] is not None else "N/A"
                        alocacao_bt = (
                            "BTs dedicadas"
                            if restricoes and restricoes.alocacao_bts == "dedicadas"
                            else "BTs compartilhadas"
                        )
                        recurso_descarga_label = (
                            "bomba" if restricoes and restricoes.com_bomba else "frente"
                        )
                        prazo_delta_label = "N/A"
                        if prazo_delta is not None:
                            if prazo_delta <= 0:
                                prazo_delta_label = f"Folga de {round_minutes(abs(prazo_delta), 1)} min"
                            else:
                                prazo_delta_label = f"Atraso de {round_minutes(prazo_delta, 1)} min"

                        resumo_rows = [
                            {
                                "Grupo": "Identificação",
                                "Indicador": "Local",
                                "Valor": resumo["local"] or "-",
                            },
                            {
                                "Grupo": "Identificação",
                                "Indicador": "Elemento / frente",
                                "Valor": resumo["elemento_frente"] or "-",
                            },
                            {
                                "Grupo": "Identificação",
                                "Indicador": "Usina",
                                "Valor": concretagem.usina if concretagem and concretagem.usina else "-",
                            },
                            {
                                "Grupo": "Identificação",
                                "Indicador": "Observações",
                                "Valor": (
                                    concretagem.observacoes
                                    if concretagem and concretagem.observacoes
                                    else "-"
                                ),
                            },
                            {
                                "Grupo": "Operação",
                                "Indicador": "Prioridade",
                                "Valor": _format_priority_label(resumo["prioridade"]),
                            },
                            {
                                "Grupo": "Operação",
                                "Indicador": "Grupo de BT",
                                "Valor": resumo["grupo_bt_label"],
                            },
                            {
                                "Grupo": "Operação",
                                "Indicador": "Alocação de BTs",
                                "Valor": alocacao_bt,
                            },
                            {
                                "Grupo": "Operação",
                                "Indicador": f"BTs na {recurso_descarga_label}",
                                "Valor": str(resumo["bts_utilizadas"]),
                            },
                            {
                                "Grupo": "Operação",
                                "Indicador": "BTs sugeridas para continuidade",
                                "Valor": str(resumo["bts_sugeridas_continuidade"])
                                if resumo["bts_sugeridas_continuidade"] is not None
                                else "N/A",
                            },
                            {
                                "Grupo": "Operação",
                                "Indicador": "Com bomba",
                                "Valor": "Sim" if restricoes and restricoes.com_bomba else "Não",
                            },
                            {
                                "Grupo": "Operação",
                                "Indicador": f"Limite simultâneo na {recurso_descarga_label}",
                                "Valor": (
                                    str(restricoes.max_bts_frente)
                                    if restricoes
                                    else "-"
                                ),
                            },
                            {
                                "Grupo": "Operação",
                                "Indicador": "Limite simultâneo na mistura",
                                "Valor": (
                                    str(restricoes.max_bts_mistura)
                                    if restricoes
                                    else "-"
                                ),
                            },
                            {
                                "Grupo": "Operação",
                                "Indicador": "Limite simultâneo na dosagem",
                                "Valor": (
                                    str(restricoes.max_bts_dosagem)
                                    if restricoes
                                    else "-"
                                ),
                            },
                            {
                                "Grupo": "Operação",
                                "Indicador": "Intervalo entre misturas",
                                "Valor": (
                                    f"{round_minutes(restricoes.intervalo_entre_misturas_min, 1)} min"
                                    if restricoes and restricoes.existe_intervalo_entre_misturas
                                    else "Não aplicável"
                                ),
                            },
                            {
                                "Grupo": "Volumes e viagens",
                                "Indicador": "Volume total",
                                "Valor": f"{round_minutes(resumo['volume_total_m3'], 2)} m³",
                            },
                            {
                                "Grupo": "Volumes e viagens",
                                "Indicador": "Capacidade da BT",
                                "Valor": f"{round_minutes(resumo['capacidade_bt_m3'], 2)} m³",
                            },
                            {
                                "Grupo": "Volumes e viagens",
                                "Indicador": "Número de viagens",
                                "Valor": str(resumo["numero_viagens"]),
                            },
                            {
                                "Grupo": "Volumes e viagens",
                                "Indicador": "Volume da 1ª viagem",
                                "Valor": f"{round_minutes(resumo['volume_primeira_viagem_m3'], 2)} m³",
                            },
                            {
                                "Grupo": "Volumes e viagens",
                                "Indicador": "Volume da última viagem",
                                "Valor": f"{round_minutes(resumo['volume_ultima_viagem_m3'], 2)} m³",
                            },
                            {
                                "Grupo": "Prazos e desempenho",
                                "Indicador": "Início da 1ª mistura",
                                "Valor": format_clock(
                                    resumo.get("inicio_primeira_mistura_raw"), resultado.data_base
                                ),
                            },
                            {
                                "Grupo": "Prazos e desempenho",
                                "Indicador": "Término da última descarga",
                                "Valor": format_clock(
                                    resumo["termino_ultima_descarga_raw"], resultado.data_base
                                ),
                            },
                            {
                                "Grupo": "Prazos e desempenho",
                                "Indicador": "Término da última viagem",
                                "Valor": format_clock(
                                    resumo["termino_ultima_viagem_raw"], resultado.data_base
                                ),
                            },
                            {
                                "Grupo": "Prazos e desempenho",
                                "Indicador": "Prazo limite",
                                "Valor": format_clock(resumo["prazo_raw"], resultado.data_base),
                            },
                            {
                                "Grupo": "Prazos e desempenho",
                                "Indicador": "Situação do prazo",
                                "Valor": status_prazo,
                            },
                            {
                                "Grupo": "Prazos e desempenho",
                                "Indicador": "Folga / atraso ao prazo",
                                "Valor": prazo_delta_label,
                            },
                            {
                                "Grupo": "Continuidade",
                                "Indicador": "Situação da continuidade",
                                "Valor": status_continuidade,
                            },
                            {
                                "Grupo": "Continuidade",
                                "Indicador": "Intervalo máximo entre descargas",
                                "Valor": (
                                    f"{round_minutes(resumo['intervalo_maximo_descargas_min'], 1)} min"
                                    if resumo["intervalo_maximo_descargas_min"] is not None
                                    else "N/A"
                                ),
                            },
                            {
                                "Grupo": "Continuidade",
                                "Indicador": "Maior intervalo calculado",
                                "Valor": (
                                    f"{round_minutes(resumo['maior_intervalo_descargas_min'], 1)} min"
                                    if resumo["intervalo_maximo_descargas_min"] is not None
                                    else "N/A"
                                ),
                            },
                            {
                                "Grupo": "Indicadores operacionais",
                                "Indicador": "Espera por mistura",
                                "Valor": f"{round_minutes(espera_mistura, 1)} min",
                            },
                            {
                                "Grupo": "Indicadores operacionais",
                                "Indicador": "Espera por dosagem",
                                "Valor": f"{round_minutes(espera_dosagem, 1)} min",
                            },
                            {
                                "Grupo": "Indicadores operacionais",
                                "Indicador": "Espera por bomba",
                                "Valor": f"{round_minutes(espera_bomba, 1)} min",
                            },
                            {
                                "Grupo": "Indicadores operacionais",
                                "Indicador": "Espera por frente",
                                "Valor": f"{round_minutes(espera_frente, 1)} min",
                            },
                            {
                                "Grupo": "Indicadores operacionais",
                                "Indicador": "Gargalo predominante da programação",
                                "Valor": gargalo_programacao_label,
                            },
                            {
                                "Grupo": "Configuração consolidada",
                                "Indicador": "BT fixa cadastrada",
                                "Valor": (
                                    str(concretagem.numero_bts_fixo)
                                    if concretagem and concretagem.numero_bts_fixo is not None
                                    else "N/A"
                                ),
                            },
                            {
                                "Grupo": "Configuração consolidada",
                                "Indicador": "Última viagem parcial proporcional",
                                "Valor": (
                                    "Sim"
                                    if restricoes and restricoes.ultima_viagem_parcial_proporcional
                                    else "Não"
                                ),
                            },
                            {
                                "Grupo": "Configuração consolidada",
                                "Indicador": "1ª viagem customizada",
                                "Valor": (
                                    f"{round_minutes(restricoes.volume_primeira_viagem_m3, 2)} m³"
                                    if restricoes and restricoes.volume_primeira_viagem_m3 is not None
                                    else "Não"
                                ),
                            },
                            *[
                                {
                                    "Grupo": "Configuração consolidada",
                                    "Indicador": f"Restrição adotada {idx}",
                                    "Valor": part,
                                }
                                for idx, part in enumerate(
                                    [
                                        part.strip()
                                        for part in str(resumo.get("restricoes_adotadas", "")).split(";")
                                        if part.strip()
                                    ],
                                    start=1,
                                )
                            ],
                            {
                                "Grupo": "Tempos de ciclo",
                                "Indicador": "Mistura",
                                "Valor": (
                                    f"{round_minutes(concretagem.ciclo.mistura_min, 1)} min"
                                    if concretagem
                                    else "-"
                                ),
                            },
                            {
                                "Grupo": "Tempos de ciclo",
                                "Indicador": "Dosagem",
                                "Valor": (
                                    f"{round_minutes(concretagem.ciclo.dosagem_min, 1)} min"
                                    if concretagem
                                    else "-"
                                ),
                            },
                            {
                                "Grupo": "Tempos de ciclo",
                                "Indicador": "Ida",
                                "Valor": (
                                    f"{round_minutes(concretagem.ciclo.ida_min, 1)} min"
                                    if concretagem
                                    else "-"
                                ),
                            },
                            {
                                "Grupo": "Tempos de ciclo",
                                "Indicador": "Slump",
                                "Valor": (
                                    f"{round_minutes(concretagem.ciclo.slump_min, 1)} min"
                                    if concretagem
                                    else "-"
                                ),
                            },
                            {
                                "Grupo": "Tempos de ciclo",
                                "Indicador": "Descarga",
                                "Valor": (
                                    f"{round_minutes(concretagem.ciclo.descarga_min, 1)} min"
                                    if concretagem
                                    else "-"
                                ),
                            },
                            {
                                "Grupo": "Tempos de ciclo",
                                "Indicador": "Lavagem",
                                "Valor": (
                                    f"{round_minutes(concretagem.ciclo.lavagem_min, 1)} min"
                                    if concretagem
                                    else "-"
                                ),
                            },
                            {
                                "Grupo": "Tempos de ciclo",
                                "Indicador": "Volta",
                                "Valor": (
                                    f"{round_minutes(concretagem.ciclo.volta_min, 1)} min"
                                    if concretagem
                                    else "-"
                                ),
                            },
                            ]
                        resumo_tabela = pd.DataFrame(resumo_rows)
                        st.table(resumo_tabela)

        with gantt_tab:
            if mobile_client:
                figura_estatica = gerar_gantt(resultado, observed_marker=gantt_observed_marker)
                st.pyplot(figura_estatica, use_container_width=True, clear_figure=True)
            else:
                figura_interativa = gerar_gantt_interativo(resultado, observed_marker=gantt_observed_marker)
                if figura_interativa is not None:
                    st.plotly_chart(
                        figura_interativa,
                        use_container_width=True,
                        config={
                            "displaylogo": False,
                            "toImageButtonOptions": {
                                "format": "png",
                                "filename": "gantt_interativo",
                                "scale": 1,
                                "width": None,
                                "height": None,
                            },
                        },
                        key=f"{widget_prefix}_gantt_interativo",
                    )
            st.markdown("<div class='result-row-gap'></div>", unsafe_allow_html=True)
            csv_bytes = exportar_detalhamento_csv(resultado.dataframe_detalhado)
            st.markdown("<div class='result-export-actions-marker'></div>", unsafe_allow_html=True)
            export_col1, export_col2 = st.columns(2)
            export_col1.download_button(
                "Baixar CSV do detalhamento",
                data=csv_bytes,
                file_name="detalhamento_concretagens.csv",
                mime="text/csv",
                key=f"{widget_prefix}_download_detalhamento",
                use_container_width=True,
            )
            export_col2.download_button(
                "Baixar relatório operacional (PDF)",
                data=relatorio_pdf_bytes,
                file_name=f"{report_filename_base}_relatorio_operacional.pdf",
                mime="application/pdf",
                key=f"{widget_prefix}_download_relatorio_pdf",
                use_container_width=True,
            )
            dataframe_filtrado = _apply_detail_filters(resultado.dataframe_detalhado, key_prefix=widget_prefix)
            st.dataframe(
                dataframe_filtrado,
                use_container_width=True,
                hide_index=True,
                height=_dataframe_height_for_rows(
                    len(dataframe_filtrado),
                    row_height=33,
                    header_height=35,
                    padding=2,
                    min_height=72,
                    max_height=560,
                ),
            )

        with disponibilidade_tab:
            if mobile_client:
                figura_disponibilidade_estatica = gerar_disponibilidade_bt(resultado)
                st.pyplot(figura_disponibilidade_estatica, use_container_width=True, clear_figure=True)
            else:
                figura_disponibilidade_interativa = gerar_disponibilidade_bt_interativa(resultado)
                if figura_disponibilidade_interativa is not None:
                    st.plotly_chart(
                        figura_disponibilidade_interativa,
                        use_container_width=True,
                        config={
                            "displaylogo": False,
                            "toImageButtonOptions": {
                                "format": "png",
                                "filename": "disponibilidade_bt_interativa",
                                "scale": 1,
                                "width": None,
                                "height": None,
                            },
                        },
                        key=f"{widget_prefix}_disponibilidade_interativa",
                    )
            tabela_disponibilidade = gerar_tabela_disponibilidade_bt(resultado)
            st.table(tabela_disponibilidade)

        with premissas_tab:
            premissas_gerais = []
            premissas_recursos = []
            premissas_programacao = []
            for premissa in resultado.premissas:
                if any(
                    marker in premissa.lower()
                    for marker in [
                        "prazo principal",
                        "término da volta",
                        "mesma bt",
                        "intervalo ocioso",
                        "data-base",
                        "carga mínima",
                    ]
                ):
                    premissas_gerais.append(premissa)
                elif any(
                    marker in premissa.lower()
                    for marker in [
                        "recursos compartilhados",
                        "bts dedicadas",
                        "bts compartilhadas",
                    ]
                ):
                    premissas_recursos.append(premissa)
                else:
                    premissas_programacao.append(premissa)

            _render_result_box_sections(
                "Premissas consideradas",
                [
                    ("Critérios de cálculo", premissas_gerais),
                    ("Recursos e alocação", premissas_recursos),
                    ("Configuração operacional", premissas_programacao),
                ],
            )


def main() -> None:
    if "scenario_payloads" not in st.session_state:
        st.session_state.scenario_payloads = []
    if "calc_mode" not in st.session_state:
        st.session_state.calc_mode = "fixo"
    if "max_total_bts" not in st.session_state:
        st.session_state.max_total_bts = 12
    if "sequenciar_por_prioridade" not in st.session_state:
        st.session_state.sequenciar_por_prioridade = False
    if "liberar_bt_compartilhada_parcialmente" not in st.session_state:
        st.session_state.liberar_bt_compartilhada_parcialmente = False
    if "current_scenario_date" not in st.session_state:
        st.session_state.current_scenario_date = date.today()
    if "current_scenario_turno" not in st.session_state:
        st.session_state.current_scenario_turno = "Diurno"
    if "current_scenario_id" not in st.session_state:
        st.session_state.current_scenario_id = ""
    if "current_scenario_name" not in st.session_state:
        st.session_state.current_scenario_name = ""
    if "selected_saved_scenario_id" not in st.session_state:
        st.session_state.selected_saved_scenario_id = ""
    if "toast_message" not in st.session_state:
        st.session_state.toast_message = ""
    if "last_saved_scenario_signature" not in st.session_state:
        st.session_state.last_saved_scenario_signature = ""
    if "resultado_reprogramado" not in st.session_state:
        st.session_state.resultado_reprogramado = None
    if "reprogramacao_meta" not in st.session_state:
        st.session_state.reprogramacao_meta = None
    if "pending_scenario_action" not in st.session_state:
        st.session_state.pending_scenario_action = None
    if "pending_program_action" not in st.session_state:
        st.session_state.pending_program_action = None
    if "current_page" not in st.session_state:
        st.session_state.current_page = "cenario"
    if "pending_focus_program_index" not in st.session_state:
        st.session_state.pending_focus_program_index = None
    if "confirm_delete_scenario" not in st.session_state:
        st.session_state.confirm_delete_scenario = False
    if "delete_target_scenario_id" not in st.session_state:
        st.session_state.delete_target_scenario_id = ""
    mobile_client = _is_mobile_client()
    if "delete_target_scenario_label" not in st.session_state:
        st.session_state.delete_target_scenario_label = ""
    if "delete_target_previous_scenario_id" not in st.session_state:
        st.session_state.delete_target_previous_scenario_id = ""
    if "delete_target_scenario_date" not in st.session_state:
        st.session_state.delete_target_scenario_date = None
    if "delete_target_scenario_turno" not in st.session_state:
        st.session_state.delete_target_scenario_turno = ""
    if "delete_target_scenario_name" not in st.session_state:
        st.session_state.delete_target_scenario_name = ""
    if "pending_delete_preview_record" not in st.session_state:
        st.session_state.pending_delete_preview_record = None
    if "delete_cancel_restore_state" not in st.session_state:
        st.session_state.delete_cancel_restore_state = None
    if "scenario_form_synced_from_active" not in st.session_state:
        st.session_state.scenario_form_synced_from_active = False
    if "active_program_index" not in st.session_state:
        st.session_state.active_program_index = 0
    if "last_calculated_signature" not in st.session_state:
        st.session_state.last_calculated_signature = ""
    if "show_reprogramming_section" not in st.session_state:
        st.session_state.show_reprogramming_section = False
    if "_pending_saved_scenarios_without_device" not in st.session_state:
        st.session_state["_pending_saved_scenarios_without_device"] = []
    if "_browser_device_bootstrap_id" not in st.session_state:
        st.session_state["_browser_device_bootstrap_id"] = ""

    _inject_styles()
    if not _bootstrap_browser_device_identity():
        return
    _ensure_browser_device_identity()
    _flush_pending_saved_scenarios_if_needed()

    _process_pending_scenario_action()
    _process_pending_program_action()
    _process_pending_selected_scenario()
    _process_pending_delete_preview()
    saved_scenarios = _load_saved_scenarios()
    saved_ids = {item.get("id", "") for item in saved_scenarios}
    if st.session_state.selected_saved_scenario_id and st.session_state.selected_saved_scenario_id not in saved_ids:
        st.session_state.selected_saved_scenario_id = ""
    _sync_scenario_form_from_active(saved_scenarios)

    if (
        st.session_state.current_page == "planejamento"
        and _has_active_scenario()
        and not st.session_state.current_scenario_name.strip()
    ):
        st.session_state.current_scenario_name = "Cenário"

    _sync_theme_marker()
    page_helper_text = (
        "Aplicação para planejamento operacional de concretagens, simulação de ciclos "
        "e dimensionamento de betoneiras com verificação de prazo e continuidade."
    )
    st.markdown(
        (
            "<div class='page-title-block'>"
            "<div class='page-title-row'>"
            "<div class='page-title-text'>Programações Concretagem – NSA</div>"
            "<div class='page-title-help'>"
            "<details><summary aria-label='Informações desta tela'>?</summary>"
            f"<div class='body'>{html.escape(page_helper_text)}</div>"
            "</details>"
            "</div>"
            "</div>"
            f"<div class='page-title-subtitle'>{html.escape(page_helper_text)}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )
    st.markdown("<div class='page-separator'></div>", unsafe_allow_html=True)
    if st.session_state.toast_message:
        st.toast(st.session_state.toast_message)
        st.session_state.toast_message = ""

    salvar_cenario = False
    calcular = False
    current_page = st.session_state.current_page

    if current_page == "cenario":
        st.subheader("Cadastro do cenário")
        st.info("Cadastre, carregue ou duplique cenário para edição das programações")
        bloco_novo, bloco_carregar = st.columns(2)

        with bloco_novo:
            with st.container(border=True):
                st.markdown("**Cadastro de novo cenário**")
                n1, n2 = st.columns(2)
                n1.date_input(
                    "Data do cenário",
                    key="current_scenario_date",
                    format="DD/MM/YYYY",
                )
                n2.selectbox(
                    "Turno",
                    options=TURNO_OPTIONS,
                    key="current_scenario_turno",
                )
                st.text_input(
                    "Nome *",
                    key="current_scenario_name",
                    placeholder="Digite um nome para o cenário",
                    help="Preenchimento obrigatório.",
                )
                st.caption(f"Nome do cenário: {_current_scenario_label()}")
                if st.button("Novo cenário", use_container_width=True):
                    if not st.session_state.current_scenario_name.strip():
                        st.error("Preencha o campo Nome para criar o cenário.")
                    else:
                        _queue_new_scenario()
                        st.rerun()

        with bloco_carregar:
            with st.container(border=True):
                st.markdown("**Carregamento de cenário cadastrado**")
                scenario_options = {
                    item.get("id", ""): item.get("label", "Cenário salvo")
                    for item in saved_scenarios
                    if item.get("id", "")
                }
                selected_id = st.session_state.selected_saved_scenario_id
                selectbox_index = None
                if selected_id in scenario_options:
                    selectbox_index = list(scenario_options.keys()).index(selected_id)
                st.selectbox(
                    "Cenários salvos",
                    options=list(scenario_options.keys()),
                    format_func=lambda item: scenario_options[item],
                    index=selectbox_index,
                    placeholder="Selecione um cenário salvo",
                    key="selected_saved_scenario_id",
                )
                _disable_saved_scenario_search()
                selected_id = st.session_state.selected_saved_scenario_id
                c1, c2 = st.columns(2)
                if c1.button(
                    "Carregar cenário",
                    use_container_width=True,
                    disabled=not selected_id,
                ):
                    if selected_id:
                        _queue_load_scenario(selected_id)
                        st.rerun()
                if c2.button(
                    "Duplicar cenário",
                    use_container_width=True,
                    disabled=not selected_id,
                ):
                    if selected_id:
                        _queue_duplicate_scenario(selected_id)
                        st.rerun()
                with st.expander("Importação de programação CSV", expanded=False):
                    uploaded_csv = st.file_uploader(
                        "Arquivo CSV exportado pelo sistema",
                        type=["csv"],
                        key="scenario_csv_upload",
                    )
                    if st.button(
                        "Importar CSV da programação",
                        use_container_width=True,
                        disabled=uploaded_csv is None,
                    ):
                        if uploaded_csv is not None:
                            try:
                                imported_record = importar_programacao_cenario_csv(uploaded_csv.getvalue())
                                _queue_import_scenario(imported_record)
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))

        st.markdown("<div style='height: 0.9rem;'></div>", unsafe_allow_html=True)
        with st.expander("Sobre o sistema", expanded=False):
            st.write(
                "A aplicação apoia o planejamento de concretagens, a simulação do ciclo das betoneiras "
                "e o dimensionamento da frota mínima para atender prazo e continuidade operacional."
            )
            st.markdown("**O que o sistema faz**")
            st.write(
                "- cadastra cenários com uma ou mais programações;"
                "\n- simula mistura, dosagem, ida, slump, descarga, lavagem e volta;"
                "\n- dimensiona BTs em modo fixo ou automático;"
                "\n- verifica prazo principal pelo término da descarga;"
                "\n- verifica continuidade operacional pelo intervalo entre descargas;"
                "\n- gera resumo executivo, tabela detalhada, gantt e disponibilidade de BT;"
                "\n- exporta resultados em CSV e PNG."
            )
            st.markdown("**Exemplos práticos**")
            st.write(
                "- simular uma concretagem simples com 1 BT para validar horário final;"
                "\n- testar se uma laje com bomba e 1 BT por vez mantém bombeamento contínuo;"
                "\n- comparar modo fixo e automático para descobrir a menor frota viável;"
                "\n- avaliar frentes simultâneas compartilhando a mesma usina;"
                "\n- usar prioridade para desempatar programações em conflito operacional;"
                "\n- visualizar, ao longo do tempo, quantas BTs ficam ocupadas e livres."
            )

    elif _has_active_scenario():
        scenario_export_record = None
        scenario_export_bytes = b""
        scenario_export_filename = "cenario_programacao.csv"
        scenario_export_error = ""
        try:
            scenario_export_record = _build_current_scenario_record()
            scenario_export_bytes = exportar_programacao_cenario_csv(scenario_export_record)
            scenario_export_filename = (
                f"{safe_identifier(scenario_export_record['label']) or 'cenario'}_programacao.csv"
            )
        except ValueError as exc:
            scenario_export_error = str(exc)

        with st.container(border=True):
            st.markdown(
                (
                    "**Cenário em edição** "
                    "<span style='font-size:0.86rem;color:#7c8796;font-weight:400;'>"
                    "(salvamento automático)"
                    "</span>"
                ),
                unsafe_allow_html=True,
            )
            if mobile_client:
                st.markdown("<div class='active-scenario-box-marker'></div>", unsafe_allow_html=True)
                _render_active_scenario_box()
                st.markdown("<div class='scenario-actions-row-two-marker'></div>", unsafe_allow_html=True)
                mobile_actions_row1 = st.columns(2)
                mobile_actions_row1[0].download_button(
                    "Exportar",
                    data=scenario_export_bytes,
                    file_name=scenario_export_filename,
                    mime="text/csv",
                    use_container_width=True,
                    disabled=scenario_export_record is None,
                )
                if mobile_actions_row1[1].button("Excluir", use_container_width=True):
                    try:
                        current_record = _build_current_scenario_record()
                        st.session_state.pending_delete_preview_record = {
                            "record": current_record,
                            "previous_id": st.session_state.get("current_scenario_id", "").strip(),
                        }
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
                st.markdown("<div class='scenario-actions-row-single-marker'></div>", unsafe_allow_html=True)
                mobile_actions_row2 = st.columns(1)
                if mobile_actions_row2[0].button("Voltar", use_container_width=True):
                    _go_to_page("cenario")
                    st.rerun()
                if scenario_export_error:
                    st.caption("Preencha o nome do cenário para exportar.")
            else:
                st.markdown("<div class='scenario-actions-marker'></div>", unsafe_allow_html=True)
                topo1, topo2, topo4, topo5 = st.columns([1.65, 1.0, 1.0, 1.0])
                with topo1:
                    _render_active_scenario_box()
                topo2.download_button(
                    "Exportar programação CSV",
                    data=scenario_export_bytes,
                    file_name=scenario_export_filename,
                    mime="text/csv",
                    use_container_width=True,
                    disabled=scenario_export_record is None,
                )
                if scenario_export_error:
                    topo2.caption("Preencha o nome do cenário para exportar.")
                if topo4.button("Excluir cenário", use_container_width=True):
                    try:
                        current_record = _build_current_scenario_record()
                        st.session_state.pending_delete_preview_record = {
                            "record": current_record,
                            "previous_id": st.session_state.get("current_scenario_id", "").strip(),
                        }
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
                if topo5.button("Voltar para cenários", use_container_width=True):
                    _go_to_page("cenario")
                    st.rerun()

            st.markdown("<div style='height: 0.3rem;'></div>", unsafe_allow_html=True)
            st.markdown("<div class='scenario-meta-expander-marker'></div>", unsafe_allow_html=True)
            with st.expander("Dados do cenário", expanded=True):
                meta1, meta2, meta3 = st.columns([0.85, 0.85, 1.55])
                meta1.date_input(
                    "Data do cenário",
                    key="current_scenario_date",
                    format="DD/MM/YYYY",
                )
                meta2.selectbox(
                    "Turno",
                    options=TURNO_OPTIONS,
                    key="current_scenario_turno",
                )
                meta3.text_input(
                    "Nome do cenário",
                    key="current_scenario_name",
                    placeholder="Digite um nome para o cenário",
                )
            _sync_expander_open_state("Dados do cenário", "scenario_meta_expander_open", mobile_default_open=False)

        if st.session_state.confirm_delete_scenario:
            target_label = st.session_state.get("delete_target_scenario_label", "").strip() or _current_scenario_label()
            message = f"Confirma a exclusão do cenário **{target_label}**?"
            st.error(message)
            confirm1, confirm2 = st.columns(2)
            if confirm1.button("Confirmar exclusão", use_container_width=True):
                target_ids = [
                    st.session_state.get("delete_target_scenario_id", "").strip(),
                    st.session_state.get("delete_target_previous_scenario_id", "").strip(),
                ]
                _reset_delete_confirmation_state()
                _queue_delete_scenario_targets(target_ids)
                st.rerun()
            if confirm2.button("Cancelar", use_container_width=True):
                _reset_delete_confirmation_state()
                st.rerun()

        st.markdown("<div style='height: 0.9rem;'></div>", unsafe_allow_html=True)

        with st.expander("Seção 1 — Cadastro da concretagem", expanded=True):
            st.markdown(
                "<div class='section-helper'>Cadastre uma ou mais concretagens e organize os dados operacionais de cada frente.</div>",
                unsafe_allow_html=True,
            )
            payloads = _snapshot_payloads_from_state()
            st.session_state.scenario_payloads = payloads
            pending_focus = st.session_state.get("pending_focus_program_index")
            if pending_focus is not None:
                st.query_params["programa"] = str(max(0, min(int(pending_focus), len(payloads) - 1)))
            _sync_active_program_from_query(len(payloads))
            active_index = max(0, min(int(st.session_state.get("active_program_index", 0)), len(payloads) - 1))

            tab_labels = [
                _current_program_name(index, payload)
                for index, payload in enumerate(payloads, start=1)
            ]

            toolbar1, toolbar2, toolbar3 = st.columns([1, 1, 1])
            if toolbar1.button("Adicionar programação", use_container_width=True):
                payloads.append(_default_payload(len(payloads) + 1))
                _apply_payloads(payloads)
                st.session_state.pending_focus_program_index = len(payloads) - 1
                st.rerun()
            toolbar2.empty()
            toolbar3.empty()
            _render_program_tabs_anchor()
            tabs = st.tabs(tab_labels)
            for index, (tab, payload) in enumerate(
                zip(tabs, payloads),
                start=1,
            ):
                with tab:
                    st.markdown("<div class='program-actions-marker'></div>", unsafe_allow_html=True)
                    tab_toolbar1, tab_toolbar2, tab_toolbar3, tab_toolbar4 = st.columns([0.8, 0.8, 1.15, 1.15])
                    if tab_toolbar1.button(
                        "Mover à esquerda",
                        key=f"mover_programacao_esquerda_{index}",
                        use_container_width=True,
                        disabled=index == 1,
                    ):
                        _queue_move_program(index - 1, "left")
                        st.rerun()
                    if tab_toolbar2.button(
                        "Mover à direita",
                        key=f"mover_programacao_direita_{index}",
                        use_container_width=True,
                        disabled=index == len(st.session_state.scenario_payloads),
                    ):
                        _queue_move_program(index - 1, "right")
                        st.rerun()
                    if tab_toolbar3.button(
                        "Duplicar programação",
                        key=f"duplicar_programacao_{index}",
                        use_container_width=True,
                    ):
                        _queue_duplicate_program(index - 1)
                        st.rerun()
                    if tab_toolbar4.button(
                        "Remover programação",
                        key=f"remover_programacao_{index}",
                        use_container_width=True,
                        disabled=len(st.session_state.scenario_payloads) == 1,
                    ):
                        _queue_remove_program(index - 1)
                        st.rerun()
                    st.markdown("<div style='height: 0.35rem;'></div>", unsafe_allow_html=True)
                    _render_scenario_form(index, payload)
            _render_program_tab_tracking()
            _render_active_program_focus()
        _invalidate_stale_result_if_needed()
        _sync_reprogramming_visibility()

        st.markdown("<div class='main-section-gap'></div>", unsafe_allow_html=True)

        with st.expander("Seção 2 — Configuração do cálculo", expanded=True):
            st.markdown(
                "<div class='section-helper'>Escolha o tipo de cálculo e informe apenas os parâmetros usados nesse modo.</div>",
                unsafe_allow_html=True,
            )

            # Linha 1: programações para calcular
            calc_program_options = list(range(1, len(st.session_state.scenario_payloads) + 1))
            calc_program_labels = {
                index: st.session_state.get(
                    _widget_key(index, "nome_programacao"),
                    payload.get("elemento_frente") or payload.get("nome_programacao", f"Programação {index}"),
                )
                for index, payload in enumerate(st.session_state.scenario_payloads, start=1)
            }
            _sync_calculation_program_selection(len(calc_program_options))
            st.multiselect(
                "Programações para calcular",
                options=calc_program_options,
                format_func=lambda item: calc_program_labels[item],
                key="calc_selected_programs_widget",
                on_change=_store_calculation_program_selection_from_widget,
                help=(
                    "Por padrão, todas as programações cadastradas entram no cálculo. "
                    "Você pode escolher só uma ou qualquer combinação entre elas."
                ),
            )
            st.caption(
                "Selecione todas para o cálculo completo do cenário, ou escolha apenas as programações que deseja simular em conjunto."
            )
            selected_programs = [
                int(item)
                for item in st.session_state.get("calc_selected_programs", calc_program_options)
                if int(item) in calc_program_options
            ]
            calculation_time_errors = _collect_calculation_time_errors(selected_programs)
            calculate_disabled = bool(calculation_time_errors)

            st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)

            # Linha 2: modo de cálculo
            cfg1, cfg2 = st.columns([1.25, 1.0])
            cfg1.radio(
                "Modo de cálculo",
                options=["fixo", "automatico"],
                format_func=lambda item: (
                    "Quantidade fixa definida" if item == "fixo" else "Dimensionamento automático"
                ),
                horizontal=True,
                key="calc_mode",
            )
            if st.session_state.calc_mode == "fixo":
                bt_fixa_summary = " | ".join(
                    f"{calc_program_labels[index]}: {int(st.session_state.get(_widget_key(index, 'numero_bts_fixo'), 0))}"
                    for index in selected_programs
                )
                cfg2.markdown(
                    "<div class='section-helper' style='margin-top:0.55rem;margin-bottom:0;'>BT fixa definida nas programações selecionadas.</div>",
                    unsafe_allow_html=True,
                )
                cfg2.caption(bt_fixa_summary or "Nenhuma programação selecionada.")
            else:
                cfg2.number_input(
                    "Limite máximo de BTs no automático",
                    min_value=1,
                    step=1,
                    key="max_total_bts",
                )
                cfg2.caption(
                    "Limita as combinações testadas até encontrar a menor frota viável."
                )

            st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)

            # Linha 3: sequenciamento e liberação parcial
            seq1, seq2 = st.columns([1.25, 1.0])
            seq1.checkbox(
                "Sequenciar por início e prioridade",
                key="sequenciar_por_prioridade",
                help=(
                    "Quando ativo, conflitos de mistura, dosagem, frente e BT compartilhada passam a respeitar "
                    "primeiro o horário de início e, em empate, a prioridade informada."
                ),
            )
            seq1.caption(
                "Use para impor uma ordem executiva entre programações concorrentes."
            )
            seq2.checkbox(
                "Permitir liberações parciais de BTs",
                key="liberar_bt_compartilhada_parcialmente",
                disabled=not st.session_state.sequenciar_por_prioridade,
                help=(
                    "Aplica-se apenas a BTs compartilhadas com sequenciamento por prioridade. "
                    "A programação de maior prioridade mantém as BTs até esgotar todas as cargas previstas. "
                    "Depois disso, as BTs que retornarem passam a alimentar a prioridade seguinte."
                ),
            )
            seq2.caption(
                "Repassa BTs compartilhadas após concluir a prioridade atual."
            )

            if st.session_state.get("resultado") is not None and not calculate_disabled:
                st.markdown("<div class='calc-actions-marker'></div>", unsafe_allow_html=True)
                action_calc_col, action_reprog_col = st.columns([1, 1])
                with action_calc_col:
                    calcular = st.button(
                        "Calcular",
                        use_container_width=True,
                        type="primary",
                        disabled=calculate_disabled,
                    )
                with action_reprog_col:
                    if st.button("Reprogramar", use_container_width=True):
                        st.session_state.show_reprogramming_section = True
                        st.session_state["base_result_default_tab"] = "Resumo executivo"
                        st.rerun()
            else:
                calcular = st.button(
                    "Calcular",
                    use_container_width=True,
                    type="primary",
                    disabled=calculate_disabled,
                )

            if calculation_time_errors:
                st.error("Corrija os horários inválidos para habilitar o cálculo.")
        if st.session_state.get("resultado") is not None and st.session_state.get("show_reprogramming_section", False):
            _render_reprogramming_section(st.session_state.resultado)
    else:
        _go_to_page("cenario")
        st.rerun()

    if calcular:
        try:
            _run_current_calculation()
            st.rerun()
        except Exception as exc:
            st.session_state.resultado = None
            st.session_state.last_calculated_signature = ""
            st.session_state.show_reprogramming_section = False
            st.session_state.resultado_reprogramado = None
            st.session_state.reprogramacao_meta = None
            st.error(str(exc))

    if current_page == "planejamento" and _has_active_scenario():
        _autosave_current_scenario_if_needed()

    if current_page == "planejamento" and st.session_state.get("resultado") is not None:
        st.markdown("<div class='main-section-gap'></div>", unsafe_allow_html=True)
        _render_result(
            st.session_state.resultado,
            widget_prefix="base",
            expanded=not bool(st.session_state.get("show_reprogramming_section", False)),
        )
        if st.session_state.get("resultado_reprogramado") is not None:
            meta = st.session_state.get("reprogramacao_meta") or {}
            helper_parts = ["Resultado recalculado a partir de marco observado do ciclo."]
            if meta.get("programacao"):
                helper_parts.append(
                    f"Programação: {meta['programacao']} | Viagem: V{int(meta['numero_viagem']):02d}"
                )
            if meta.get("reference_label"):
                helper_parts.append(f"Marco: {meta['reference_label']}")
            if meta.get("planned_reference") and meta.get("observed_reference"):
                helper_parts.append(
                    "Planejado: "
                    f"{format_clock(meta['planned_reference'], st.session_state.resultado.data_base)} | "
                    "Observado: "
                    f"{format_clock(meta['observed_reference'], st.session_state.resultado.data_base)} | "
                    "Desvio: "
                    f"{round_minutes(meta['delta_minutes'], 1)} min"
                )
            observed_label = (
                f"Marco observado: {meta['reference_label'].lower()}"
                if meta.get("reference_label")
                else "Marco observado"
            )

            _render_result(
                st.session_state.resultado_reprogramado,
                section_title="Seção 3A — Resultados da reprogramação",
                helper_text=" ".join(helper_parts),
                widget_prefix="reprog",
                gantt_observed_marker=(
                    {
                        "observed_reference": meta.get("observed_reference"),
                        "label": observed_label,
                    }
                    if meta.get("observed_reference") is not None
                    else None
                ),
            )


if __name__ == "__main__":
    main()
