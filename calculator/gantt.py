from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import os
import tempfile
from pathlib import Path
from datetime import timedelta

MPL_CONFIG_DIR = Path(tempfile.gettempdir()) / "serra_araras_mplconfig"
MPL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPL_CONFIG_DIR))

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter
from matplotlib.lines import Line2D

from calculator.models import ResultadoCalculo
from calculator.utils import format_clock, round_minutes


def _ensure_plotly_browser_path() -> None:
    if os.environ.get("BROWSER_PATH"):
        return

    bundled_candidates = [
        Path(
            "/Library/Frameworks/Python.framework/Versions/3.13/lib/python3.13/site-packages/"
            "choreographer/cli/browser_exe/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/"
            "Google Chrome for Testing"
        ),
    ]
    for candidate in bundled_candidates:
        if candidate.exists():
            os.environ["BROWSER_PATH"] = str(candidate)
            return


def _priority_suffix(prioridade: int) -> str:
    return f" | P{prioridade}" if prioridade > 0 else ""


def _etapa_sigla(nome_etapa: str) -> str:
    siglas = {
        "Espera mistura": "Esp. Mist.",
        "Mistura": "Mist.",
        "Espera dosagem": "Esp. Dos.",
        "Dosagem": "Dos.",
        "Ida": "Ida",
        "Slump": "Slp",
        "Espera bomba": "Esp. Bomb.",
        "Espera frente": "Esp. Fr.",
        "Descarga": "Desc.",
        "Lavagem": "Lav.",
        "Volta": "Volta",
    }
    return siglas.get(nome_etapa, nome_etapa[:8])


def _etapa_letra(nome_etapa: str) -> str:
    letras = {
        "Mistura": "M",
        "Dosagem": "D",
        "Ida": "I",
        "Slump": "S",
        "Descarga": "D",
        "Lavagem": "L",
        "Volta": "V",
    }
    return letras.get(nome_etapa, "")


def _build_manual_time_ticks(
    min_inicio,
    max_fim,
    left_padding_days: float,
    right_padding_days: float,
    reference_ticks: list[float],
) -> list[float]:
    if min_inicio is None or max_fim is None:
        return sorted({round(float(tick), 8) for tick in reference_ticks})

    x_start = min_inicio - timedelta(days=left_padding_days)
    x_end = max_fim + timedelta(days=right_padding_days)

    base_tick = x_start.replace(minute=0, second=0, microsecond=0)
    if base_tick < x_start:
        base_tick += timedelta(hours=1)

    regular_ticks: list[float] = []
    current_tick = base_tick
    while current_tick <= x_end:
        regular_ticks.append(mdates.date2num(current_tick))
        current_tick += timedelta(hours=1)

    merged_ticks = sorted(
        {
            round(float(tick), 8)
            for tick in regular_ticks + reference_ticks
            if mdates.date2num(x_start) <= tick <= mdates.date2num(x_end)
        }
    )
    return merged_ticks


def _format_axis_time_tick(value: float, _pos: int | None = None) -> str:
    dt = mdates.num2date(value).replace(tzinfo=None)
    rounded = dt.replace(second=0, microsecond=0)
    if dt.second > 30 or (dt.second == 30 and dt.microsecond > 0):
        rounded += timedelta(minutes=1)
    elif dt.second == 0 and dt.microsecond >= 500_000:
        rounded += timedelta(minutes=1)
    return rounded.strftime("%H:%M")


def _wrap_section_lines(lines: list[str], width: int = 90) -> str:
    return "\n".join(fill(line, width=width, subsequent_indent="  ") for line in lines if line)


def _estimate_gantt_left_margin(labels: list[str]) -> float:
    if not labels:
        return 0.08
    max_chars = max(len(label) for label in labels)
    estimated = 0.055 + (max_chars * 0.0048)
    return min(max(0.08, estimated), 0.24)


def _draw_section(
    ax,
    title: str,
    lines: list[str],
    y_top: float,
    width: int = 90,
    wrap_lines: bool = True,
) -> float:
    if not lines:
        return y_top

    wrapped = _wrap_section_lines(lines, width=width) if wrap_lines else "\n".join(lines)
    line_count = max(1, len(wrapped.splitlines()))

    ax.text(
        0.0,
        y_top,
        title,
        transform=ax.transAxes,
        fontsize=10.5,
        fontweight="bold",
        va="top",
        color="#222222",
    )
    content_y = y_top - 0.085
    ax.text(
        0.0,
        content_y,
        wrapped,
        transform=ax.transAxes,
        fontsize=8.4,
        va="top",
        linespacing=1.25,
        color="#333333",
    )
    return content_y - (line_count * 0.047) - 0.065


def gerar_tabela_disponibilidade_bt(resultado: ResultadoCalculo) -> pd.DataFrame:
    viagens_por_grupo: dict[str, list] = defaultdict(list)
    for viagem in resultado.viagens:
        if viagem.inicio_viagem is None or viagem.fim_viagem is None:
            continue
        viagens_por_grupo[viagem.grupo_bt].append(viagem)

    rows: list[dict[str, object]] = []
    for group_key in resultado.bt_counts:
        trips = sorted(
            viagens_por_grupo.get(group_key, []),
            key=lambda item: (item.inicio_viagem, item.fim_viagem, item.numero_viagem),
        )
        total_bt = resultado.bt_counts[group_key]
        label = resultado.bt_group_labels.get(group_key, group_key)
        if not trips:
            rows.append(
                {
                    "Frota": label,
                    "Início": "-",
                    "Fim": "-",
                    "Duração (min)": 0,
                    "BTs ocupadas": 0,
                    "BTs livres": total_bt,
                }
            )
            continue

        events: list[tuple] = []
        for trip in trips:
            events.append((trip.inicio_viagem, 1))
            events.append((trip.fim_viagem, -1))
        events.sort(key=lambda item: (item[0], item[1]))

        current = 0
        current_start = events[0][0]
        for instant, delta in events:
            if instant > current_start:
                rows.append(
                    {
                        "Frota": label,
                        "Início": format_clock(current_start, resultado.data_base),
                        "Fim": format_clock(instant, resultado.data_base),
                        "Duração (min)": round_minutes((instant - current_start).total_seconds() / 60.0, 1),
                        "BTs ocupadas": current,
                        "BTs livres": max(0, total_bt - current),
                    }
                )
            current += delta
            current_start = instant

    return pd.DataFrame(rows)


