from __future__ import annotations

from collections import defaultdict
import os
import tempfile
from pathlib import Path
from textwrap import fill
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


def _priority_sort_value(prioridade: int) -> int:
    return prioridade if prioridade > 0 else 999


def _priority_suffix(prioridade: int) -> str:
    return f" | P{prioridade}" if prioridade > 0 else ""


def _sequencing_lines(resultado: ResultadoCalculo) -> list[str]:
    if not resultado.sequenciamento_prioridade_ativo:
        return []

    labels_by_group = resultado.bt_group_labels
    grouped = {}
    for concretagem in resultado.concretagens:
        grouped.setdefault(concretagem.grupo_bt, []).append(concretagem)

    lines: list[str] = []
    for group_key, members in grouped.items():
        if len(members) <= 1:
            continue
        ordered = sorted(
            members,
            key=lambda item: (
                item.inicio_primeira_mistura,
                _priority_sort_value(item.prioridade),
                item.ordem,
            ),
        )
        sequence = " -> ".join(
            f"{item.nome_programacao} ({item.inicio_primeira_mistura.strftime('%H:%M')}{_priority_suffix(item.prioridade)})"
            for item in ordered
        )
        lines.append(f"{labels_by_group.get(group_key, group_key)}: {sequence}")
    return lines


def _intervalo_descargas_lines(resultado: ResultadoCalculo) -> list[str]:
    linhas: list[str] = []
    for intervalo in resultado.intervalos_descarga:
        if not intervalo.get("violacao"):
            continue
        linhas.append(
            (
                f"{intervalo['frente_label']}: "
                f"{round_minutes(intervalo['intervalo_min'], 1)} min "
                f"(limite {round_minutes(intervalo['limite_min'], 1)} min) entre "
                f"{format_clock(intervalo['fim_descarga_anterior'], resultado.data_base)} e "
                f"{format_clock(intervalo['inicio_proxima_descarga'], resultado.data_base)}"
            )
        )
    return linhas


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
    axes[-1].set_xlabel("Tempo da operação", fontsize=9)
    figure.suptitle("Disponibilidade de BT no tempo", x=0.03, y=0.988, ha="left", fontsize=17, fontweight="bold")
    legend_handles = [
        Line2D([0], [0], color=cor_ocupada, lw=2, label="BTs ocupadas"),
        Line2D([0], [0], color=cor_livre, lw=2, label="BTs livres"),
        Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor=cor_retorno,
            markeredgecolor="white",
            markersize=6,
            label="Retorno da BT",
        ),
    ]
    figure.legend(
        handles=legend_handles,
        loc="upper left",
        bbox_to_anchor=(0.03, 0.945),
        frameon=False,
        ncol=3,
        fontsize=8.5,
        columnspacing=1.6,
        handlelength=2.2,
        handletextpad=0.6,
    )
    figure.subplots_adjust(left=0.07, right=0.985, top=0.84, bottom=0.08)
    return figure


