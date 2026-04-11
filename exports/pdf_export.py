from __future__ import annotations

import os
import tempfile
from io import BytesIO
from textwrap import fill
from datetime import datetime
from pathlib import Path

MPL_CONFIG_DIR = Path(tempfile.gettempdir()) / "serra_araras_mplconfig"
MPL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPL_CONFIG_DIR))

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from calculator.gantt import gerar_disponibilidade_bt, gerar_gantt
from calculator.models import ResultadoCalculo
from calculator.utils import format_clock, round_minutes


PDF_PAGE_SIZE = (16.54, 11.69)
PDF_MARGIN_LEFT = 0.055
PDF_MARGIN_RIGHT = 0.975
PDF_MARGIN_TOP = 0.955
PDF_CONTENT_TOP = 0.91
PDF_MARGIN_BOTTOM = 0.065
PDF_CHART_TOP = 0.905


def _wrap_lines(lines: list[str], width: int) -> list[str]:
    wrapped: list[str] = []
    for line in lines:
        if not line:
            continue
        wrapped.extend(fill(line, width=width).splitlines())
    return wrapped


def _summary_lines(resultado: ResultadoCalculo) -> tuple[list[str], list[str], list[str]]:
    total_volume = sum(item.volume_total_m3 for item in resultado.concretagens)
    total_bt = sum(resultado.bt_counts.values())
    bt_summary = ", ".join(
        f"{resultado.bt_group_labels.get(group_key, group_key)}: {count}"
        for group_key, count in resultado.bt_counts.items()
    )
    prazo_configurado = any(resumo.get("prazo_raw") is not None for resumo in resultado.resumo)
    continuidade_configurada = any(
        resumo.get("intervalo_maximo_descargas_min") is not None for resumo in resultado.resumo
    )

    left_lines = [
        f"Modo de cálculo: {'Automático' if resultado.automatico else 'Fixo'}",
        f"Volume total: {round_minutes(total_volume, 2)} m³",
        f"Viagens geradas: {len(resultado.viagens)}",
        f"BTs utilizadas: {total_bt}",
    ]
    if bt_summary:
        left_lines.append(f"Distribuição de BTs: {bt_summary}")

    right_lines = [
        (
            f"Prazo de descarga: {'Atende' if resultado.prazo_atendido else 'Não atende'}"
            if prazo_configurado
            else "Prazo de descarga: N/A"
        ),
        (
            "Continuidade operacional: "
            + ("Atende" if resultado.atende_intervalo_descargas else "Não atende")
            if continuidade_configurada
            else "Continuidade operacional: N/A"
        ),
        (
            f"Última descarga: {format_clock(resultado.termino_ultima_descarga, resultado.data_base)}"
            if resultado.termino_ultima_descarga is not None
            else "Última descarga: -"
        ),
        (
            f"Última viagem: {format_clock(resultado.termino_ultima_viagem, resultado.data_base)}"
            if resultado.termino_ultima_viagem is not None
            else "Última viagem: -"
        ),
        (
            "Gargalo por espera: "
            + ("Sem espera relevante" if resultado.gargalo_por_espera == "sem espera" else resultado.gargalo_por_espera)
        ),
        f"Recurso mais ocupado: {resultado.recurso_mais_ocupado}",
    ]

    program_lines: list[str] = []
    for resumo in resultado.resumo:
        prazo = resumo.get("prazo_raw")
        program_lines.append(
            " | ".join(
                [
                    resumo.get("nome_programacao", "-"),
                    f"BTs: {resumo.get('bt_count', '-')}",
                    f"Viagens: {resumo.get('numero_viagens', '-')}",
                    (
                        f"Prazo: {format_clock(prazo, resultado.data_base)}"
                        if prazo is not None
                        else "Prazo: N/A"
                    ),
                    (
                        "Continuidade: "
                        + (
                            "Atende"
                            if resumo.get("atende_intervalo_descargas") is not False
                            else "Não atende"
                        )
                    ),
                ]
            )
        )

    return left_lines, right_lines, program_lines