def gerar_disponibilidade_bt(resultado: ResultadoCalculo) -> plt.Figure:
    viagens_por_grupo: dict[str, list] = defaultdict(list)
    for viagem in resultado.viagens:
        if viagem.inicio_viagem is None or viagem.fim_viagem is None:
            continue
        viagens_por_grupo[viagem.grupo_bt].append(viagem)

    grupos = list(resultado.bt_counts.keys())
    row_pattern: list[float] = []
    for group_index, _group_key in enumerate(grupos or ["_single"]):
        row_pattern.extend([1.0, 1.0])
        if group_index < max(len(grupos), 1) - 1:
            row_pattern.append(0.34)

    altura = max(5.6, 2.45 * max(len(grupos), 1) + 0.8)
    figure = plt.figure(figsize=(17.5, altura), facecolor="white")
    grid = figure.add_gridspec(
        nrows=len(row_pattern),
        ncols=1,
        height_ratios=row_pattern,
        hspace=0.22,
    )

    axes: list = []
    group_axes: list[tuple] = []
    row_cursor = 0
    shared_x = None
    for group_index, _group_key in enumerate(grupos or ["_single"]):
        ax_ocupadas = figure.add_subplot(grid[row_cursor, 0], sharex=shared_x)
        if shared_x is None:
            shared_x = ax_ocupadas
        ax_livres = figure.add_subplot(grid[row_cursor + 1, 0], sharex=shared_x)
        axes.extend([ax_ocupadas, ax_livres])
        group_axes.append((ax_ocupadas, ax_livres))
        row_cursor += 2
        if group_index < max(len(grupos), 1) - 1:
            spacer_ax = figure.add_subplot(grid[row_cursor, 0])
            spacer_ax.axis("off")
            row_cursor += 1

    cor_ocupada = "#3f7ea3"
    cor_livre = "#4aa36b"
    cor_faixa = "#dfeee4"
    cor_retorno = "#2e617f"

    global_start = None
    global_end = None

    for group_index, group_key in enumerate(grupos):
        ax_ocupadas, ax_livres = group_axes[group_index]
        trips = sorted(
            viagens_por_grupo.get(group_key, []),
            key=lambda item: (item.inicio_viagem, item.fim_viagem, item.numero_viagem),
        )
        total_bt = resultado.bt_counts[group_key]
        label = resultado.bt_group_labels.get(group_key, group_key)
        ax_ocupadas.set_facecolor("white")
        ax_livres.set_facecolor("white")

        if not trips:
            ax_ocupadas.text(
                0.0,
                0.5,
                f"{label}: sem viagens registradas",
                transform=ax_ocupadas.transAxes,
                ha="left",
                va="center",
                fontsize=10,
                color="#666666",
            )
            ax_ocupadas.set_yticks(range(0, total_bt + 1))
            ax_livres.set_yticks(range(0, total_bt + 1))
            continue

        events: list[tuple] = []
        for trip in trips:
            events.append((trip.inicio_viagem, 1))
            events.append((trip.fim_viagem, -1))

        events.sort(key=lambda item: (item[0], item[1]))
        x_start = min(item[0] for item in events) - timedelta(minutes=5)
        x_end = max(item[0] for item in events) + timedelta(minutes=5)
        global_start = x_start if global_start is None else min(global_start, x_start)
        global_end = x_end if global_end is None else max(global_end, x_end)

        current = 0
        times = [x_start]
        ocupadas = [0]
        retorno_ocupadas: list[tuple[float, float]] = []
        retorno_livres: list[tuple[float, float]] = []
        for instant, delta in events:
            if instant != times[-1]:
                times.append(instant)
                ocupadas.append(current)
            current += delta
            times.append(instant)
            ocupadas.append(current)
            if delta < 0:
                instant_num = mdates.date2num(instant)
                retorno_ocupadas.append((instant_num, current))
                retorno_livres.append((instant_num, total_bt - current))
        times.append(x_end)
        ocupadas.append(current)
        livres = [max(0, total_bt - value) for value in ocupadas]

        times_num = mdates.date2num(times)
        ax_ocupadas.step(
            times_num,
            ocupadas,
            where="post",
            color=cor_ocupada,
            linewidth=2.0,
        )
        ax_ocupadas.fill_between(times_num, ocupadas, step="post", color=cor_ocupada, alpha=0.12)
        ax_livres.step(
            times_num,
            livres,
            where="post",
            color=cor_livre,
            linewidth=2.0,
        )
        ax_livres.fill_between(times_num, livres, step="post", color=cor_faixa, alpha=0.45)

        if retorno_ocupadas:
            ax_ocupadas.scatter(
                [item[0] for item in retorno_ocupadas],
                [item[1] for item in retorno_ocupadas],
                s=18,
                color=cor_retorno,
                edgecolors="white",
                linewidths=0.5,
                zorder=4,
            )
        if retorno_livres:
            ax_livres.scatter(
                [item[0] for item in retorno_livres],
                [item[1] for item in retorno_livres],
                s=18,
                color=cor_retorno,
                edgecolors="white",
                linewidths=0.5,
                zorder=4,
            )

        ax_ocupadas.set_ylim(-0.45, total_bt + 0.4)
        ax_livres.set_ylim(-0.45, total_bt + 0.4)
        ax_ocupadas.set_yticks(range(0, total_bt + 1))
        ax_livres.set_yticks(range(0, total_bt + 1))
        ax_ocupadas.set_ylabel("Ocup.", fontsize=9)
        ax_livres.set_ylabel("Livres", fontsize=9)
        ax_ocupadas.grid(axis="x", linestyle=":", alpha=0.18)
        ax_ocupadas.grid(axis="y", linestyle=":", alpha=0.12)
        ax_livres.grid(axis="x", linestyle=":", alpha=0.18)
        ax_livres.grid(axis="y", linestyle=":", alpha=0.12)
        ax_ocupadas.set_title(
            f"{label} | Total considerado: {total_bt} BT(s)",
            loc="left",
            fontsize=10.2,
            fontweight="bold",
            pad=8,
        )
        for ax in (ax_ocupadas, ax_livres):
            for spine in ax.spines.values():
                spine.set_color("#5d5d5d")
                spine.set_linewidth(1.0)

    if global_start is not None and global_end is not None:
        left_padding = 3 / 1440
        right_padding = 5 / 1440
        reference_ticks: list[float] = []
        tick_values = _build_manual_time_ticks(
            global_start,
            global_end,
            left_padding,
            right_padding,
            reference_ticks,
        )
        for ax in axes:
            ax.set_xlim(
                mdates.date2num(global_start - timedelta(days=left_padding)),
                mdates.date2num(global_end + timedelta(days=right_padding)),
            )
            ax.set_xticks(tick_values)
            ax.xaxis.set_major_formatter(FuncFormatter(_format_axis_time_tick))
            ax.tick_params(axis="x", labelsize=8.5)
            ax.tick_params(axis="y", labelsize=8.5)

    for ax in axes[:-1]:
        ax.tick_params(axis="x", labelbottom=False)
    axes[-1].set_xlabel("")
    figure.suptitle("Disponibilidade de BT no tempo", x=0.03, y=0.988, ha="left", fontsize=17, fontweight="bold")
    legend_handles = [
        Line2D([0], [0], color=cor_ocupada, lw=2, label="BTs ocupadas"),
        Line2D([0], [0], color=cor_livre, lw=2, label="BTs livres"),
    ]
    figure.legend(
        handles=legend_handles,
        loc="upper left",
        bbox_to_anchor=(0.03, 0.945),
        frameon=False,
        ncol=2,
        fontsize=8.5,
        columnspacing=1.6,
        handlelength=2.2,
        handletextpad=0.6,
    )
    figure.subplots_adjust(left=0.07, right=0.985, top=0.84, bottom=0.08)
    return figure