def gerar_gantt(resultado: ResultadoCalculo) -> plt.Figure:
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
    cycle_blocks: list[tuple[str, str]] = []
    for concretagem in resultado.concretagens:
        etapas = " | ".join(
            f"{_etapa_sigla(etapa)} {round_minutes(duracao, 1)} min"
            for etapa, duracao in concretagem.ciclo.as_rows()
        )
        cycle_blocks.append((concretagem.nome_programacao, etapas))

    intervalos_lines = _intervalo_descargas_lines(resultado)
    sequencing_lines = _sequencing_lines(resultado)
    chart_height = max(6.8, 0.7 * max(len(viagens), 1) + 1.8)
    cycle_panel_height = max(1.9, 0.48 * max(len(cycle_blocks), 1) + 0.75)
    ops_line_count = len(intervalos_lines[:4]) + len(sequencing_lines)
    ops_panel_height = max(2.1, 0.18 * max(ops_line_count, 1) + 0.95)
    bottom_height = max(cycle_panel_height, ops_panel_height)
    figura_altura = chart_height + bottom_height + 1.0
    figure = plt.figure(figsize=(18.8, figura_altura), facecolor="white")
    grid = figure.add_gridspec(
        3,
        1,
        height_ratios=[chart_height, 0.52, bottom_height],
        hspace=0.05,
    )
    ax = figure.add_subplot(grid[0, 0])
    ax_legend = figure.add_subplot(grid[1, 0])
    bottom_grid = grid[2, 0].subgridspec(1, 2, width_ratios=[1.1, 1.0], wspace=0.18)
    ax_cycles = figure.add_subplot(bottom_grid[0, 0])
    ax_ops = figure.add_subplot(bottom_grid[0, 1])
    ax_legend.axis("off")
    ax_cycles.axis("off")
    ax_ops.axis("off")
    ax.set_facecolor("white")

    cor_principal = "#3f7ea3"
    cor_borda = "#2e617f"
    cor_espera = "#ece9e2"
    cor_espera_borda = "#8e8e8e"
    cor_inicio = "#4aa3a1"
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
                color=cor_espera if is_wait else cor_principal,
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
    if primeiras_misturas:
        ax.axvline(
            mdates.date2num(primeira_mistura_referencia),
            color=cor_inicio,
            linestyle="-",
            linewidth=1.6,
        )

    deadlines_drawn: set[float] = set()
    deadlines_labels: list[str] = []
    for resumo in resultado.resumo:
        deadline = resumo.get("prazo_raw")
        if deadline is None:
            continue
        deadline_num = round(mdates.date2num(deadline), 8)
        if deadline_num in deadlines_drawn:
            continue
        deadlines_drawn.add(deadline_num)
        deadlines_labels.append(format_clock(deadline, resultado.data_base))
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
        Line2D(
            [0],
            [0],
            color=cor_inicio,
            lw=1.8,
            linestyle="-",
            label=(
                f"Início da 1ª mistura ({format_clock(primeira_mistura_referencia, resultado.data_base)})"
                if primeira_mistura_referencia is not None
                else "Início da 1ª mistura"
            ),
        )
    ]
    if deadlines_drawn:
        legend_handles.append(
            Line2D(
                [0],
                [0],
                color=cor_prazo,
                lw=1.4,
                linestyle="--",
                label=(
                    f"Prazo limite de descarga ({', '.join(deadlines_labels)})"
                    if deadlines_labels
                    else "Prazo limite de descarga"
                ),
            )
        )
    if resultado.termino_ultima_descarga is not None:
        legend_handles.append(
            Line2D(
                [0],
                [0],
                color=cor_termino,
                lw=1.5,
                linestyle="-.",
                label=(
                    "Término real da última descarga "
                    f"({format_clock(resultado.termino_ultima_descarga, resultado.data_base)})"
                ),
            )
        )
    if any(item.get("violacao") for item in resultado.intervalos_descarga):
        legend_handles.append(
            Line2D(
                [0],
                [0],
                color=cor_intervalo,
                lw=7,
                alpha=0.5,
                label="Intervalo excedido entre descargas",
            )
        )
    ax_legend.legend(
        handles=legend_handles,
        loc="center left",
        fontsize=8,
        ncol=max(1, len(legend_handles)),
        frameon=False,
        bbox_to_anchor=(0.0, 0.18),
        borderaxespad=0.0,
        columnspacing=1.4,
        handlelength=2.6,
    )

    ax_cycles.text(
        0.0,
        0.98,
        "Tempos de ciclo",
        transform=ax_cycles.transAxes,
        fontsize=10.5,
        fontweight="bold",
        va="top",
        ha="left",
        color="#222222",
    )
    y_cycle = 0.88
    cycle_step = 0.22 if len(cycle_blocks) <= 3 else 0.18
    for program_name, etapas in cycle_blocks:
        ax_cycles.text(
            0.0,
            y_cycle,
            program_name,
            transform=ax_cycles.transAxes,
            fontsize=8.4,
            fontweight="bold",
            va="top",
            ha="left",
            color="#333333",
        )
        ax_cycles.text(
            0.0,
            y_cycle - 0.085,
            etapas,
            transform=ax_cycles.transAxes,
            fontsize=8.4,
            va="top",
            ha="left",
            color="#333333",
        )
        y_cycle -= cycle_step

    y_ops = 0.98
    if intervalos_lines:
        y_ops = _draw_section(
            ax_ops,
            "Continuidade operacional",
            [f"- {item}" for item in intervalos_lines[:4]],
            y_ops,
            width=52,
            wrap_lines=False,
        )
    if sequencing_lines:
        _draw_section(
            ax_ops,
            "Sequenciamento adotado",
            [f"- {item}" for item in sequencing_lines],
            y_ops,
            width=52,
        )

    figure.suptitle("Planejamento concretagem", x=0.03, y=0.950, ha="left", fontsize=17, fontweight="bold")
    figure.subplots_adjust(left=0.08, right=0.985, top=0.92, bottom=0.055)
    return figure
