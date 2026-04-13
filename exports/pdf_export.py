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
import pandas as pd
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


def _display_text(value: object) -> str:
    if value is None:
        return "-"
    text = str(value).strip()
    return text if text else "-"


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


def _detailed_summary_dataframe(resultado: ResultadoCalculo) -> pd.DataFrame:
    total_volume = sum(item.volume_total_m3 for item in resultado.concretagens)
    total_bt = sum(resultado.bt_counts.values())
    bt_summary = ", ".join(
        f"{resultado.bt_group_labels.get(group_key, group_key)}: {count}"
        for group_key, count in resultado.bt_counts.items()
    )
    modo_valor = "Automático" if resultado.automatico else "Fixo"
    modo_detalhe = (
        "Menor frota encontrada"
        if resultado.automatico and resultado.dimensionamento_encontrado
        else _display_text(bt_summary)
    )
    prazo_configurado = any(resumo.get("prazo_raw") is not None for resumo in resultado.resumo)
    restricao_intervalo_ativa = any(
        resumo.get("intervalo_maximo_descargas_min") is not None for resumo in resultado.resumo
    )
    programacoes_calculadas = [
        resumo.get("nome_programacao", "-")
        for resumo in resultado.resumo
        if resumo.get("nome_programacao")
    ]
    rows = [
        {
            "Indicador": "Prazo de descarga",
            "Valor": (
                "Atende"
                if resultado.prazo_atendido
                else "Não atende"
            ) if prazo_configurado else "N/A",
            "Detalhe": (
                "Horário limite configurado"
                if prazo_configurado
                else "Nenhum prazo de descarga informado"
            ),
        },
        {
            "Indicador": "Continuidade operacional",
            "Valor": (
                "Atende"
                if resultado.atende_intervalo_descargas
                else "Não atende"
            ) if restricao_intervalo_ativa else "N/A",
            "Detalhe": (
                "Intervalo entre descargas verificado"
                if restricao_intervalo_ativa
                else "Sem restrição de continuidade"
            ),
        },
        {
            "Indicador": "BTs utilizadas",
            "Valor": str(total_bt),
            "Detalhe": _display_text(bt_summary),
        },
        {
            "Indicador": "Gargalo por espera",
            "Valor": (
                "Sem espera relevante"
                if resultado.gargalo_por_espera == "sem espera"
                else _display_text(resultado.gargalo_por_espera)
            ),
            "Detalhe": (
                "Sem espera acumulada relevante"
                if resultado.gargalo_por_espera == "sem espera"
                else "Recurso com maior espera acumulada"
            ),
        },
        {
            "Indicador": "Recurso mais ocupado",
            "Valor": _display_text(resultado.recurso_mais_ocupado),
            "Detalhe": "Maior taxa de ocupação relativa",
        },
        {"Indicador": "Modo de cálculo", "Valor": modo_valor, "Detalhe": modo_detalhe},
        {
            "Indicador": "Programações calculadas",
            "Valor": str(len(programacoes_calculadas)),
            "Detalhe": _display_text(", ".join(programacoes_calculadas)),
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
    ]
    prazos_resumo = [
        resumo.get("prazo_raw")
        for resumo in resultado.resumo
        if resumo.get("prazo_raw") is not None
    ]
    if prazos_resumo:
        rows.append(
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
        rows.append(
            {
                "Indicador": "Intervalo configurado",
                "Valor": ", ".join(
                    f"{resumo.get('nome_programacao', 'Programação')}: "
                    f"{round_minutes(resumo['intervalo_maximo_descargas_min'], 1)} min"
                    for resumo in resultado.resumo
                    if resumo.get("intervalo_maximo_descargas_min") is not None
                ),
                "Detalhe": "Limite adotado entre descargas",
            }
        )
        rows.append(
            {
                "Indicador": "Maior intervalo atingido",
                "Valor": ", ".join(
                    f"{resumo.get('nome_programacao', 'Programação')}: "
                    f"{round_minutes(resumo['maior_intervalo_descargas_min'], 1)} min"
                    for resumo in resultado.resumo
                    if resumo.get("maior_intervalo_descargas_min") is not None
                ),
                "Detalhe": "Maior intervalo calculado no cenário",
            }
        )
    rows.extend(
        [
            {
                "Indicador": "Última descarga",
                "Valor": format_clock(resultado.termino_ultima_descarga, resultado.data_base),
                "Detalhe": "Referência principal para prazo",
            },
            {
                "Indicador": "Última viagem",
                "Valor": format_clock(resultado.termino_ultima_viagem, resultado.data_base),
                "Detalhe": "Inclui lavagem e retorno",
            },
        ]
    )
    return pd.DataFrame(rows)


def _prepare_table_page_dataframe(
    dataframe: pd.DataFrame,
    *,
    wrap_widths: dict[str, int] | None = None,
) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe.copy()
    wrap_widths = wrap_widths or {}
    prepared = dataframe.copy()
    for column in prepared.columns:
        width = wrap_widths.get(column)
        prepared[column] = prepared[column].apply(
            lambda value: "\n".join(fill(_display_text(value), width=width).splitlines())
            if width
            else _display_text(value)
        )
    return prepared


def _build_table_figure(
    dataframe: pd.DataFrame,
    *,
    title: str,
    scenario_label: str,
    subtitle: str = "",
    col_widths: list[float] | None = None,
    rows_per_page_info: str = "",
) -> plt.Figure:
    figure = plt.figure(figsize=PDF_PAGE_SIZE, facecolor="white")
    ax = figure.add_axes([0, 0, 1, 1])
    ax.axis("off")

    figure.text(
        PDF_MARGIN_LEFT,
        PDF_MARGIN_TOP,
        title,
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
    if subtitle:
        figure.text(
            PDF_MARGIN_RIGHT,
            PDF_CONTENT_TOP,
            subtitle,
            fontsize=10,
            color="#5f6b7a",
            ha="right",
            va="top",
        )
    if rows_per_page_info:
        figure.text(
            PDF_MARGIN_LEFT,
            0.875,
            rows_per_page_info,
            fontsize=9.8,
            color="#5f6b7a",
            ha="left",
            va="top",
        )

    if dataframe.empty:
        figure.text(
            0.5,
            0.5,
            "Sem dados disponíveis para exibir.",
            fontsize=12,
            color="#526170",
            ha="center",
            va="center",
        )
        return figure

    table = ax.table(
        cellText=dataframe.values.tolist(),
        colLabels=list(dataframe.columns),
        cellLoc="left",
        colLoc="left",
        colWidths=col_widths,
        bbox=[PDF_MARGIN_LEFT, 0.09, PDF_MARGIN_RIGHT - PDF_MARGIN_LEFT, 0.74],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.8)
    table.scale(1, 1.25)

    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#d6dde6")
        cell.set_linewidth(0.6)
        cell.PAD = 0.03
        if row == 0:
            cell.set_facecolor("#eef2f7")
            cell.get_text().set_fontweight("bold")
            cell.get_text().set_color("#243446")
        else:
            cell.set_facecolor("white")
            cell.get_text().set_color("#243446")

    return figure


def _build_detalhamento_figures(
    resultado: ResultadoCalculo,
    *,
    scenario_label: str,
) -> list[plt.Figure]:
    detalhamento = resultado.dataframe_detalhado
    if detalhamento is None:
        detalhamento = pd.DataFrame()
    else:
        detalhamento = pd.DataFrame(detalhamento)

    columns = [
        column
        for column in [
            "Programação",
            "BT",
            "Viagem",
            "Volume da viagem (m³)",
            "Etapa",
            "Início",
            "Fim",
            "Duração (min)",
            "Observação",
        ]
        if column in detalhamento.columns
    ]
    detalhamento = detalhamento[columns] if columns else pd.DataFrame()
    detalhamento_preparado = _prepare_table_page_dataframe(
        detalhamento,
        wrap_widths={
            "Programação": 20,
            "BT": 12,
            "Etapa": 16,
            "Observação": 28,
        },
    )
    if detalhamento_preparado.empty:
        return [
            _build_table_figure(
                detalhamento_preparado,
                title="Detalhamento operacional",
                scenario_label=scenario_label,
            )
        ]

    rows_per_page = 24
    col_widths = [0.18, 0.08, 0.06, 0.1, 0.12, 0.1, 0.1, 0.1, 0.16][: len(detalhamento_preparado.columns)]
    figures: list[plt.Figure] = []
    total_pages = (len(detalhamento_preparado) - 1) // rows_per_page + 1
    for page_index, start in enumerate(range(0, len(detalhamento_preparado), rows_per_page), start=1):
        chunk = detalhamento_preparado.iloc[start : start + rows_per_page]
        figures.append(
            _build_table_figure(
                chunk,
                title="Detalhamento operacional",
                scenario_label=scenario_label,
                subtitle=f"Página {page_index}/{total_pages}",
                col_widths=col_widths,
                rows_per_page_info=f"Linhas {start + 1} a {start + len(chunk)} do detalhamento",
            )
        )
    return figures


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
        preferred_left = getattr(figure, "_preferred_pdf_left", PDF_MARGIN_LEFT)
        figure.subplots_adjust(
            left=max(PDF_MARGIN_LEFT, preferred_left),
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

        resumo_detalhado_figure = _build_table_figure(
            _prepare_table_page_dataframe(
                _detailed_summary_dataframe(resultado),
                wrap_widths={"Indicador": 22, "Valor": 42, "Detalhe": 42},
            ),
            title="Resumo detalhado",
            scenario_label=scenario_label,
            col_widths=[0.24, 0.26, 0.5],
        )
        pdf.savefig(_normalize_pdf_figure_size(resumo_detalhado_figure))
        plt.close(resumo_detalhado_figure)

        gantt_figure = gerar_gantt(resultado, observed_marker=observed_marker)
        pdf.savefig(_normalize_pdf_figure_size(gantt_figure, chart_layout=True))
        plt.close(gantt_figure)

        disponibilidade_figure = gerar_disponibilidade_bt(resultado)
        pdf.savefig(_normalize_pdf_figure_size(disponibilidade_figure, chart_layout=True))
        plt.close(disponibilidade_figure)

        for detalhamento_figure in _build_detalhamento_figures(
            resultado,
            scenario_label=scenario_label,
        ):
            pdf.savefig(_normalize_pdf_figure_size(detalhamento_figure))
            plt.close(detalhamento_figure)

    buffer.seek(0)
    return buffer.getvalue()
