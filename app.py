from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import date, time
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from calculator.engine import calcular_dimensionamento_minimo, simular_ciclo_bt
from calculator.gantt import gerar_disponibilidade_bt, gerar_gantt, gerar_tabela_disponibilidade_bt
from calculator.models import Concretagem
from calculator.utils import format_clock, parse_time_value, round_minutes, safe_identifier
from exports.csv_export import (
    exportar_detalhamento_csv,
    exportar_programacao_cenario_csv,
    importar_programacao_cenario_csv,
)


BASE_DIR = Path(__file__).resolve().parent
SAVED_SCENARIOS_PATH = BASE_DIR / "sample_data" / "saved_scenarios.json"
TURNO_OPTIONS = ["Diurno", "Noturno"]


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
        .section-helper {
            color: #5f6b7a;
            font-size: 0.95rem;
            margin-top: -0.35rem;
            margin-bottom: 0.9rem;
        }
        .page-separator {
            height: 1px;
            background: rgba(255, 255, 255, 0.1);
            margin: 1.1rem 0 1.4rem 0;
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
        }
        .scenario-meta-preview {
            padding: 0.15rem 0 0.55rem 0;
            color: #5f6b7a;
            font-size: 0.94rem;
        }
        .result-status-card {
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 12px;
            padding: 0.8rem 0.9rem;
            min-height: 92px;
            background: rgba(255, 255, 255, 0.04);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
        }
        .result-status-card .label {
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: rgba(255, 255, 255, 0.82);
            margin-bottom: 0.3rem;
        }
        .result-status-card .value {
            font-size: 1.35rem;
            font-weight: 700;
            line-height: 1.15;
            margin-bottom: 0.2rem;
            color: #ffffff;
        }
        .result-status-card .subvalue {
            font-size: 0.88rem;
            color: rgba(255, 255, 255, 0.88);
        }
        .result-status-card.ok {
            border-color: rgba(76, 175, 80, 0.42);
            background: rgba(25, 60, 34, 0.9);
        }
        .result-status-card.warn {
            border-color: rgba(255, 167, 38, 0.42);
            background: rgba(58, 40, 18, 0.92);
        }
        .result-status-card.bad {
            border-color: rgba(239, 83, 80, 0.42);
            background: rgba(58, 24, 28, 0.92);
        }
        .result-status-card.info {
            border-color: rgba(100, 181, 246, 0.42);
            background: rgba(23, 42, 64, 0.92);
        }
        .result-kicker {
            font-size: 0.84rem;
            color: #5f6b7a;
            margin-bottom: 0.85rem;
        }
        .result-box {
            border: 1px solid rgba(128, 128, 128, 0.16);
            border-radius: 12px;
            padding: 0.85rem 1rem;
            background: rgba(127, 127, 127, 0.04);
            margin: 0.75rem 0 1rem 0;
        }
        .result-box .title {
            font-size: 0.9rem;
            font-weight: 700;
            margin-bottom: 0.45rem;
        }
        .result-box .subtitle {
            font-size: 0.8rem;
            font-weight: 700;
            color: rgba(255, 255, 255, 0.82);
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
            border: 1px solid rgba(128, 128, 128, 0.16);
            border-radius: 10px;
            padding: 0.7rem 0.9rem;
            background: rgba(127, 127, 127, 0.035);
            margin: 0.55rem 0 0.2rem 0;
        }
        .result-inline-note .title {
            font-size: 0.84rem;
            font-weight: 700;
            margin-bottom: 0.2rem;
        }
        .result-inline-note .body {
            font-size: 0.93rem;
            line-height: 1.45;
        }
        .result-linked-note {
            margin: 0.5rem 0 0 0;
            padding: 0.6rem 0.75rem;
            border-left: 3px solid rgba(255, 255, 255, 0.22);
            border-radius: 0 10px 10px 0;
            background: #273142;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.14);
        }
        .result-linked-note .title {
            font-size: 0.8rem;
            font-weight: 700;
            margin-bottom: 0.18rem;
            color: #ffffff;
        }
        .result-linked-note .body {
            font-size: 0.86rem;
            line-height: 1.42;
            color: #dbe4f0;
        }
        .result-linked-note.ok {
            border-left-color: #52b36a;
            background: #23422c;
        }
        .result-linked-note.warn {
            border-left-color: #d89224;
            background: #4b3a1f;
        }
        .result-linked-note.bad {
            border-left-color: #d95a57;
            background: #4a2b2e;
        }
        .result-linked-note.info {
            border-left-color: #5ba8e8;
            background: #2d4058;
        }
        .result-mini-card {
            border: 1px solid #3b475c;
            border-radius: 10px;
            padding: 0.7rem 0.85rem;
            min-height: 82px;
            background: #273142;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.16);
        }
        .result-mini-card .label {
            font-size: 0.8rem;
            color: #cbd5e1;
            margin-bottom: 0.28rem;
        }
        .result-mini-card .value {
            font-size: 1.1rem;
            font-weight: 700;
            color: #ffffff;
            line-height: 1.1;
        }
        .result-mini-card .subvalue {
            margin-top: 0.22rem;
            font-size: 0.82rem;
            color: #dbe4f0;
        }
        .result-row-gap {
            height: 0.8rem;
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
        @media (prefers-color-scheme: light) {
            .section-helper,
            .result-kicker,
            .scenario-meta-preview {
                color: #4b5563;
            }
            .result-status-card {
                border-color: rgba(15, 23, 42, 0.12);
                background: #f7f8fa;
                box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65);
            }
            .result-status-card .label {
                color: rgba(17, 24, 39, 0.82);
            }
            .result-status-card .value {
                color: #111827;
            }
            .result-status-card .subvalue {
                color: rgba(17, 24, 39, 0.76);
            }
            .result-status-card.ok {
                border-color: rgba(46, 125, 50, 0.34);
                background: #edf7ee;
            }
            .result-status-card.warn {
                border-color: rgba(180, 83, 9, 0.34);
                background: #fff4e5;
            }
            .result-status-card.bad {
                border-color: rgba(185, 28, 28, 0.30);
                background: #fdecec;
            }
            .result-status-card.info {
                border-color: rgba(37, 99, 235, 0.28);
                background: #edf5ff;
            }
            .result-box {
                border-color: rgba(15, 23, 42, 0.12);
                background: #f7f8fa;
            }
            .result-box .subtitle {
                color: #374151;
            }
            .result-inline-note {
                border-color: rgba(15, 23, 42, 0.12);
                background: #f7f8fa;
            }
        }
        @media (max-width: 768px) {
            .stApp h1 {
                font-size: 2rem !important;
                line-height: 1.08;
            }
            .stApp h2 {
                font-size: 1.45rem !important;
            }
            .stApp h3 {
                font-size: 1.15rem !important;
            }
            .active-scenario-box {
                min-height: unset;
                line-height: 1.3;
                align-items: flex-start;
                flex-wrap: wrap;
            }
            .section-helper,
            .scenario-meta-preview,
            .result-kicker {
                font-size: 0.88rem;
                margin-bottom: 0.65rem;
            }
            div[data-testid="stHorizontalBlock"] {
                gap: 0.55rem !important;
            }
            div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
                width: 100% !important;
                min-width: 0 !important;
                flex: 1 1 100% !important;
            }
            div[data-testid="stButton"] button {
                width: 100%;
            }
            .result-status-card,
            .result-mini-card,
            .result-box,
            .result-inline-note,
            .result-linked-note {
                padding: 0.7rem 0.8rem;
            }
            .result-status-card,
            .result-mini-card {
                min-height: unset;
            }
            .result-status-card .value {
                font-size: 1.22rem;
            }
            .result-status-card .subvalue,
            .result-mini-card .subvalue,
            .result-linked-note .body {
                font-size: 0.82rem;
            }
            .result-mini-card .value {
                font-size: 1.02rem;
            }
            .result-linked-note,
            .result-inline-note,
            .result-box {
                margin-top: 0.45rem;
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
            iframe[title^="streamlit"] {
                max-width: 100%;
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


def _render_section_heading(title: str, helper_text: str) -> None:
    st.subheader(title)
    st.markdown(f"<div class='section-helper'>{helper_text}</div>", unsafe_allow_html=True)


def _render_subsection_heading(title: str, helper_text: str) -> None:
    st.markdown(f"**{title}**")
    st.caption(helper_text)


def _apply_detail_filters(dataframe: pd.DataFrame) -> pd.DataFrame:
    filtered = dataframe.copy()
    with st.expander("Filtros da tabela", expanded=False):
        st.caption("Refine o detalhamento por programação, BT, viagem, etapa ou busca textual.")
        c1, c2, c3, c4 = st.columns(4)

        programacoes = []
        if "Programação" in filtered.columns:
            programacoes = c1.multiselect(
                "Programação",
                options=sorted(filtered["Programação"].dropna().unique().tolist()),
                key="detalhamento_filter_programacao",
            )

        bts = []
        if "BT" in filtered.columns:
            bts = c2.multiselect(
                "BT",
                options=sorted(filtered["BT"].dropna().unique().tolist()),
                key="detalhamento_filter_bt",
            )

        viagens = []
        if "Viagem" in filtered.columns:
            viagens = c3.multiselect(
                "Viagem",
                options=sorted(filtered["Viagem"].dropna().unique().tolist()),
                key="detalhamento_filter_viagem",
            )

        etapas = []
        if "Etapa" in filtered.columns:
            etapas = c4.multiselect(
                "Etapa",
                options=sorted(filtered["Etapa"].dropna().unique().tolist()),
                key="detalhamento_filter_etapa",
            )

        busca_textual = st.text_input(
            "Busca textual",
            value=st.session_state.get("detalhamento_filter_busca", ""),
            placeholder="Ex.: descarga, bomba, V03, D20 P6, aguardando...",
            key="detalhamento_filter_busca",
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
            "<span style='display:inline;color:#c9f2d0;font-size:0.76rem;font-weight:700;"
            "margin-right:0.5rem;text-transform:uppercase;letter-spacing:0.04em;'>"
            "Cenário ativo:</span>"
            f"<span style='color:#ffffff;font-weight:700;'>{_current_scenario_label()}</span>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _default_payload(index: int) -> dict:
    return {
        "id": f"concretagem-{index}",
        "nome_programacao": f"Programação {index}",
        "local": "Serra das Araras",
        "elemento_frente": f"Frente {index}",
        "usina": "Usina Serra",
        "tipo_cimento": "CP V-ARI",
        "observacoes": "",
        "volume_total_m3": 24.0,
        "capacidade_bt_m3": 8.0,
        "numero_bts_fixo": 0,
        "inicio_primeira_mistura": "07:00",
        "prioridade": 0,
        "prazo_limite_descarga": None,
        "ciclo": {
            "mistura_min": 10.0,
            "dosagem_min": 6.0,
            "ida_min": 25.0,
            "slump_min": 5.0,
            "descarga_min": 18.0,
            "lavagem_min": 10.0,
            "volta_min": 22.0,
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


def _ensure_saved_scenarios_file() -> None:
    if SAVED_SCENARIOS_PATH.exists():
        return
    SAVED_SCENARIOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SAVED_SCENARIOS_PATH.write_text(
        json.dumps(_default_saved_scenarios_file(), ensure_ascii=False, indent=2),
        encoding="utf-8",
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


def _load_saved_scenarios() -> list[dict]:
    _ensure_saved_scenarios_file()
    with SAVED_SCENARIOS_PATH.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    raw_scenarios = payload.get("scenarios", [])
    normalized_scenarios = [_normalize_scenario_record(item) for item in raw_scenarios]
    if normalized_scenarios != raw_scenarios:
        _write_saved_scenarios(normalized_scenarios)
    return normalized_scenarios


def _write_saved_scenarios(scenarios: list[dict]) -> None:
    scenarios = [_normalize_scenario_record(item) for item in scenarios]
    SAVED_SCENARIOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SAVED_SCENARIOS_PATH.write_text(
        json.dumps({"scenarios": scenarios}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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


def _apply_payloads(
    payloads: list[dict],
    mode: str | None = None,
    max_total_bts: int | None = None,
    sequenciar_por_prioridade: bool | None = None,
) -> None:
    st.session_state.scenario_payloads = payloads

    for index, payload in enumerate(payloads, start=1):
        ciclo = payload.get("ciclo", {})
        restricoes = payload.get("restricoes", {})
        st.session_state[_widget_key(index, "nome_programacao")] = payload.get(
            "nome_programacao", f"Programação {index}"
        )
        st.session_state[_widget_key(index, "local")] = payload.get("local", "")
        st.session_state[_widget_key(index, "elemento_frente")] = payload.get("elemento_frente", "")
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
        st.session_state[_widget_key(index, "prioridade")] = int(payload.get("prioridade", 0) or 0)
        st.session_state[_widget_key(index, "usar_prazo")] = payload.get("prazo_limite_descarga") is not None
        st.session_state[_widget_key(index, "prazo_limite_descarga")] = parse_time_value(
            payload.get("prazo_limite_descarga")
        ) or time(12, 0)

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


def _ensure_defaults(index: int, payload: dict) -> None:
    if _widget_key(index, "nome_programacao") in st.session_state:
        return
    _apply_payloads(st.session_state.scenario_payloads)


def _snapshot_payloads_from_state() -> list[dict]:
    payloads = []
    for index, payload in enumerate(st.session_state.scenario_payloads, start=1):
        if _widget_key(index, "nome_programacao") in st.session_state:
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
        "payloads": payloads,
    }


def _apply_saved_scenario(record: dict) -> None:
    record = _normalize_scenario_record(record)
    _apply_payloads(
        record.get("payloads") or [_default_payload(1)],
        mode=record.get("calc_mode", "fixo"),
        max_total_bts=record.get("max_total_bts", 12),
        sequenciar_por_prioridade=record.get("sequenciar_por_prioridade", False),
    )
    st.session_state.pending_focus_program_index = 0
    st.session_state.resultado = None
    _set_current_scenario_metadata(
        scenario_date=date.fromisoformat(record.get("date", date.today().isoformat())),
        turno=record.get("turno", "Diurno"),
        scenario_id=record.get("id"),
    )
    st.session_state.current_scenario_name = (record.get("name") or "").strip() or "Cenário"
    st.session_state.selected_saved_scenario_id = record.get("id", "")
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
    st.session_state.current_scenario_name = record["name"]
    return record["id"]


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
    )
    st.session_state.pending_focus_program_index = 0
    _set_current_scenario_metadata(scenario_date, turno, "")
    st.session_state.current_scenario_name = scenario_name
    saved_id = _save_current_scenario()
    st.session_state.selected_saved_scenario_id = saved_id
    st.session_state.resultado = None
    st.session_state.current_page = "planejamento"
    st.session_state.toast_message = "Cenário criado com sucesso."


def _clear_active_scenario() -> None:
    st.session_state.scenario_payloads = []
    st.session_state.resultado = None
    st.session_state.current_scenario_id = ""
    st.session_state.current_scenario_name = ""
    st.session_state.selected_saved_scenario_id = ""
    st.session_state.pending_focus_program_index = None
    st.session_state.current_page = "cenario"


def _duplicate_saved_scenario(record: dict) -> None:
    _apply_payloads(
        record.get("payloads") or [_default_payload(1)],
        mode=record.get("calc_mode", "fixo"),
        max_total_bts=record.get("max_total_bts", 12),
        sequenciar_por_prioridade=record.get("sequenciar_por_prioridade", False),
    )
    st.session_state.pending_focus_program_index = 0
    _set_current_scenario_metadata(
        scenario_date=date.fromisoformat(record.get("date", date.today().isoformat())),
        turno=record.get("turno", "Diurno"),
        scenario_id="",
    )
    base_name = (record.get("name") or "").strip() or "Cenário"
    st.session_state.current_scenario_name = f"{_normalize_duplicate_name(base_name)} (cópia)"
    st.session_state.selected_saved_scenario_id = ""
    st.session_state.resultado = None
    st.session_state.current_page = "planejamento"
    st.session_state.toast_message = (
        "Cenário duplicado. Ajuste os dados e salve para criar uma nova simulação."
    )


def _import_scenario_record(record: dict) -> None:
    _apply_payloads(
        record.get("payloads") or [_default_payload(1)],
        mode=record.get("calc_mode", "fixo"),
        max_total_bts=record.get("max_total_bts", 12),
        sequenciar_por_prioridade=record.get("sequenciar_por_prioridade", False),
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
    st.session_state.current_page = "planejamento"
    st.session_state.toast_message = "Cenário importado com sucesso."


def _delete_current_scenario() -> None:
    current_id = st.session_state.get("current_scenario_id", "").strip()
    if current_id:
        scenarios = _load_saved_scenarios()
        scenarios = [item for item in scenarios if item.get("id") != current_id]
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


def _queue_import_scenario(record: dict) -> None:
    st.session_state.pending_scenario_action = {"type": "import", "record": record}


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


def _process_pending_selected_scenario() -> None:
    selected_id = st.session_state.pop("pending_selected_saved_scenario_id", None)
    if selected_id is not None:
        st.session_state.selected_saved_scenario_id = selected_id


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
        st.session_state.selected_saved_scenario_id = ""
        st.session_state.scenario_form_synced_from_active = True
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
        const syncProgramTab = () => {
          const tablists = window.parent.document.querySelectorAll('[role="tablist"]');
          if (!tablists.length) return;
          const buttons = tablists[0].querySelectorAll('button[role="tab"]');
          buttons.forEach((button, index) => {
            if (button.dataset.programTrackingBound === "true") return;
            button.dataset.programTrackingBound = "true";
            button.addEventListener("click", () => {
              const url = new URL(window.parent.location.href);
              url.searchParams.set("programa", String(index));
              window.parent.history.replaceState({}, "", url.toString());
            });
          });
        };
        setTimeout(syncProgramTab, 80);
        </script>
        """,
        height=0,
    )


def _render_pending_program_focus() -> None:
    target_index = st.session_state.get("pending_focus_program_index")
    if target_index is None:
        return
    st.query_params["programa"] = str(int(target_index))
    components.html(
        f"""
        <script>
        const focusTab = () => {{
          const tablists = window.parent.document.querySelectorAll('[role="tablist"]');
          if (!tablists.length) return;
          const buttons = tablists[0].querySelectorAll('button[role="tab"]');
          const target = buttons[{int(target_index)}];
          if (target) target.click();
        }};
        setTimeout(focusTab, 80);
        </script>
        """,
        height=0,
    )
    st.session_state.pending_focus_program_index = None


def _read_payload_from_widgets(index: int) -> dict:
    usar_prazo = st.session_state[_widget_key(index, "usar_prazo")]
    primeira_custom = st.session_state[_widget_key(index, "permitir_primeira_viagem_customizada")]
    return {
        "id": f"concretagem-{index}",
        "nome_programacao": st.session_state[_widget_key(index, "nome_programacao")],
        "local": st.session_state[_widget_key(index, "local")],
        "elemento_frente": st.session_state[_widget_key(index, "elemento_frente")],
        "usina": st.session_state[_widget_key(index, "usina")],
        "tipo_cimento": st.session_state[_widget_key(index, "tipo_cimento")],
        "observacoes": st.session_state[_widget_key(index, "observacoes")],
        "volume_total_m3": st.session_state[_widget_key(index, "volume_total_m3")],
        "capacidade_bt_m3": st.session_state[_widget_key(index, "capacidade_bt_m3")],
        "numero_bts_fixo": st.session_state[_widget_key(index, "numero_bts_fixo")],
        "inicio_primeira_mistura": st.session_state[_widget_key(index, "inicio_primeira_mistura")].strftime(
            "%H:%M"
        ),
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


def _render_scenario_form(index: int, payload: dict) -> None:
    _ensure_defaults(index, payload)

    with st.container(border=True):
        _render_subsection_heading(
            "Identificação",
            "Dados gerais da programação, frente e observações da concretagem.",
        )
        col1, col2 = st.columns([1.2, 1.0])
        with col1:
            st.text_input("Nome da programação", key=_widget_key(index, "nome_programacao"))
            st.text_input("Elemento / frente", key=_widget_key(index, "elemento_frente"))
            st.text_input("Local", key=_widget_key(index, "local"))
            st.text_input("Usina", key=_widget_key(index, "usina"))
        with col2:
            st.text_input("Tipo de cimento", key=_widget_key(index, "tipo_cimento"))
            st.text_area(
                "Observações",
                key=_widget_key(index, "observacoes"),
                height=140,
            )

    st.write("")

    with st.container(border=True):
        _render_subsection_heading(
            "Dados operacionais",
            "Volumes, capacidade da frota e horários-base da operação.",
        )
        op1, op2, op3 = st.columns(3)
        op1.number_input(
            "Volume total da concretagem (m³)",
            min_value=0.0,
            step=1.0,
            key=_widget_key(index, "volume_total_m3"),
        )
        op2.number_input(
            "Capacidade da BT (m³)",
            min_value=0.0,
            step=0.5,
            key=_widget_key(index, "capacidade_bt_m3"),
        )
        op3.time_input(
            "Início da 1ª mistura",
            key=_widget_key(index, "inicio_primeira_mistura"),
            step=300,
        )

        op4, op5, op6, op7 = st.columns([1, 1, 1, 1.2])
        op4.checkbox(
            "Usar prazo limite de descarga",
            key=_widget_key(index, "usar_prazo"),
        )
        op5.time_input(
            "Prazo limite para término da descarga",
            key=_widget_key(index, "prazo_limite_descarga"),
            step=300,
            disabled=not st.session_state[_widget_key(index, "usar_prazo")],
        )
        op6.number_input(
            "BTs fixas disponíveis (0 = opcional)",
            min_value=0,
            step=1,
            key=_widget_key(index, "numero_bts_fixo"),
        )
        op7.number_input(
            "Prioridade (0 = sem prioridade; 1 = maior)",
            min_value=0,
            step=1,
            key=_widget_key(index, "prioridade"),
            help="Use 0 quando a programação não precisar de prioridade no sequenciamento.",
        )

    st.write("")

    with st.container(border=True):
        _render_subsection_heading(
            "Configuração da operação",
            "Restrições de simultaneidade e regras de operação na usina e na frente.",
        )
        cfg1, cfg2, cfg3, cfg4 = st.columns(4)
        cfg1.radio(
            "Operação",
            options=["Com bomba", "Sem bomba"],
            key=_widget_key(index, "com_bomba"),
            horizontal=True,
        )
        cfg2.number_input(
            "BTs simultâneas na bomba / frente",
            min_value=1,
            step=1,
            key=_widget_key(index, "max_bts_frente"),
        )
        cfg3.number_input(
            "BTs simultâneas na mistura",
            min_value=1,
            step=1,
            key=_widget_key(index, "max_bts_mistura"),
        )
        cfg4.number_input(
            "BTs simultâneas na dosagem",
            min_value=1,
            step=1,
            key=_widget_key(index, "max_bts_dosagem"),
        )

        cfg5, cfg6, cfg7, cfg8 = st.columns([1, 1.1, 1, 1.1])
        cfg5.checkbox(
            "Existe intervalo obrigatório entre misturas?",
            key=_widget_key(index, "existe_intervalo_entre_misturas"),
        )
        cfg6.number_input(
            "Intervalo entre misturas (min)",
            min_value=0.0,
            step=1.0,
            key=_widget_key(index, "intervalo_entre_misturas_min"),
            disabled=not st.session_state[_widget_key(index, "existe_intervalo_entre_misturas")],
        )
        cfg7.checkbox(
            "Controlar intervalo máximo entre descargas?",
            key=_widget_key(index, "existe_intervalo_maximo_entre_descargas"),
        )
        cfg8.number_input(
            "Intervalo máximo entre descargas (min)",
            min_value=0.0,
            step=1.0,
            key=_widget_key(index, "intervalo_maximo_entre_descargas_min"),
            disabled=not st.session_state[
                _widget_key(index, "existe_intervalo_maximo_entre_descargas")
            ],
        )

    st.write("")

    with st.container(border=True):
        _render_subsection_heading(
            "Tempos do ciclo (minutos)",
            "Tempos básicos usados na simulação de cada viagem da betoneira.",
        )
        ciclo1, ciclo2, ciclo3, ciclo4 = st.columns(4)
        ciclo1.number_input("Mistura", min_value=0.0, step=1.0, key=_widget_key(index, "mistura_min"))
        ciclo2.number_input("Dosagem", min_value=0.0, step=1.0, key=_widget_key(index, "dosagem_min"))
        ciclo3.number_input("Ida", min_value=0.0, step=1.0, key=_widget_key(index, "ida_min"))
        ciclo4.number_input("Slump", min_value=0.0, step=1.0, key=_widget_key(index, "slump_min"))

        ciclo5, ciclo6, ciclo7 = st.columns(3)
        ciclo5.number_input("Descarga", min_value=0.0, step=1.0, key=_widget_key(index, "descarga_min"))
        ciclo6.number_input("Lavagem", min_value=0.0, step=1.0, key=_widget_key(index, "lavagem_min"))
        ciclo7.number_input("Volta", min_value=0.0, step=1.0, key=_widget_key(index, "volta_min"))

    st.write("")

    with st.container(border=True):
        _render_subsection_heading(
            "Configurações adicionais",
            "Ajustes finos para primeira viagem, última parcial e compartilhamento de BTs.",
        )
        add1, add2, add3 = st.columns(3)
        add1.checkbox(
            "Última viagem parcial com descarga proporcional",
            key=_widget_key(index, "ultima_viagem_parcial_proporcional"),
        )
        add2.checkbox(
            "Permitir volume customizado na 1ª viagem",
            key=_widget_key(index, "permitir_primeira_viagem_customizada"),
        )
        add3.selectbox(
            "BTs dedicadas ou compartilhadas",
            options=["dedicadas", "compartilhadas"],
            key=_widget_key(index, "alocacao_bts"),
        )

        st.number_input(
            "Volume da 1ª viagem (m³)",
            min_value=0.0,
            step=0.5,
            key=_widget_key(index, "volume_primeira_viagem_m3"),
            disabled=not st.session_state[_widget_key(index, "permitir_primeira_viagem_customizada")],
        )


def _build_concretagens_from_form() -> list[Concretagem]:
    payloads = []
    for index, _payload in enumerate(st.session_state.scenario_payloads, start=1):
        payloads.append(_read_payload_from_widgets(index))
    st.session_state.scenario_payloads = payloads
    return [Concretagem.from_dict(payload, ordem=index - 1) for index, payload in enumerate(payloads, start=1)]


def _render_result(resultado) -> None:
    with st.expander("Seção 3 — Resultados", expanded=True):
        st.markdown(
            "<div class='section-helper'>Resumo executivo, detalhamento operacional, gráfico de gantt e exportações.</div>",
            unsafe_allow_html=True,
        )

        total_volume = sum(item.volume_total_m3 for item in resultado.concretagens)
        total_bt = sum(resultado.bt_counts.values())
        bt_summary = ", ".join(
            f"{label}: {count}"
            for key, count in resultado.bt_counts.items()
            for label in [resultado.bt_group_labels[key]]
        )
        prazo_configurado = any(resumo.get("prazo_raw") is not None for resumo in resultado.resumo)
        restricao_intervalo_ativa = any(
            resumo.get("intervalo_maximo_descargas_min") is not None
            for resumo in resultado.resumo
        )
        bts_sugeridas_continuidade = [
            int(resumo["bts_sugeridas_continuidade"])
            for resumo in resultado.resumo
            if resumo.get("atende_intervalo_descargas") is False
            and resumo.get("bts_sugeridas_continuidade") is not None
        ]
        bt_sugerida_card = max(bts_sugeridas_continuidade) if bts_sugeridas_continuidade else None

        cards1 = st.columns(5)
        modo_valor = "Automático" if resultado.automatico else "Fixo"
        modo_sub = (
            "Menor frota encontrada"
            if resultado.automatico and resultado.dimensionamento_encontrado
            else bt_summary
        )
        with cards1[0]:
            _render_result_status_card(
                "Prazo de descarga",
                (
                    "Atende"
                    if resultado.prazo_atendido
                    else "Não atende"
                ) if prazo_configurado else "N/A",
                (
                    f"Última descarga: {format_clock(resultado.termino_ultima_descarga, resultado.data_base)}"
                    if prazo_configurado
                    else "Nenhum prazo de descarga foi informado"
                ),
                "info" if not prazo_configurado else ("ok" if resultado.prazo_atendido else "bad"),
            )
        with cards1[1]:
            continuidade_value = (
                "Atende"
                if resultado.atende_intervalo_descargas
                else "Não atende"
            ) if restricao_intervalo_ativa else "N/A"
            continuidade_sub = (
                "Sem restrição configurada"
                if not restricao_intervalo_ativa
                else "Intervalo entre descargas verificado"
            )
            _render_result_status_card(
                "Continuidade operacional",
                continuidade_value,
                continuidade_sub,
                "" if not restricao_intervalo_ativa else ("ok" if resultado.atende_intervalo_descargas else "bad"),
            )
        with cards1[2]:
            _render_result_status_card(
                "BTs utilizadas",
                str(total_bt),
                bt_summary,
                "info",
            )
        with cards1[3]:
            _render_result_status_card(
                "Gargalo por espera",
                (
                    "Sem espera relevante"
                    if resultado.gargalo_por_espera == "sem espera"
                    else str(resultado.gargalo_por_espera).capitalize()
                ),
                bt_summary,
                "warn",
            )
        with cards1[4]:
            _render_result_status_card(
                "Recurso mais ocupado",
                str(resultado.recurso_mais_ocupado).capitalize(),
                bt_summary,
                "warn",
            )

        linked_notes = st.columns(5)
        with linked_notes[0]:
            if not prazo_configurado:
                _render_result_linked_note(
                    "Prazo",
                    "Nenhuma programação deste cenário possui prazo limite de descarga configurado.",
                    "info",
                )
            elif resultado.prazo_atendido:
                _render_result_linked_note(
                    "Prazo",
                    "O cenário atende todos os prazos de descarga informados.",
                    "ok",
                )
            else:
                _render_result_linked_note(
                    "Prazo",
                    "O cenário não atende pelo menos um dos prazos de descarga informados.",
                    "bad",
                )

        with linked_notes[1]:
            if restricao_intervalo_ativa:
                if resultado.atende_intervalo_descargas:
                    _render_result_linked_note(
                        "Continuidade",
                        "Os intervalos entre descargas atendem a restrição operacional configurada.",
                        "ok",
                    )
                else:
                    _render_result_linked_note(
                        "Continuidade",
                        "Os intervalos entre descargas não atendem a restrição operacional configurada.",
                        "bad",
                    )
                    for intervalo in resultado.intervalos_descarga:
                        if not intervalo["violacao"]:
                            continue
                        _render_result_linked_note(
                            "Violação de continuidade",
                            (
                                f"{intervalo['frente_label']}: intervalo de "
                                f"{round_minutes(intervalo['intervalo_min'], 1)} min entre "
                                f"{format_clock(intervalo['fim_descarga_anterior'], resultado.data_base)} "
                                "e "
                                f"{format_clock(intervalo['inicio_proxima_descarga'], resultado.data_base)} "
                                f"(limite {round_minutes(intervalo['limite_min'], 1)} min)."
                            ),
                            "bad",
                        )

        with linked_notes[2]:
            if resultado.automatico and resultado.dimensionamento_encontrado:
                _render_result_linked_note(
                    "Dimensionamento",
                    f"Dimensionamento mínimo encontrado. {bt_summary}.",
                    "ok",
                )
            elif resultado.automatico:
                _render_result_linked_note(
                    "Dimensionamento",
                    f"Dimensionamento mínimo não encontrado dentro do limite testado. {bt_summary}.",
                    "warn",
                )
            else:
                _render_result_linked_note(
                    "Simulação",
                    f"Simulação com BT fixa executada. {bt_summary}.",
                    "info",
                )

        with linked_notes[3]:
            if resultado.gargalo_por_espera == "sem espera":
                _render_result_linked_note(
                    "Espera",
                    "Não houve fila relevante no cenário calculado; o card ao lado mostra o recurso mais ocupado no cronograma final.",
                    "info",
                )
        with linked_notes[4]:
            if resultado.sequenciamento_prioridade_ativo:
                _render_result_linked_note(
                    "Sequenciamento",
                    "Prioridade ativa. A ordem segue o início da 1ª mistura e, em empate, prioridade, prazo e ordem de cadastro.",
                    "info",
                )
            for warning in resultado.warnings:
                _render_result_linked_note(
                    "Atenção",
                    warning,
                    "warn",
                )

        st.markdown("<div class='result-row-gap'></div>", unsafe_allow_html=True)

        cards2 = st.columns(6 if bt_sugerida_card is not None else 5)
        with cards2[0]:
            _render_result_mini_card(
                "Modo de cálculo",
                modo_valor,
                modo_sub,
            )
        with cards2[1]:
            _render_result_mini_card(
                "Volume total",
                f"{round_minutes(total_volume, 2)} m³",
                "Somatório de todas as programações calculadas",
            )
        with cards2[2]:
            _render_result_mini_card(
                "Viagens",
                str(len(resultado.viagens)),
                "Total de viagens geradas na simulação",
            )
        with cards2[3]:
            _render_result_mini_card(
                "Última descarga",
                format_clock(resultado.termino_ultima_descarga, resultado.data_base),
                "Horário principal de atendimento ao prazo",
            )
        with cards2[4]:
            _render_result_mini_card(
                "Última viagem",
                format_clock(resultado.termino_ultima_viagem, resultado.data_base),
                "Inclui lavagem e retorno da última BT",
            )
        if bt_sugerida_card is not None:
            with cards2[5]:
                _render_result_mini_card(
                    "BTs sugeridas",
                    str(bt_sugerida_card),
                    "Referência visual para atender continuidade",
                )

        st.markdown("<div class='result-row-gap'></div>", unsafe_allow_html=True)

        if resultado.recomendacoes_ajuste:
            _render_result_box(
                "O que pode ser alterado para atender as restrições do cenário",
                resultado.recomendacoes_ajuste,
            )

        resumo_tab, tabela_tab, gantt_tab, disponibilidade_tab, premissas_tab = st.tabs(
            [
                "Resumo executivo",
                "Tabela detalhada",
                "Gantt operacional",
                "Disponibilidade de BT",
                "Premissas consideradas",
            ]
        )

        with resumo_tab:
            concretagem_lookup = {concretagem.id: concretagem for concretagem in resultado.concretagens}
            for resumo in resultado.resumo:
                with st.expander(resumo["nome_programacao"], expanded=True):
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
                            else gargalo_programacao.capitalize()
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
                        prazo_delta_label = "N/A"
                        if prazo_delta is not None:
                            if prazo_delta <= 0:
                                prazo_delta_label = f"Folga de {round_minutes(abs(prazo_delta), 1)} min"
                            else:
                                prazo_delta_label = f"Atraso de {round_minutes(prazo_delta, 1)} min"

                        resumo_tabela = pd.DataFrame(
                            [
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
                                "Indicador": "Tipo de cimento",
                                "Valor": (
                                    concretagem.tipo_cimento
                                    if concretagem and concretagem.tipo_cimento
                                    else "-"
                                ),
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
                                "Indicador": "BTs da frente",
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
                                "Indicador": "Limite simultâneo na frente",
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
                                "Valor": resumo["inicio_primeira_mistura"].strftime("%H:%M"),
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
                                "Indicador": "Restrições adotadas",
                                "Valor": resumo["restricoes_adotadas"],
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
                        )
                        st.table(resumo_tabela)

        with tabela_tab:
            csv_bytes = exportar_detalhamento_csv(resultado.dataframe_detalhado)
            st.download_button(
                "Baixar CSV do detalhamento",
                data=csv_bytes,
                file_name="detalhamento_concretagens.csv",
                mime="text/csv",
            )
            dataframe_filtrado = _apply_detail_filters(resultado.dataframe_detalhado)
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

        with gantt_tab:
            figura = gerar_gantt(resultado)
            buffer = BytesIO()
            figura.savefig(buffer, format="png", dpi=200, bbox_inches="tight")
            buffer.seek(0)
            st.download_button(
                "Salvar PNG do gantt",
                data=buffer.getvalue(),
                file_name="gantt_concretagens.png",
                mime="image/png",
            )
            st.pyplot(figura, use_container_width=True)

        with disponibilidade_tab:
            figura_disponibilidade = gerar_disponibilidade_bt(resultado)
            tabela_disponibilidade = gerar_tabela_disponibilidade_bt(resultado)
            buffer_disponibilidade = BytesIO()
            figura_disponibilidade.savefig(
                buffer_disponibilidade,
                format="png",
                dpi=200,
                bbox_inches="tight",
            )
            buffer_disponibilidade.seek(0)
            st.download_button(
                "Salvar PNG da disponibilidade de BT",
                data=buffer_disponibilidade.getvalue(),
                file_name="disponibilidade_bt.png",
                mime="image/png",
            )
            st.pyplot(figura_disponibilidade, use_container_width=True)
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
    if "pending_scenario_action" not in st.session_state:
        st.session_state.pending_scenario_action = None
    if "current_page" not in st.session_state:
        st.session_state.current_page = "cenario"
    if "pending_focus_program_index" not in st.session_state:
        st.session_state.pending_focus_program_index = None
    if "confirm_delete_scenario" not in st.session_state:
        st.session_state.confirm_delete_scenario = False
    if "scenario_form_synced_from_active" not in st.session_state:
        st.session_state.scenario_form_synced_from_active = False
    if "active_program_index" not in st.session_state:
        st.session_state.active_program_index = 0

    _inject_styles()

    _process_pending_scenario_action()
    _process_pending_selected_scenario()
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

    st.title("Programações Concretagem – NSA")
    st.caption(
        "Aplicação para planejamento operacional de concretagens, simulação de ciclos e dimensionamento de betoneiras com verificação de prazo e continuidade."
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
            st.markdown("**Cenário em edição**")
            topo1, topo2, topo3, topo4, topo5 = st.columns([1.55, 0.92, 0.82, 0.82, 0.86])
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
            if topo3.button("Salvar cenário", use_container_width=True):
                try:
                    st.session_state.scenario_payloads = _snapshot_payloads_from_state()
                    saved_id = _save_current_scenario()
                    st.session_state.pending_selected_saved_scenario_id = saved_id
                    _queue_load_scenario(saved_id)
                    st.session_state.toast_message = "Cenário salvo com sucesso."
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
            if topo4.button("Excluir cenário", use_container_width=True):
                st.session_state.confirm_delete_scenario = True
                st.rerun()
            if topo5.button("Voltar para cenários", use_container_width=True):
                _go_to_page("cenario")
                st.rerun()

            st.markdown("<div style='height: 0.3rem;'></div>", unsafe_allow_html=True)
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
            st.markdown(
                f"<div class='scenario-meta-preview'>Nome completo do cenário: <strong>{_current_scenario_label()}</strong></div>",
                unsafe_allow_html=True,
            )

        if st.session_state.confirm_delete_scenario:
            message = f"Confirma a exclusão do cenário `{_current_scenario_label()}`?"
            st.warning(message)
            confirm1, confirm2 = st.columns(2)
            if confirm1.button("Confirmar exclusão", use_container_width=True):
                st.session_state.confirm_delete_scenario = False
                _delete_current_scenario()
                st.rerun()
            if confirm2.button("Cancelar", use_container_width=True):
                st.session_state.confirm_delete_scenario = False
                st.rerun()

        st.markdown("<div style='height: 0.9rem;'></div>", unsafe_allow_html=True)

        with st.expander("Seção 1 — Cadastro da concretagem", expanded=True):
            st.markdown(
                "<div class='section-helper'>Cadastre uma ou mais concretagens e organize os dados operacionais de cada frente.</div>",
                unsafe_allow_html=True,
            )
            payloads = _snapshot_payloads_from_state()
            _sync_active_program_from_query(len(payloads))
            active_index = max(0, min(st.session_state.active_program_index, len(payloads) - 1))

            toolbar1, toolbar2, toolbar3 = st.columns([1, 1, 1])
            if toolbar1.button("Adicionar programação", use_container_width=True):
                payloads.append(_default_payload(len(payloads) + 1))
                _apply_payloads(payloads)
                st.session_state.pending_focus_program_index = len(payloads) - 1
                st.rerun()
            if toolbar2.button(
                "Duplicar programação",
                use_container_width=True,
                disabled=len(payloads) == 0,
            ):
                source_index = active_index
                duplicated_payload = deepcopy(payloads[source_index])
                existing_names = [item.get("nome_programacao", "") for item in payloads]
                duplicated_payload["nome_programacao"] = _next_program_copy_name(
                    duplicated_payload.get("nome_programacao", f"Programação {source_index + 1}"),
                    existing_names,
                )
                payloads.insert(source_index + 1, duplicated_payload)
                _apply_payloads(payloads)
                st.session_state.pending_focus_program_index = source_index + 1
                st.rerun()
            if toolbar3.button(
                "Remover programação",
                use_container_width=True,
                disabled=len(st.session_state.scenario_payloads) == 1,
            ):
                updated_payloads = payloads[:active_index] + payloads[active_index + 1 :]
                _apply_payloads(updated_payloads)
                st.session_state.pending_focus_program_index = max(0, len(updated_payloads) - 1)
                if updated_payloads:
                    st.session_state.pending_focus_program_index = max(0, active_index - (1 if active_index == len(payloads) - 1 else 0))
                st.rerun()

            tab_labels = [
                payload.get("nome_programacao", f"Programação {index}")
                for index, payload in enumerate(st.session_state.scenario_payloads, start=1)
            ]
            tabs = st.tabs(tab_labels)
            for index, (tab, payload) in enumerate(
                zip(tabs, st.session_state.scenario_payloads),
                start=1,
            ):
                with tab:
                    _render_scenario_form(index, payload)
            _render_program_tab_tracking()
            _render_pending_program_focus()

        st.write("")

        with st.expander("Seção 2 — Configuração do cálculo", expanded=True):
            st.markdown(
                "<div class='section-helper'>Escolha entre simulação com frota fixa ou dimensionamento automático antes de calcular.</div>",
                unsafe_allow_html=True,
            )
            cfg1, cfg2 = st.columns([1.3, 1.0])
            cfg1.radio(
                "Modo de cálculo",
                options=["fixo", "automatico"],
                format_func=lambda item: (
                    "Simulação com BT fixa" if item == "fixo" else "Dimensionamento automático"
                ),
                horizontal=True,
                key="calc_mode",
            )
            cfg1.caption(
                "Fixo simula a frota informada. Automático procura a menor frota que atenda as restrições do cenário."
            )
            cfg2.number_input(
                "Limite máximo de BTs no automático",
                min_value=1,
                step=1,
                key="max_total_bts",
            )
            cfg2.caption("Usado apenas no modo automático para limitar as composições testadas.")
            st.checkbox(
                "Sequenciar programações por horário de início e prioridade quando houver conflito de recursos da operação",
                key="sequenciar_por_prioridade",
                help=(
                    "Quando ativo, conflitos de mistura, dosagem, frente e BT compartilhada passam a respeitar "
                    "primeiro o horário de início e, em empate, a prioridade informada."
                ),
            )

            calcular = st.button("Calcular", use_container_width=True, type="primary")
    else:
        _go_to_page("cenario")
        st.rerun()

    if calcular:
        try:
            concretagens = _build_concretagens_from_form()
            if st.session_state.calc_mode == "automatico":
                resultado = calcular_dimensionamento_minimo(
                    concretagens,
                    base_date=st.session_state.current_scenario_date,
                    max_total_bts=int(st.session_state.max_total_bts),
                    sequenciar_por_prioridade=bool(st.session_state.sequenciar_por_prioridade),
                )
            else:
                resultado = simular_ciclo_bt(
                    concretagens,
                    base_date=st.session_state.current_scenario_date,
                    sequenciar_por_prioridade=bool(st.session_state.sequenciar_por_prioridade),
                )
            st.session_state.resultado = resultado
        except Exception as exc:
            st.session_state.resultado = None
            st.error(str(exc))

    if current_page == "planejamento" and st.session_state.get("resultado") is not None:
        _render_result(st.session_state.resultado)


if __name__ == "__main__":
    main()