def gerar_disponibilidade_bt_interativa(resultado: ResultadoCalculo):
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        return None

    viagens_por_grupo: dict[str, list] = defaultdict(list)
    for viagem in resultado.viagens:
        if viagem.inicio_viagem is None or viagem.fim_viagem is None:
            continue
        viagens_por_grupo[viagem.grupo_bt].append(viagem)

    grupos = list(resultado.bt_counts.keys())
    if not grupos:
        return None

    programacoes_por_grupo: dict[str, list[str]] = defaultdict(list)
    for concretagem in resultado.concretagens:
        if concretagem.nome_programacao not in programacoes_por_grupo[concretagem.grupo_bt]:
            programacoes_por_grupo[concretagem.grupo_bt].append(concretagem.nome_programacao)

    row_heights: list[float] = []
    subplot_titles: list[str] = []
    spacer_rows: list[int] = []
    total_rows = 0
    for group_index, group_key in enumerate(grupos):
        label = resultado.bt_group_labels.get(group_key, group_key)
        total_bt = resultado.bt_counts[group_key]
        nomes_programacoes = " | ".join(programacoes_por_grupo.get(group_key, []))
        subplot_titles.extend([nomes_programacoes or label, ""])
        row_heights.extend([0.58, 0.42])
        total_rows += 2
        if group_index < len(grupos) - 1:
            row_heights.append(0.24)
            subplot_titles.append("")
            total_rows += 1
            spacer_rows.append(total_rows)

    figura = make_subplots(
        rows=total_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.045,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
    )

    cor_ocupada = "#3f7ea3"
    cor_livre = "#4aa36b"
    cor_retorno = "#2e617f"
    grid_color = "rgba(0,0,0,0.08)"
    global_start = None
    global_end = None

    current_row = 1
    for group_index, group_key in enumerate(grupos):
        trips = sorted(
            viagens_por_grupo.get(group_key, []),
            key=lambda item: (item.inicio_viagem, item.fim_viagem, item.numero_viagem),
        )
        total_bt = resultado.bt_counts[group_key]
        label = resultado.bt_group_labels.get(group_key, group_key)

        if not trips:
            x_values = [resultado.data_base]
            figura.add_trace(
                go.Scatter(
                    x=x_values,
                    y=[0],
                    mode="lines",
                line={"color": cor_ocupada, "width": 2, "shape": "hv"},
                name="BTs ocupadas",
                legendgroup="ocupadas",
                legendrank=1,
                showlegend=current_row == 1,
                hovertemplate=f"{label}<br>BTs ocupadas: 0<extra></extra>",
            ),
                row=current_row,
                col=1,
            )
            figura.add_trace(
                go.Scatter(
                    x=x_values,
                    y=[total_bt],
                    mode="lines",
                line={"color": cor_livre, "width": 2, "shape": "hv"},
                name="BTs livres",
                legendgroup="livres",
                legendrank=2,
                showlegend=current_row == 1,
                hovertemplate=f"{label}<br>BTs livres: {total_bt}<extra></extra>",
            ),
                row=current_row + 1,
                col=1,
            )
            figura.update_yaxes(range=[-0.45, total_bt + 0.4], row=current_row, col=1)
            figura.update_yaxes(range=[-0.45, total_bt + 0.4], row=current_row + 1, col=1)
            current_row += 2
            if group_index < len(grupos) - 1:
                current_row += 1
            continue

        events: list[tuple] = []
        for trip in trips:
            events.append((trip.inicio_viagem, 1))
            events.append((trip.fim_viagem, -1))
        events.sort(key=lambda item: (item[0], item[1]))

        x_start = min(item[0] for item in events) - timedelta(minutes=5)
        x_end = max(item[0] for item in events) + timedelta(minutes=5)
        global_start = x_start if global_start is None else min(global_start, x_start)
        global_end = x_end if global_end is None else max(global_end, x_end)

        current = 0
        times = [x_start]
        ocupadas = [0]
        retorno_ocupadas_x: list[object] = []
        retorno_ocupadas_y: list[int] = []
        retorno_livres_x: list[object] = []
        retorno_livres_y: list[int] = []

        for instant, delta in events:
            if instant != times[-1]:
                times.append(instant)
                ocupadas.append(current)
            current += delta
            times.append(instant)
            ocupadas.append(current)
            if delta < 0:
                retorno_ocupadas_x.append(instant)
                retorno_ocupadas_y.append(current)
                retorno_livres_x.append(instant)
                retorno_livres_y.append(total_bt - current)

        times.append(x_end)
        ocupadas.append(current)
        livres = [max(0, total_bt - value) for value in ocupadas]

        figura.add_trace(
            go.Scatter(
                x=times,
                y=ocupadas,
                mode="lines",
                line={"color": cor_ocupada, "width": 2.3, "shape": "hv"},
                fill="tozeroy",
                fillcolor="rgba(63,126,163,0.12)",
                name="BTs ocupadas",
                legendgroup="ocupadas",
                legendrank=1,
                showlegend=current_row == 1,
                hovertemplate=(
                    f"{label}<br>"
                    "Horário: %{x|%H:%M}<br>"
                    "BTs ocupadas: %{y}<extra></extra>"
                ),
            ),
            row=current_row,
            col=1,
        )

        figura.add_trace(
            go.Scatter(
                x=times,
                y=livres,
                mode="lines",
                line={"color": cor_livre, "width": 2.3, "shape": "hv"},
                fill="tozeroy",
                fillcolor="rgba(74,163,107,0.16)",
                name="BTs livres",
                legendgroup="livres",
                legendrank=2,
                showlegend=current_row == 1,
                hovertemplate=(
                    f"{label}<br>"
                    "Horário: %{x|%H:%M}<br>"
                    "BTs livres: %{y}<extra></extra>"
                ),
            ),
            row=current_row + 1,
            col=1,
        )
        if retorno_ocupadas_x:
            figura.add_trace(
                go.Scatter(
                    x=retorno_ocupadas_x,
                    y=retorno_ocupadas_y,
                    mode="markers",
                    marker={
                        "size": 7,
                        "color": cor_retorno,
                        "line": {"color": "white", "width": 1},
                    },
                    name="Retorno da BT",
                    legendgroup="retorno",
                    legendrank=3,
                    showlegend=False,
                    hovertemplate=(
                        f"{label}<br>"
                        "Retorno: %{x|%H:%M}<br>"
                        "BTs ocupadas após retorno: %{y}<extra></extra>"
                    ),
                ),
                row=current_row,
                col=1,
            )
        if retorno_livres_x:
            figura.add_trace(
                go.Scatter(
                    x=retorno_livres_x,
                    y=retorno_livres_y,
                    mode="markers",
                    marker={
                        "size": 7,
                        "color": cor_retorno,
                        "line": {"color": "white", "width": 1},
                    },
                    name="Retorno da BT",
                    legendgroup="retorno",
                    legendrank=3,
                    showlegend=False,
                    hovertemplate=(
                        f"{label}<br>"
                        "Retorno: %{x|%H:%M}<br>"
                        "BTs livres após retorno: %{y}<extra></extra>"
                    ),
                ),
                row=current_row + 1,
                col=1,
            )

        figura.update_yaxes(
            range=[-0.45, total_bt + 0.4],
            tickmode="linear",
            tick0=0,
            dtick=1,
            title="Ocup.",
            row=current_row,
            col=1,
        )
        figura.update_yaxes(
            range=[-0.45, total_bt + 0.4],
            tickmode="linear",
            tick0=0,
            dtick=1,
            title="Livres",
            row=current_row + 1,
            col=1,
        )
        current_row += 2
        if group_index < len(grupos) - 1:
            current_row += 1

    if global_start is not None and global_end is not None:
        for row in range(1, total_rows + 1):
            figura.update_xaxes(
                range=[global_start, global_end],
                showgrid=True,
                gridcolor=grid_color,
                tickformat="%H:%M",
                tickfont={"color": "#475569", "size": 12},
                showline=True,
                linecolor="rgba(31,41,55,0.28)",
                row=row,
                col=1,
            )
            figura.update_yaxes(
                showgrid=True,
                gridcolor="rgba(0,0,0,0.05)",
                tickfont={"color": "#475569", "size": 11},
                title_font={"color": "#475569", "size": 11},
                showline=True,
                linecolor="rgba(31,41,55,0.22)",
                row=row,
                col=1,
            )

    for row in spacer_rows:
        figura.update_xaxes(visible=False, row=row, col=1)
        figura.update_yaxes(visible=False, row=row, col=1)

    for row in range(1, total_rows):
        figura.update_xaxes(showticklabels=False, row=row, col=1)

    figure_height = max(760, 300 * len(grupos) + 120)

    def _paper_units(px: float) -> float:
        return px / figure_height

    top_title_y = 0.988
    top_reserved_px = 84
    plot_domain_top = 1 - _paper_units(top_reserved_px)

    footer_bottom_padding_px = 18
    plot_to_legend_gap_px = 14
    legend_block_height_px = 38
    xaxis_tick_band_px = 30

    footer_total_reserved_px = (
        footer_bottom_padding_px
        + legend_block_height_px
        + plot_to_legend_gap_px
        + xaxis_tick_band_px
    )
    footer_reserved_height = max(_paper_units(footer_total_reserved_px), _paper_units(112))
    plot_domain_bottom = footer_reserved_height
    plot_span = plot_domain_top - plot_domain_bottom
    footer_legend_y = plot_domain_bottom - _paper_units(xaxis_tick_band_px + plot_to_legend_gap_px)

    figura.update_layout(
        title={
            "text": "Disponibilidade de BT no tempo",
            "x": 0.0,
            "xanchor": "left",
            "y": top_title_y,
            "font": {"size": 20, "color": "#1f2937"},
        },
        height=figure_height,
        plot_bgcolor="white",
        paper_bgcolor="white",
        font={"color": "#243041", "size": 12},
        margin={"l": 72, "r": 40, "t": 102, "b": max(88, int(footer_total_reserved_px + 20))},
        legend={
            "orientation": "h",
            "x": 0.0,
            "y": footer_legend_y,
            "xanchor": "left",
            "yanchor": "top",
            "bgcolor": "rgba(255,255,255,0.92)",
            "font": {"color": "#334155", "size": 11},
        },
    )
    for annotation in figura.layout.annotations:
        if annotation.text in subplot_titles and annotation.text:
            annotation.update(
                font={"size": 11.5, "color": "#334155"},
                xanchor="left",
                y=plot_domain_bottom + (annotation.y * plot_span),
            )

    layout_json = figura.layout.to_plotly_json()
    for axis_key, axis_value in layout_json.items():
        if not axis_key.startswith("yaxis"):
            continue
        if not isinstance(axis_value, dict) or "domain" not in axis_value:
            continue
        domain = axis_value["domain"]
        figura.layout[axis_key].domain = [
            plot_domain_bottom + (domain[0] * plot_span),
            plot_domain_bottom + (domain[1] * plot_span),
        ]

    figura.update_xaxes(title_text="", row=total_rows, col=1)
    return figura