def _build_summary_figure(
    resultado: ResultadoCalculo,
    *,
    scenario_label: str,
    helper_text: str = "",
) -> plt.Figure:
    figure = plt.figure(figsize=PDF_PAGE_SIZE, facecolor="white")
    ax = figure.add_axes([0, 0, 1, 1])
    ax.axis("off")

    left_lines, right_lines, program_lines = _summary_lines(resultado)

    figure.text(
        PDF_MARGIN_LEFT,
        PDF_MARGIN_TOP,
        "Relatório operacional",
        fontsize=20,
        fontweight="bold",
        ha="left",
        va="top",
    )
    figure.text(
        PDF_MARGIN_LEFT,
        PDF_CONTENT_TOP,
        scenario_label,
        fontsize=11.5,
        color="#3b4a5a",
        ha="left",
        va="top",
    )
    figure.text(
        PDF_MARGIN_RIGHT,
        PDF_MARGIN_TOP,
        datetime.now().strftime("Gerado em %d/%m/%Y %H:%M"),
        fontsize=9.5,
        color="#5f6b7a",
        ha="right",
        va="top",
    )

    y_cursor = 0.865
    if helper_text.strip():
        wrapped_helper = _wrap_lines([helper_text.strip()], width=110)
        figure.text(
            PDF_MARGIN_LEFT,
            y_cursor,
            "\n".join(wrapped_helper),
            fontsize=10.2,
            color="#485564",
            ha="left",
            va="top",
        )
        y_cursor -= 0.032 * len(wrapped_helper) + 0.028

    figure.text(PDF_MARGIN_LEFT, y_cursor, "Indicadores gerais", fontsize=13, fontweight="bold", ha="left", va="top")
    y_cursor -= 0.04
    figure.text(
        PDF_MARGIN_LEFT,
        y_cursor,
        "\n".join(_wrap_lines(left_lines, width=48)),
        fontsize=10.8,
        color="#263648",
        ha="left",
        va="top",
    )
    figure.text(
        0.53,
        y_cursor,
        "\n".join(_wrap_lines(right_lines, width=50)),
        fontsize=10.8,
        color="#263648",
        ha="left",
        va="top",
    )

    y_cursor -= max(len(_wrap_lines(left_lines, 48)), len(_wrap_lines(right_lines, 50))) * 0.028 + 0.04

    figure.text(PDF_MARGIN_LEFT, y_cursor, "Programações calculadas", fontsize=13, fontweight="bold", ha="left", va="top")
    y_cursor -= 0.04
    wrapped_program_lines = _wrap_lines(program_lines, width=118)
    figure.text(
        PDF_MARGIN_LEFT,
        y_cursor,
        "\n".join(wrapped_program_lines),
        fontsize=10.4,
        color="#263648",
        ha="left",
        va="top",
    )
    y_cursor -= len(wrapped_program_lines) * 0.026 + 0.035

    warnings = list(resultado.warnings or [])
    recommendations = list(resultado.recomendacoes_ajuste or [])
    if warnings:
        figure.text(PDF_MARGIN_LEFT, y_cursor, "Alertas do cálculo", fontsize=13, fontweight="bold", ha="left", va="top")
        y_cursor -= 0.038
        warning_lines = _wrap_lines(warnings[:5], width=118)
        figure.text(
            PDF_MARGIN_LEFT,
            y_cursor,
            "\n".join(warning_lines),
            fontsize=10.2,
            color="#5a3b2d",
            ha="left",
            va="top",
        )
        y_cursor -= len(warning_lines) * 0.026 + 0.03

    if recommendations:
        figure.text(PDF_MARGIN_LEFT, y_cursor, "Recomendações", fontsize=13, fontweight="bold", ha="left", va="top")
        y_cursor -= 0.038
        recommendation_lines = _wrap_lines(recommendations[:5], width=118)
        figure.text(
            PDF_MARGIN_LEFT,
            y_cursor,
            "\n".join(recommendation_lines),
            fontsize=10.2,
            color="#2f4e3d",
            ha="left",
            va="top",
        )

    return figure


def _normalize_pdf_figure_size(figure: plt.Figure, *, chart_layout: bool = False) -> plt.Figure:
    figure.set_size_inches(*PDF_PAGE_SIZE, forward=True)
    if chart_layout:
        figure.subplots_adjust(
            left=PDF_MARGIN_LEFT,
            right=PDF_MARGIN_RIGHT,
            top=PDF_CHART_TOP,
            bottom=PDF_MARGIN_BOTTOM,
        )
    suptitle = getattr(figure, "_suptitle", None)
    if suptitle is not None:
        suptitle.set_position((PDF_MARGIN_LEFT, PDF_MARGIN_TOP))
    return figure


def exportar_relatorio_operacional_pdf(
    resultado: ResultadoCalculo,
    *,
    scenario_label: str,
    helper_text: str = "",
    observed_marker: dict | None = None,
) -> bytes:
    buffer = BytesIO()
    with PdfPages(buffer) as pdf:
        summary_figure = _build_summary_figure(
            resultado,
            scenario_label=scenario_label,
            helper_text=helper_text,
        )
        pdf.savefig(_normalize_pdf_figure_size(summary_figure))
        plt.close(summary_figure)

        gantt_figure = gerar_gantt(resultado, observed_marker=observed_marker)
        pdf.savefig(_normalize_pdf_figure_size(gantt_figure, chart_layout=True))
        plt.close(gantt_figure)

        disponibilidade_figure = gerar_disponibilidade_bt(resultado)
        pdf.savefig(_normalize_pdf_figure_size(disponibilidade_figure, chart_layout=True))
        plt.close(disponibilidade_figure)

    buffer.seek(0)
    return buffer.getvalue()