def gerar_gantt_interativo(
    resultado: ResultadoCalculo,
    observed_marker: dict | None = None,
):
    try:
        import plotly.express as px
        import plotly.graph_objects as go
    except ImportError:
        return None

    ordem_programacao = {
        concretagem.id: index
        for index, concretagem in enumerate(resultado.concretagens)
    }
    viagens = sorted(
        resultado.viagens,
        key=lambda viagem: (
            ordem_programacao.get(viagem.concretagem_id, 999),
            viagem.numero_viagem,
            viagem.inicio_viagem,
        ),
    )
    priorities = {concretagem.id: concretagem.prioridade for concretagem in resultado.concretagens}

    cores_etapa = {
        "Mistura": "#3f7ea3",
        "Dosagem": "#4a8bb1",
        "Ida": "#5b95b4",
        "Slump": "#6ca2bf",
        "Descarga": "#2d6f93",
        "Lavagem": "#79abc8",
        "Volta": "#5b88a8",
        "Espera mistura": "#ece9e2",
        "Espera dosagem": "#ece9e2",
        "Espera bomba": "#ece9e2",
        "Espera frente": "#ece9e2",
    }

    rows: list[dict[str, object]] = []
    category_order: list[str] = []
    tick_text_by_category: dict[str, str] = {}
    group_headers: list[tuple[str, str, object]] = []
    start_annotations: list[tuple[object, str, str]] = []
    end_annotations: list[tuple[object, str, str]] = []
    min_inicio = None
    max_fim = None
    previous_program = None
    gap_count = 0
    for viagem in viagens:
        if viagem.nome_programacao != previous_program:
            spacer_key = f"__gap__{gap_count}"
            category_order.append(spacer_key)
            tick_text_by_category[spacer_key] = ""
            group_headers.append((viagem.nome_programacao, spacer_key, viagem.inicio_viagem))
            gap_count += 1

        volume_label = f"{round_minutes(viagem.volume_m3, 1)} m³"
        label = (
            f"V{viagem.numero_viagem:02d} | {viagem.bt} | {volume_label}"
            f"{_priority_suffix(priorities.get(viagem.concretagem_id, 0))}"
        )
        category_key = f"{viagem.concretagem_id}::{viagem.numero_viagem:02d}::{viagem.bt}"
        category_order.append(category_key)
        tick_text_by_category[category_key] = label

        mistura = next((etapa for etapa in viagem.etapas if etapa.etapa == "Mistura"), None)
        volta = next((etapa for etapa in viagem.etapas if etapa.etapa == "Volta"), None)
        if mistura is not None:
            start_annotations.append(
                (mistura.inicio, category_key, format_clock(mistura.inicio, resultado.data_base))
            )
        if volta is not None:
            end_annotations.append(
                (volta.fim, category_key, format_clock(volta.fim, resultado.data_base))
            )

        for etapa in viagem.etapas:
            inicio = etapa.inicio
            fim = etapa.fim
            min_inicio = inicio if min_inicio is None or inicio < min_inicio else min_inicio
            max_fim = fim if max_fim is None or fim > max_fim else max_fim
            rows.append(
                {
                    "Programação": viagem.nome_programacao,
                    "Viagem": category_key,
                    "Etapa": etapa.etapa,
                    "Início": inicio,
                    "Fim": fim,
                    "Início_fmt": format_clock(inicio, resultado.data_base),
                    "Fim_fmt": format_clock(fim, resultado.data_base),
                    "Duração_min": round_minutes(etapa.duracao_min, 1),
                    "BT": viagem.bt,
                    "Etapa_txt": "" if etapa.etapa.startswith("Espera") else _etapa_letra(etapa.etapa),
                }
            )
        previous_program = viagem.nome_programacao

    df = pd.DataFrame(rows)
    if df.empty:
        figura = go.Figure()
        figura.update_layout(
            title={
                "text": "Planejamento Concretagem",
                "x": 0.0,
                "xanchor": "left",
                "y": 0.982,
                "font": {"size": 20, "color": "#1f2937"},
            },
            height=520,
            plot_bgcolor="white",
            paper_bgcolor="white",
            margin={"l": 72, "r": 72, "t": 92, "b": 52},
            font={"color": "#243041", "size": 12},
            xaxis={"visible": False},
            yaxis={"visible": False},
        )
        figura.add_annotation(
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            text="Sem viagens disponíveis para exibir no planejamento.",
            showarrow=False,
            font={"size": 14, "color": "#475569"},
        )
        return figura

    figura = px.timeline(
        df,
        x_start="Início",
        x_end="Fim",
        y="Viagem",
        color="Etapa",
        text="Etapa_txt",
        color_discrete_map=cores_etapa,
        category_orders={"Viagem": category_order},
        custom_data=["Programação", "Etapa", "Início_fmt", "Fim_fmt", "Duração_min", "BT"],
    )
    top_title_y = 0.988
    top_reserved_px = 84
    figure_height = max(
        700,
        110 + (len(category_order) * 46),
    )

    def _paper_units(px: float) -> float:
        return px / figure_height

    plot_domain_top = 1 - _paper_units(top_reserved_px)
    top_annotation_y = plot_domain_top + _paper_units(10)

    footer_bottom_padding_px = 18
    plot_to_legend_gap_px = 14
    legend_block_height_px = 38
    xaxis_tick_band_px = 30
    footer_total_reserved_px = (
        footer_bottom_padding_px
        + legend_block_height_px
        + plot_to_legend_gap_px
        + xaxis_tick_band_px
    )

    footer_reserved_height = max(_paper_units(footer_total_reserved_px), _paper_units(112))
    plot_domain_bottom = footer_reserved_height
    footer_legend_y = plot_domain_bottom - _paper_units(xaxis_tick_band_px + plot_to_legend_gap_px)

    figura.update_traces(
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Viagem: %{y}<br>"
            "Etapa: %{customdata[1]}<br>"
            "BT: %{customdata[5]}<br>"
            "Início: %{customdata[2]}<br>"
            "Fim: %{customdata[3]}<br>"
            "Duração: %{customdata[4]} min"
            "<extra></extra>"
        ),
        marker_line_width=1,
        marker_line_color="#2e617f",
        textposition="inside",
        insidetextanchor="middle",
        textfont={"color": "white", "size": 10},
        textangle=0,
        cliponaxis=False,
    )

    def _add_vertical_reference(
        when,
        *,
        color: str,
        dash: str = "solid",
        width: float = 1.6,
        annotation_text: str | None = None,
        annotation_xanchor: str = "left",
    ) -> None:
        figura.add_shape(
            type="line",
            x0=when,
            x1=when,
            y0=0,
            y1=1,
            xref="x",
            yref="y domain",
            line={"color": color, "dash": dash, "width": width},
        )
        if annotation_text:
            figura.add_annotation(
                x=when,
                y=top_annotation_y,
                xref="x",
                yref="paper",
                text=annotation_text,
                showarrow=False,
                xanchor=annotation_xanchor,
                yanchor="bottom",
                font={"size": 11, "color": "#243041"},
                bgcolor="rgba(255,255,255,0.96)",
            )

    primeiras_misturas = [etapa.inicio for etapa in resultado.etapas if etapa.etapa == "Mistura"]
    primeira_mistura_referencia = min(primeiras_misturas) if primeiras_misturas else None
    if primeira_mistura_referencia is not None:
        _add_vertical_reference(
            primeira_mistura_referencia,
            color="#4aa3a1",
            width=2,
            annotation_text=f"Início 1ª mistura ({format_clock(primeira_mistura_referencia, resultado.data_base)})",
            annotation_xanchor="left",
        )

    deadlines_drawn: set[float] = set()
    for resumo in resultado.resumo:
        deadline = resumo.get("prazo_raw")
        if deadline is None:
            continue
        deadline_num = round(mdates.date2num(deadline), 8)
        if deadline_num in deadlines_drawn:
            continue
        deadlines_drawn.add(deadline_num)
        _add_vertical_reference(
            deadline,
            color="#e07a73",
            dash="dash",
            width=1.5,
        )

    if resultado.termino_ultima_descarga is not None:
        _add_vertical_reference(
            resultado.termino_ultima_descarga,
            color="#303030",
            dash="dashdot",
            width=1.6,
            annotation_text=f"Término real ({format_clock(resultado.termino_ultima_descarga, resultado.data_base)})",
            annotation_xanchor="right",
        )

    observed_marker_dt = observed_marker.get("observed_reference") if observed_marker else None
    observed_marker_label = observed_marker.get("label") if observed_marker else "Marco observado"
    if observed_marker_dt is not None:
        _add_vertical_reference(
            observed_marker_dt,
            color="#d97706",
            dash="longdash",
            width=2,
            annotation_text=f"{observed_marker_label} ({format_clock(observed_marker_dt, resultado.data_base)})",
            annotation_xanchor="right",
        )

    for program_name, category_key, trip_start in group_headers:
        figura.add_annotation(
            x=trip_start,
            y=category_key,
            xref="x",
            yref="y",
            text=program_name,
            showarrow=False,
            xanchor="left",
            yanchor="middle",
            font={"size": 12, "color": "#475569"},
        )

    for when, category_key, label in start_annotations:
        figura.add_annotation(
            x=when,
            y=category_key,
            xref="x",
            yref="y",
            text=label,
            showarrow=False,
            xanchor="right",
            yanchor="middle",
            xshift=-4,
            font={"size": 10, "color": "#64748b"},
        )

    for when, category_key, label in end_annotations:
        figura.add_annotation(
            x=when,
            y=category_key,
            xref="x",
            yref="y",
            text=label,
            showarrow=False,
            xanchor="left",
            yanchor="middle",
            xshift=4,
            font={"size": 10, "color": "#64748b"},
        )

    figura.update_layout(
        title={
            "text": "Planejamento Concretagem",
            "x": 0.0,
            "xanchor": "left",
            "y": top_title_y,
            "font": {"size": 20, "color": "#1f2937"},
        },
        barmode="overlay",
        bargap=0.28,
        height=figure_height,
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend_title_text="<b>Etapas</b>",
        margin={
            "l": 72,
            "r": 72,
            "t": 102,
            "b": max(88, int(footer_total_reserved_px + 20)),
        },
        font={"color": "#243041", "size": 12},
        legend={
            "font": {"color": "#243041", "size": 11},
            "title": {"font": {"color": "#243041", "size": 11}},
            "bgcolor": "rgba(255,255,255,0.92)",
            "orientation": "h",
            "x": 0.0,
            "xanchor": "left",
            "y": footer_legend_y,
            "yanchor": "top",
        },
    )
    figura.update_yaxes(
        title="Viagens",
        autorange="reversed",
        categoryorder="array",
        categoryarray=category_order,
        tickvals=category_order,
        ticktext=[tick_text_by_category.get(item, item) for item in category_order],
        title_font={"color": "#374151", "size": 13},
        tickfont={"color": "#4b5563", "size": 12},
        showline=True,
        linecolor="rgba(31,41,55,0.28)",
        gridcolor="rgba(0,0,0,0.05)",
        ticks="outside",
    )
    figura.update_xaxes(
        title="",
        tickformat="%H:%M",
        showgrid=True,
        gridcolor="rgba(0,0,0,0.08)",
        title_font={"color": "#374151", "size": 13},
        tickfont={"color": "#4b5563", "size": 12},
        showline=True,
        linecolor="rgba(31,41,55,0.28)",
        zeroline=False,
    )
    figura.update_yaxes(domain=[plot_domain_bottom, plot_domain_top])
    if min_inicio is not None and max_fim is not None:
        figura.update_xaxes(range=[min_inicio - timedelta(minutes=6), max_fim + timedelta(minutes=6)])

    return figura


def exportar_gantt_interativo_png(
    resultado: ResultadoCalculo,
    observed_marker: dict | None = None,
    width: int = 1700,
) -> bytes | None:
    _ensure_plotly_browser_path()
    figura = gerar_gantt_interativo(resultado, observed_marker=observed_marker)
    if figura is None:
        return None

    figura_export = deepcopy(figura)
    export_height = int(figura_export.layout.height or max(520, 78 + (len(resultado.viagens) * 39)))
    figura_export.update_layout(width=width, height=export_height, autosize=False)
    try:
        return figura_export.to_image(format="png", width=width, height=export_height, scale=1)
    except Exception:
        return None


def gerar_gantt(resultado: ResultadoCalculo, observed_marker: dict | None = None) -> plt.Figure:
    ordem_programacao = {
        concretagem.id: index
        for index, concretagem in enumerate(resultado.concretagens)
    }
    viagens = sorted(
        resultado.viagens,
        key=lambda viagem: (
            ordem_programacao.get(viagem.concretagem_id, 999),
            viagem.numero_viagem,
            viagem.inicio_viagem,
        ),
    )
    num_programacoes = max(len(resultado.concretagens), 1)
    chart_height = max(6.8, 0.7 * max(len(viagens), 1) + 1.8)
    legend_height = 0.85
    figura_altura = chart_height + legend_height + 0.6
    figure = plt.figure(figsize=(18.8, figura_altura), facecolor="white")
    grid = figure.add_gridspec(
        2,
        1,
        height_ratios=[chart_height, legend_height],
        hspace=0.07,
    )
    ax = figure.add_subplot(grid[0, 0])
    ax_legend = figure.add_subplot(grid[1, 0])
    ax_legend.axis("off")
    ax.set_facecolor("white")

    cores_etapa = {
        "Mistura": "#3f7ea3",
        "Dosagem": "#4a8bb1",
        "Ida": "#5b95b4",
        "Slump": "#6ca2bf",
        "Descarga": "#2d6f93",
        "Lavagem": "#79abc8",
        "Volta": "#5b88a8",
    }
    cor_principal = "#3f7ea3"
    cor_borda = "#2e617f"
    cor_espera = "#ece9e2"
    cor_espera_borda = "#8e8e8e"
    cor_inicio = "#4aa3a1"
    cor_marcador_observado = "#d97706"
    cor_prazo = "#e07a73"
    cor_termino = "#303030"
    cor_intervalo = "#f1b6ad"

    labels: list[str] = []
    y_positions: list[float] = []
    min_inicio = None
    max_fim = None
    current_y = 0.0
    previous_program = None
    group_boundaries: list[tuple[float, str]] = []
    group_headers: list[tuple[str, float, float]] = []
    current_group_start_y: float | None = None
    priorities = {concretagem.id: concretagem.prioridade for concretagem in resultado.concretagens}

    for viagem in viagens:
        if previous_program is not None and viagem.nome_programacao != previous_program:
            group_boundaries.append((current_y - 0.5, previous_program))
            if current_group_start_y is not None:
                group_headers.append((previous_program, current_group_start_y, y_positions[-1]))
            current_y += 0.8
            current_group_start_y = None
        y_positions.append(current_y)
        if current_group_start_y is None:
            current_group_start_y = current_y
        labels.append(
            f"V{viagem.numero_viagem:02d} | {viagem.bt}{_priority_suffix(priorities.get(viagem.concretagem_id, 0))}"
        )
        previous_program = viagem.nome_programacao
        current_y += 1.0

    if previous_program is not None:
        group_boundaries.append((current_y - 0.5, previous_program))
        if current_group_start_y is not None:
            group_headers.append((previous_program, current_group_start_y, y_positions[-1]))

    for linha, viagem in enumerate(viagens):
        y = y_positions[linha]
        if viagem.inicio_viagem and (min_inicio is None or viagem.inicio_viagem < min_inicio):
            min_inicio = viagem.inicio_viagem
        if viagem.fim_viagem and (max_fim is None or viagem.fim_viagem > max_fim):
            max_fim = viagem.fim_viagem

        for etapa in viagem.etapas:
            inicio = mdates.date2num(etapa.inicio)
            fim = mdates.date2num(etapa.fim)
            largura = fim - inicio
            is_wait = etapa.etapa.startswith("Espera")

            ax.barh(
                y=y,
                width=largura,
                left=inicio,
                height=0.66,
                color=cor_espera if is_wait else cores_etapa.get(etapa.etapa, cor_principal),
                edgecolor=cor_espera_borda if is_wait else cor_borda,
                hatch="////" if is_wait else None,
                linewidth=0.95,
                alpha=0.96,
            )

            largura_min = etapa.duracao_min
            if largura_min >= 7:
                ax.text(
                    inicio + (largura / 2),
                    y,
                    _etapa_sigla(etapa.etapa),
                    ha="center",
                    va="center",
                    fontsize=6.9,
                    color="#4d4d4d" if is_wait else "white",
                    fontweight="bold" if not is_wait else "normal",
                    clip_on=True,
                )

        if viagem.inicio_viagem and viagem.fim_viagem:
            start_label_x = mdates.date2num(viagem.inicio_viagem - timedelta(minutes=0.8))
            end_label_x = mdates.date2num(viagem.fim_viagem + timedelta(minutes=0.8))
            ax.text(
                start_label_x,
                y - 0.34,
                format_clock(viagem.inicio_viagem, resultado.data_base),
                ha="right",
                va="center",
                fontsize=7.1,
                color="#797979",
            )
            ax.text(
                end_label_x,
                y - 0.34,
                format_clock(viagem.fim_viagem, resultado.data_base),
                ha="left",
                va="center",
                fontsize=7.1,
                color="#797979",
            )

    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    if y_positions:
        y_min = -1.02
        y_max = max(y_positions) + 0.75
        ax.set_ylim(y_max, y_min)
    ax.set_xlabel("")
    ax.grid(axis="x", linestyle=":", alpha=0.18)
    ax.xaxis.set_major_formatter(FuncFormatter(_format_axis_time_tick))
    ax.tick_params(axis="x", labelsize=8.5)
    ax.tick_params(axis="y", labelsize=8, pad=10)
    for spine in ax.spines.values():
        spine.set_color("#5d5d5d")
        spine.set_linewidth(1.0)

    for boundary_y, _program_name in group_boundaries[:-1]:
        ax.axhline(boundary_y + 0.42, color="#d9d9d9", linewidth=1.0, alpha=0.8)

    for program_name, start_y, end_y in group_headers:
        primeira_viagem = next((viagem for viagem in viagens if viagem.nome_programacao == program_name), None)
        if primeira_viagem is None or primeira_viagem.inicio_viagem is None:
            continue
        ax.text(
            mdates.date2num(primeira_viagem.inicio_viagem),
            start_y - 0.64,
            program_name,
            ha="left",
            va="bottom",
            fontsize=8.6,
            color="#505050",
            fontweight="bold",
            bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.2},
        )

    primeiras_misturas = [etapa.inicio for etapa in resultado.etapas if etapa.etapa == "Mistura"]
    primeira_mistura_referencia = min(primeiras_misturas) if primeiras_misturas else None
    observed_marker_dt = observed_marker.get("observed_reference") if observed_marker else None
    observed_marker_label = observed_marker.get("label") if observed_marker else None
    if primeiras_misturas:
        ax.axvline(
            mdates.date2num(primeira_mistura_referencia),
            color=cor_inicio,
            linestyle="-",
            linewidth=1.6,
        )

    deadlines_drawn: set[float] = set()
    for resumo in resultado.resumo:
        deadline = resumo.get("prazo_raw")
        if deadline is None:
            continue
        deadline_num = round(mdates.date2num(deadline), 8)
        if deadline_num in deadlines_drawn:
            continue
        deadlines_drawn.add(deadline_num)
        ax.axvline(
            deadline_num,
            color=cor_prazo,
            linestyle="--",
            linewidth=1.2,
        )

    if resultado.termino_ultima_descarga is not None:
        ax.axvline(
            mdates.date2num(resultado.termino_ultima_descarga),
            color=cor_termino,
            linestyle="-.",
            linewidth=1.4,
        )
    if observed_marker_dt is not None:
        ax.axvline(
            mdates.date2num(observed_marker_dt),
            color=cor_marcador_observado,
            linestyle=(0, (5, 2)),
            linewidth=1.6,
        )

    for intervalo in resultado.intervalos_descarga:
        if not intervalo.get("violacao"):
            continue
        ax.axvspan(
            mdates.date2num(intervalo["fim_descarga_anterior"]),
            mdates.date2num(intervalo["inicio_proxima_descarga"]),
            color=cor_intervalo,
            alpha=0.28,
            zorder=0,
        )

    left_padding = None
    right_padding = None
    if min_inicio and max_fim:
        inicio_num = mdates.date2num(min_inicio)
        fim_num = mdates.date2num(max_fim)
        padding = (fim_num - inicio_num) * 0.05 if fim_num > inicio_num else 0.02
        left_padding = max(padding * 0.7, 6 / 1440)
        right_padding = max(padding * 0.95, 12 / 1440)
        ax.set_xlim(inicio_num - left_padding, fim_num + right_padding)

    reference_ticks: list[float] = []
    if primeira_mistura_referencia is not None:
        reference_ticks.append(mdates.date2num(primeira_mistura_referencia))
    reference_ticks.extend(sorted(deadlines_drawn))
    if resultado.termino_ultima_descarga is not None:
        reference_ticks.append(mdates.date2num(resultado.termino_ultima_descarga))
    if observed_marker_dt is not None:
        reference_ticks.append(mdates.date2num(observed_marker_dt))
    if reference_ticks and min_inicio and max_fim and left_padding is not None and right_padding is not None:
        merged_ticks = _build_manual_time_ticks(
            min_inicio,
            max_fim,
            left_padding,
            right_padding,
            reference_ticks,
        )
        ax.set_xticks(merged_ticks)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")

    legend_handles = [
        Line2D([0], [0], marker="s", linestyle="None", markersize=8, markerfacecolor=color, markeredgecolor=cor_borda, label=label)
        for label, color in cores_etapa.items()
    ]
    ax_legend.legend(
        handles=legend_handles,
        loc="center left",
        fontsize=8,
        title="Etapas",
        ncol=max(1, len(legend_handles)),
        frameon=False,
        bbox_to_anchor=(0.0, 0.18),
        borderaxespad=0.0,
        columnspacing=1.4,
        handlelength=1.2,
    )

    left_margin = _estimate_gantt_left_margin(labels)
    figure.suptitle("Planejamento concretagem", x=0.03, y=0.950, ha="left", fontsize=17, fontweight="bold")
    figure.subplots_adjust(left=left_margin, right=0.985, top=0.92, bottom=0.08)
    figure._preferred_pdf_left = left_margin
    return figure
