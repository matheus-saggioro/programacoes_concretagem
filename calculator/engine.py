from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable

import pandas as pd

from calculator.models import Concretagem, EtapaViagem, ResultadoCalculo, Viagem
from calculator.scheduling import LaneResource, TruckFleet, TruckState, simular_descarga_com_fila
from calculator.utils import (
    bt_group_label,
    format_clock,
    front_resource_key,
    minutes_between,
    round_minutes,
)


EPSILON = 1e-6
MIN_BT_LOAD_M3 = 3.0


@dataclass(slots=True)
class PlantContext:
    usina: str
    mistura: LaneResource
    dosagem: LaneResource


@dataclass(slots=True)
class FrontContext:
    key: str
    label: str
    categoria: str
    recurso: LaneResource
    intervalo_maximo_entre_descargas_min: float | None = None


@dataclass(slots=True)
class CandidateTrip:
    concretagem: Concretagem
    viagem: Viagem
    truck: TruckState
    truck_ready: datetime
    planned_start: datetime
    mix_start: datetime


@dataclass(slots=True)
class SequencingContext:
    enabled: bool
    ordered_ids_by_group: dict[str, list[str]]
    active_id_by_group: dict[str, str | None]


def validar_concretagens(concretagens: Iterable[Concretagem]) -> None:
    concretagens = list(concretagens)
    if not concretagens:
        raise ValueError("Informe ao menos uma concretagem.")

    for concretagem in concretagens:
        if concretagem.volume_total_m3 <= 0:
            raise ValueError(
                f"{concretagem.nome_programacao}: o volume total deve ser maior que zero."
            )
        if concretagem.capacidade_bt_m3 <= 0:
            raise ValueError(
                f"{concretagem.nome_programacao}: a capacidade da BT deve ser maior que zero."
            )
        if concretagem.capacidade_bt_m3 + EPSILON < MIN_BT_LOAD_M3:
            raise ValueError(
                f"{concretagem.nome_programacao}: a capacidade da BT deve ser de pelo menos "
                f"{round_minutes(MIN_BT_LOAD_M3, 1)} m³."
            )
        if concretagem.restricoes.max_bts_frente <= 0:
            raise ValueError(
                f"{concretagem.nome_programacao}: a simultaneidade máxima na frente/bomba deve ser maior que zero."
            )
        if concretagem.restricoes.max_bts_mistura <= 0:
            raise ValueError(
                f"{concretagem.nome_programacao}: a simultaneidade máxima na mistura deve ser maior que zero."
            )
        if concretagem.restricoes.max_bts_dosagem <= 0:
            raise ValueError(
                f"{concretagem.nome_programacao}: a simultaneidade máxima na dosagem deve ser maior que zero."
            )
        if (
            concretagem.restricoes.existe_intervalo_maximo_entre_descargas
            and concretagem.restricoes.intervalo_maximo_entre_descargas_min <= 0
        ):
            raise ValueError(
                f"{concretagem.nome_programacao}: o intervalo máximo entre descargas deve ser maior que zero."
            )

        ciclo = concretagem.ciclo
        for nome, valor in ciclo.as_rows():
            if valor < 0:
                raise ValueError(
                    f"{concretagem.nome_programacao}: o tempo de {nome.lower()} não pode ser negativo."
                )

        if concretagem.restricoes.permitir_primeira_viagem_customizada:
            volume_primeira = concretagem.restricoes.volume_primeira_viagem_m3
            if volume_primeira is None or volume_primeira <= 0:
                raise ValueError(
                    f"{concretagem.nome_programacao}: informe um volume válido para a primeira viagem."
                )
            if volume_primeira - concretagem.capacidade_bt_m3 > EPSILON:
                raise ValueError(
                    f"{concretagem.nome_programacao}: o volume da primeira viagem não pode exceder a capacidade da BT."
                )
            if volume_primeira - concretagem.volume_total_m3 > EPSILON:
                raise ValueError(
                    f"{concretagem.nome_programacao}: o volume da primeira viagem não pode exceder o volume total."
                )
            if volume_primeira + EPSILON < MIN_BT_LOAD_M3:
                raise ValueError(
                    f"{concretagem.nome_programacao}: a primeira viagem customizada deve ter pelo menos "
                    f"{round_minutes(MIN_BT_LOAD_M3, 1)} m³."
                )

        volumes = distribuir_volumes(concretagem)
        if not volumes:
            raise ValueError(
                f"{concretagem.nome_programacao}: não foi possível gerar as viagens com os dados informados."
            )


def _rebalance_last_trip_to_minimum(
    volumes: list[float],
    minimum_load: float,
    custom_first_locked: bool,
) -> list[float]:
    if not volumes:
        return volumes
    if len(volumes) == 1:
        if volumes[0] + EPSILON < minimum_load:
            raise ValueError(
                f"O volume total da concretagem deve ser de pelo menos {round_minutes(minimum_load, 1)} m³."
            )
        return [round(volumes[0], 3)]

    adjusted = [float(volume) for volume in volumes]
    if adjusted[-1] + EPSILON >= minimum_load:
        return [round(volume, 3) for volume in adjusted]

    needed = minimum_load - adjusted[-1]
    donor_start = 1 if custom_first_locked else 0
    for index in range(len(adjusted) - 2, donor_start - 1, -1):
        available = max(0.0, adjusted[index] - minimum_load)
        transfer = min(needed, available)
        if transfer <= EPSILON:
            continue
        adjusted[index] -= transfer
        adjusted[-1] += transfer
        needed -= transfer
        if needed <= EPSILON:
            break

    if adjusted[-1] + EPSILON < minimum_load:
        raise ValueError(
            f"Não foi possível distribuir as viagens com carga mínima de "
            f"{round_minutes(minimum_load, 1)} m³ por BT."
        )

    for index, volume in enumerate(adjusted):
        if volume + EPSILON < minimum_load:
            label = "a primeira viagem" if index == 0 else f"a viagem {index + 1}"
            raise ValueError(
                f"Não foi possível manter {label} com ao menos "
                f"{round_minutes(minimum_load, 1)} m³."
            )

    return [round(volume, 3) for volume in adjusted]


def distribuir_volumes(concretagem: Concretagem) -> list[float]:
    capacidade = concretagem.capacidade_bt_m3
    restante = concretagem.volume_total_m3
    volumes: list[float] = []

    if concretagem.restricoes.permitir_primeira_viagem_customizada:
        volume_primeira = concretagem.restricoes.volume_primeira_viagem_m3 or 0.0
        volumes.append(round(volume_primeira, 3))
        restante -= volume_primeira

    while restante > EPSILON:
        if restante > capacidade + EPSILON:
            volumes.append(round(capacidade, 3))
            restante -= capacidade
            continue

        if abs(restante - capacidade) <= EPSILON:
            volumes.append(round(capacidade, 3))
            restante = 0.0
            continue

        if not concretagem.restricoes.ultima_viagem_parcial_proporcional:
            raise ValueError(
                f"{concretagem.nome_programacao}: o volume total exige viagem parcial final, "
                "mas a opção de descarga proporcional está desativada."
            )
        volumes.append(round(restante, 3))
        restante = 0.0

    return _rebalance_last_trip_to_minimum(
        volumes,
        MIN_BT_LOAD_M3,
        concretagem.restricoes.permitir_primeira_viagem_customizada,
    )


def gerar_viagens(concretagens: Iterable[Concretagem]) -> dict[str, list[Viagem]]:
    viagens_por_cenario: dict[str, list[Viagem]] = {}
    for concretagem in concretagens:
        volumes = distribuir_volumes(concretagem)
        viagens_por_cenario[concretagem.id] = [
            Viagem(
                concretagem_id=concretagem.id,
                nome_programacao=concretagem.nome_programacao,
                numero_viagem=indice,
                volume_m3=volume,
                grupo_bt=concretagem.grupo_bt,
            )
            for indice, volume in enumerate(volumes, start=1)
        ]
    return viagens_por_cenario


def calcular_duracao_descarga(concretagem: Concretagem, volume_viagem: float) -> float:
    base = concretagem.ciclo.descarga_min
    if not concretagem.restricoes.ultima_viagem_parcial_proporcional:
        return base
    if abs(volume_viagem - concretagem.capacidade_bt_m3) <= EPSILON:
        return base
    return base * (volume_viagem / concretagem.capacidade_bt_m3)


def _preview_trip_timeline(
    concretagem: Concretagem,
    trip_start: datetime,
    plant: PlantContext,
    front_context: FrontContext,
    volume_viagem: float,
):
    mix_preview = plant.mistura.peek(
        trip_start,
        concretagem.ciclo.mistura_min,
    )
    dose_preview = plant.dosagem.peek(
        mix_preview.end,
        concretagem.ciclo.dosagem_min,
    )
    slump_end = (
        dose_preview.end
        + timedelta(minutes=concretagem.ciclo.ida_min + concretagem.ciclo.slump_min)
    )
    descarga_duration = calcular_duracao_descarga(concretagem, volume_viagem)
    front_preview = front_context.recurso.peek(slump_end, descarga_duration)
    return mix_preview, dose_preview, slump_end, front_preview


def _plan_trip_start(
    concretagem: Concretagem,
    trip: Viagem,
    truck_ready: datetime,
    plant: PlantContext,
    front_context: FrontContext,
) -> tuple[datetime, datetime]:
    planned_start = truck_ready

    for _ in range(6):
        mix_preview, dose_preview, slump_end, front_preview = _preview_trip_timeline(
            concretagem,
            planned_start,
            plant,
            front_context,
            trip.volume_m3,
        )
        wait_for_mix = minutes_between(planned_start, mix_preview.start)
        wait_for_dose = minutes_between(mix_preview.end, dose_preview.start)
        wait_for_pump = 0.0
        if concretagem.restricoes.com_bomba and concretagem.restricoes.max_bts_frente == 1:
            wait_for_pump = minutes_between(slump_end, front_preview.start)

        wait_to_reduce = max(wait_for_mix, wait_for_dose, wait_for_pump)
        if wait_to_reduce <= EPSILON:
            return planned_start, mix_preview.start

        adjusted_start = planned_start + timedelta(minutes=wait_to_reduce)
        if adjusted_start <= planned_start:
            break
        planned_start = adjusted_start

    mix_preview, _dose_preview, _slump_end, _front_preview = _preview_trip_timeline(
        concretagem,
        planned_start,
        plant,
        front_context,
        trip.volume_m3,
    )
    return planned_start, mix_preview.start


def aplicar_restricoes_compartilhadas(
    concretagens: Iterable[Concretagem],
) -> tuple[dict[str, PlantContext], dict[str, FrontContext], list[str]]:
    concretagens = list(concretagens)
    warnings: list[str] = []

    por_usina: dict[str, list[Concretagem]] = defaultdict(list)
    por_frente: dict[str, list[Concretagem]] = defaultdict(list)
    for concretagem in concretagens:
        por_usina[concretagem.usina].append(concretagem)
        por_frente[
            front_resource_key(
                concretagem.local,
                concretagem.elemento_frente,
                concretagem.restricoes.com_bomba,
            )
        ].append(concretagem)

    plantas: dict[str, PlantContext] = {}
    for usina, grupo in por_usina.items():
        mistura_caps = {item.restricoes.max_bts_mistura for item in grupo}
        dosagem_caps = {item.restricoes.max_bts_dosagem for item in grupo}
        intervalos = {round(item.restricoes.intervalo_efetivo_min, 6) for item in grupo}

        if len(mistura_caps) > 1:
            warnings.append(
                f"Usina {usina}: capacidades de mistura divergentes encontradas. "
                f"Foi adotado o menor valor ({min(mistura_caps)})."
            )
        if len(dosagem_caps) > 1:
            warnings.append(
                f"Usina {usina}: capacidades de dosagem divergentes encontradas. "
                f"Foi adotado o menor valor ({min(dosagem_caps)})."
            )
        if len(intervalos) > 1:
            warnings.append(
                f"Usina {usina}: intervalos entre misturas divergentes encontrados. "
                f"Foi adotado o maior valor ({max(intervalos)} min)."
            )

        plantas[usina] = PlantContext(
            usina=usina,
            mistura=LaneResource(
                name=f"Mistura - {usina}",
                capacity=min(mistura_caps),
                min_gap_minutes=max(intervalos),
            ),
            dosagem=LaneResource(
                name=f"Dosagem - {usina}",
                capacity=min(dosagem_caps),
            ),
        )

    frentes: dict[str, FrontContext] = {}
    for key, grupo in por_frente.items():
        caps = {item.restricoes.max_bts_frente for item in grupo}
        intervalos_max_descarga = {
            round(item.restricoes.intervalo_maximo_entre_descargas_min, 6)
            for item in grupo
            if item.restricoes.existe_intervalo_maximo_entre_descargas
        }
        if len(caps) > 1:
            warnings.append(
                f"Frente {grupo[0].local} / {grupo[0].elemento_frente}: limites divergentes na descarga. "
                f"Foi adotado o menor valor ({min(caps)})."
            )
        if intervalos_max_descarga and (
            len(intervalos_max_descarga) > 1 or len(intervalos_max_descarga) != len(grupo)
        ):
            warnings.append(
                f"Frente {grupo[0].local} / {grupo[0].elemento_frente}: limites máximos entre descargas divergentes encontrados. "
                f"Foi adotado o menor valor ({min(intervalos_max_descarga)} min)."
            )
        referencia = grupo[0]
        categoria = "bomba" if referencia.restricoes.com_bomba else "frente"
        frentes[key] = FrontContext(
            key=key,
            label=f"{referencia.local} / {referencia.elemento_frente}",
            categoria=categoria,
            recurso=LaneResource(
                name=f"Descarga - {referencia.local} / {referencia.elemento_frente}",
                capacity=min(caps),
            ),
            intervalo_maximo_entre_descargas_min=(
                min(intervalos_max_descarga) if intervalos_max_descarga else None
            ),
        )

    return plantas, frentes, warnings


def _group_metadata(
    concretagens: Iterable[Concretagem],
) -> tuple[list[str], dict[str, str], dict[str, list[Concretagem]]]:
    ordered_keys: list[str] = []
    labels: dict[str, str] = {}
    members: dict[str, list[Concretagem]] = defaultdict(list)
    for concretagem in concretagens:
        key = concretagem.grupo_bt
        if key not in labels:
            ordered_keys.append(key)
            labels[key] = bt_group_label(
                concretagem.restricoes.alocacao_bts,
                concretagem.usina,
                concretagem.nome_programacao,
            )
        members[key].append(concretagem)
    return ordered_keys, labels, members


def _resolve_fixed_bt_counts(
    concretagens: Iterable[Concretagem],
) -> tuple[dict[str, int], dict[str, str], list[str]]:
    group_keys, labels, members = _group_metadata(concretagens)
    counts: dict[str, int] = {}
    warnings: list[str] = []

    for key in group_keys:
        group = members[key]
        if group[0].restricoes.alocacao_bts == "compartilhadas":
            informed = [item.numero_bts_fixo for item in group if item.numero_bts_fixo]
            if not informed:
                raise ValueError(
                    f"{labels[key]}: informe a quantidade fixa de BTs disponível para a simulação."
                )
            if len(set(informed)) > 1:
                warnings.append(
                    f"{labels[key]}: quantidades fixas divergentes informadas entre frentes compartilhadas. "
                    f"Foi adotado o maior valor ({max(informed)})."
                )
            counts[key] = max(informed)
        else:
            informed = group[0].numero_bts_fixo
            if not informed:
                raise ValueError(
                    f"{group[0].nome_programacao}: informe a quantidade fixa de BTs disponível."
                )
            counts[key] = informed

    return counts, labels, warnings


def _build_fleets(
    group_keys: list[str],
    labels: dict[str, str],
    bt_counts: dict[str, int],
    base_date: date,
) -> dict[str, TruckFleet]:
    fleets: dict[str, TruckFleet] = {}
    initial_time = datetime.combine(base_date, time(0, 0))

    for sequence, key in enumerate(group_keys, start=1):
        count_bt = bt_counts.get(key, 0)
        if count_bt <= 0:
            raise ValueError(f"{labels[key]}: a quantidade de BTs deve ser maior que zero.")
        prefix = "SH" if key.startswith("shared::") else f"D{sequence}"
        fleets[key] = TruckFleet(
            group_key=key,
            label=labels[key],
            trucks=[
                TruckState(truck_id=f"{prefix}-{indice:02d}", available_at=initial_time)
                for indice in range(1, count_bt + 1)
            ],
        )
    return fleets


def _append_stage(
    trip: Viagem,
    etapas: list[EtapaViagem],
    etapa: str,
    inicio: datetime,
    fim: datetime,
    observacao: str = "",
) -> None:
    if fim <= inicio:
        return
    item = EtapaViagem(
        concretagem_id=trip.concretagem_id,
        nome_programacao=trip.nome_programacao,
        bt=trip.bt,
        viagem=trip.numero_viagem,
        volume_m3=trip.volume_m3,
        etapa=etapa,
        inicio=inicio,
        fim=fim,
        duracao_min=minutes_between(inicio, fim),
        observacao=observacao,
    )
    trip.etapas.append(item)
    etapas.append(item)


def _describe_restrictions(concretagem: Concretagem) -> str:
    frente_label = "bomba" if concretagem.restricoes.com_bomba else "frente"
    partes = [
        f"{frente_label}: {concretagem.restricoes.max_bts_frente} BT simultânea(s)",
        f"mistura: {concretagem.restricoes.max_bts_mistura}",
        f"dosagem: {concretagem.restricoes.max_bts_dosagem}",
        f"BTs {concretagem.restricoes.alocacao_bts}",
    ]
    if concretagem.restricoes.existe_intervalo_entre_misturas:
        partes.append(
            f"intervalo entre misturas: {round_minutes(concretagem.restricoes.intervalo_efetivo_min)} min"
        )
    if concretagem.restricoes.existe_intervalo_maximo_entre_descargas:
        partes.append(
            "intervalo máximo entre descargas: "
            f"{round_minutes(concretagem.restricoes.intervalo_maximo_entre_descargas_min)} min"
        )
    if concretagem.restricoes.permitir_primeira_viagem_customizada:
        partes.append(
            f"1ª viagem customizada: {round_minutes(concretagem.restricoes.volume_primeira_viagem_m3 or 0)} m³"
        )
    if concretagem.restricoes.ultima_viagem_parcial_proporcional:
        partes.append("última viagem parcial proporcional")
    return "; ".join(partes)


def _create_detalhamento_dataframe(resultado: ResultadoCalculo) -> pd.DataFrame:
    stage_order = {
        "Espera mistura": 0,
        "Mistura": 1,
        "Espera dosagem": 2,
        "Dosagem": 3,
        "Ida": 4,
        "Slump": 5,
        "Espera bomba": 6,
        "Espera frente": 6,
        "Descarga": 7,
        "Lavagem": 8,
        "Volta": 9,
    }
    rows = []
    for etapa in sorted(
        resultado.etapas,
        key=lambda item: (
            item.inicio,
            item.nome_programacao,
            item.viagem,
            stage_order.get(item.etapa, 99),
        ),
    ):
        rows.append(
            {
                "Programação": etapa.nome_programacao,
                "BT": etapa.bt,
                "Viagem": etapa.viagem,
                "Volume da viagem (m³)": round(etapa.volume_m3, 3),
                "Etapa": etapa.etapa,
                "Início": format_clock(etapa.inicio, resultado.data_base),
                "Fim": format_clock(etapa.fim, resultado.data_base),
                "Duração (min)": round_minutes(etapa.duracao_min, 2),
                "Observação": etapa.observacao,
            }
        )
    return pd.DataFrame(rows)


def _resource_utilization(resource: LaneResource) -> float:
    if not resource.allocations:
        return 0.0
    start = min(item[0] for item in resource.allocations)
    end = max(item[1] for item in resource.allocations)
    span = minutes_between(start, end)
    if span <= 0:
        return 0.0
    busy = sum(minutes_between(item[0], item[1]) for item in resource.allocations)
    return busy / (resource.capacity * span)


def _fleet_utilization(fleet: TruckFleet, trips: Iterable[Viagem]) -> float:
    relevant = [trip for trip in trips if trip.grupo_bt == fleet.group_key and trip.inicio_viagem and trip.fim_viagem]
    if not relevant:
        return 0.0
    start = min(trip.inicio_viagem for trip in relevant if trip.inicio_viagem is not None)
    end = max(trip.fim_viagem for trip in relevant if trip.fim_viagem is not None)
    span = minutes_between(start, end)
    if span <= 0:
        return 0.0
    busy = sum(
        minutes_between(trip.inicio_viagem, trip.fim_viagem)
        for trip in relevant
        if trip.inicio_viagem and trip.fim_viagem
    )
    return busy / (len(fleet.trucks) * span)


def _identify_bottlenecks(
    waits_by_resource: dict[str, float],
    plants: dict[str, PlantContext],
    fronts: dict[str, FrontContext],
    fleets: dict[str, TruckFleet],
    trips: list[Viagem],
) -> tuple[str, str]:
    gargalo_por_espera = "sem espera"
    if any(value > EPSILON for value in waits_by_resource.values()):
        gargalo_por_espera = max(waits_by_resource, key=lambda key: waits_by_resource[key])

    scores = {
        "mistura": max((_resource_utilization(plant.mistura) for plant in plants.values()), default=0.0),
        "dosagem": max((_resource_utilization(plant.dosagem) for plant in plants.values()), default=0.0),
        "bomba": max(
            (_resource_utilization(front.recurso) for front in fronts.values() if front.categoria == "bomba"),
            default=0.0,
        ),
        "frente": max(
            (_resource_utilization(front.recurso) for front in fronts.values() if front.categoria == "frente"),
            default=0.0,
        ),
        "número insuficiente de BTs": max(
            (_fleet_utilization(fleet, trips) for fleet in fleets.values()),
            default=0.0,
        ),
    }
    recurso_mais_ocupado = max(scores, key=lambda key: scores[key])
    return gargalo_por_espera, recurso_mais_ocupado


def _generate_premissas(
    concretagens: Iterable[Concretagem],
    bt_counts: dict[str, int],
    bt_group_labels: dict[str, str],
    sequenciamento_prioridade_ativo: bool,
    base_date: date,
) -> list[str]:
    concretagens = list(concretagens)
    premissas = [
        f"Data-base da simulação: {base_date.strftime('%d/%m/%Y')}.",
        f"Carga mínima considerada por BT: {round_minutes(MIN_BT_LOAD_M3, 1)} m³.",
        "Prazo principal avaliado pelo término da descarga.",
        "Término da volta é exibido separadamente e não define atendimento ao prazo.",
        "A mesma BT é reaproveitada apenas após o fim da volta.",
    ]
    if sequenciamento_prioridade_ativo:
        premissas.append(
            "Quando há conflito por recursos compartilhados da operação, as programações são sequenciadas pelo horário de início e, em empate, por prioridade, prazo e ordem de cadastro."
        )
    else:
        premissas.append(
            "Quando há recursos compartilhados, o agendamento segue a menor data de início possível e desempate pela ordem de cadastro."
        )
    if any(
        item.restricoes.com_bomba and item.restricoes.max_bts_frente == 1
        for item in concretagens
    ):
        premissas.append(
            "Em operações com bomba e 1 BT por vez, o carregamento é ajustado para reduzir fila na bomba e manter o bombeamento mais contínuo."
        )
    premissas.append(
        "O início da viagem pode ser ajustado para reduzir esperas excessivas antes da mistura, da dosagem e, quando aplicável, da bomba."
    )
    if any(item.restricoes.existe_intervalo_maximo_entre_descargas for item in concretagens):
        premissas.append(
            "Quando configurado, o sistema verifica o intervalo ocioso entre o fim de uma descarga e o início da próxima na mesma frente."
        )

    for key, count_bt in bt_counts.items():
        premissas.append(f"{bt_group_labels[key]}: {count_bt} BT(s) considerada(s) na simulação.")

    for concretagem in concretagens:
        descarga = "bomba" if concretagem.restricoes.com_bomba else "frente"
        alocacao = (
            "BTs dedicadas"
            if concretagem.restricoes.alocacao_bts == "dedicadas"
            else "BTs compartilhadas"
        )
        prazo = format_clock(concretagem.prazo_datetime(base_date), base_date)
        premissas.append(
            f"{concretagem.nome_programacao}: início {concretagem.inicio_primeira_mistura.strftime('%H:%M')}, "
            f"prazo {prazo}, descarga via {descarga}, {alocacao}, "
            f"capacidade da BT {round_minutes(concretagem.capacidade_bt_m3)} m³."
        )
        premissas.append(
            f"{concretagem.nome_programacao}: simultaneidade na frente {concretagem.restricoes.max_bts_frente}, "
            f"mistura {concretagem.restricoes.max_bts_mistura}, dosagem {concretagem.restricoes.max_bts_dosagem}."
        )
        if concretagem.restricoes.existe_intervalo_entre_misturas:
            premissas.append(
                f"{concretagem.nome_programacao}: intervalo obrigatório entre misturas de "
                f"{round_minutes(concretagem.restricoes.intervalo_entre_misturas_min, 1)} min."
            )
        if concretagem.restricoes.existe_intervalo_maximo_entre_descargas:
            premissas.append(
                f"{concretagem.nome_programacao}: intervalo máximo entre descargas de "
                f"{round_minutes(concretagem.restricoes.intervalo_maximo_entre_descargas_min, 1)} min."
            )
        if concretagem.restricoes.permitir_primeira_viagem_customizada:
            premissas.append(
                f"{concretagem.nome_programacao}: 1ª viagem customizada em "
                f"{round_minutes(concretagem.restricoes.volume_primeira_viagem_m3 or 0.0, 2)} m³."
            )
        if concretagem.restricoes.ultima_viagem_parcial_proporcional:
            premissas.append(
                f"{concretagem.nome_programacao}: última viagem parcial com descarga proporcional."
            )
    return premissas


def _build_sequencing_context(
    concretagens: Iterable[Concretagem],
    sequenciar_por_prioridade: bool,
) -> SequencingContext:
    concretagens = list(concretagens)
    if not sequenciar_por_prioridade:
        return SequencingContext(
            enabled=False,
            ordered_ids_by_group={},
            active_id_by_group={},
        )

    members_by_group: dict[str, list[Concretagem]] = defaultdict(list)
    for concretagem in concretagens:
        members_by_group[concretagem.grupo_bt].append(concretagem)

    ordered_ids_by_group: dict[str, list[str]] = {}
    active_id_by_group: dict[str, str | None] = {}
    for group_key, members in members_by_group.items():
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
        ordered_ids_by_group[group_key] = [item.id for item in ordered]
        active_id_by_group[group_key] = None

    return SequencingContext(
        enabled=bool(ordered_ids_by_group),
        ordered_ids_by_group=ordered_ids_by_group,
        active_id_by_group=active_id_by_group,
    )


def _resolve_group_active_concretagem(
    group_key: str,
    sequencing: SequencingContext,
    trips_by_scenario: dict[str, list[Viagem]],
    next_trip_index: dict[str, int],
) -> str | None:
    if not sequencing.enabled or group_key not in sequencing.ordered_ids_by_group:
        return None

    active_id = sequencing.active_id_by_group.get(group_key)
    if active_id is not None and next_trip_index[active_id] < len(trips_by_scenario[active_id]):
        return active_id

    for concretagem_id in sequencing.ordered_ids_by_group[group_key]:
        if next_trip_index[concretagem_id] < len(trips_by_scenario[concretagem_id]):
            sequencing.active_id_by_group[group_key] = concretagem_id
            return concretagem_id

    sequencing.active_id_by_group[group_key] = None
    return None


def _priority_sort_value(prioridade: int) -> int:
    return prioridade if prioridade > 0 else 999


def _build_discharge_interval_analysis(
    concretagens: list[Concretagem],
    trips_by_scenario: dict[str, list[Viagem]],
    fronts: dict[str, FrontContext],
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]], bool]:
    eventos_por_frente: dict[str, list[dict[str, object]]] = defaultdict(list)

    for concretagem in concretagens:
        front_key = front_resource_key(
            concretagem.local,
            concretagem.elemento_frente,
            concretagem.restricoes.com_bomba,
        )
        front_context = fronts[front_key]
        if front_context.intervalo_maximo_entre_descargas_min is None:
            continue

        for trip in trips_by_scenario[concretagem.id]:
            descarga = next((etapa for etapa in trip.etapas if etapa.etapa == "Descarga"), None)
            if descarga is None:
                continue
            eventos_por_frente[front_key].append(
                {
                    "nome_programacao": trip.nome_programacao,
                    "viagem": trip.numero_viagem,
                    "bt": trip.bt,
                    "inicio": descarga.inicio,
                    "fim": descarga.fim,
                }
            )

    intervalos: list[dict[str, object]] = []
    resumo_por_frente: dict[str, dict[str, object]] = {}

    for front_key, front_context in fronts.items():
        limite = front_context.intervalo_maximo_entre_descargas_min
        if limite is None:
            continue

        eventos = sorted(
            eventos_por_frente.get(front_key, []),
            key=lambda item: (item["inicio"], item["fim"], item["nome_programacao"], item["viagem"]),
        )
        maior_intervalo = 0.0
        atende = True
        violacoes = 0

        if eventos:
            bloco_fim = eventos[0]["fim"]
            ultimo_evento_bloco = eventos[0]
            for evento in eventos[1:]:
                if evento["inicio"] <= bloco_fim:
                    if evento["fim"] > bloco_fim:
                        bloco_fim = evento["fim"]
                        ultimo_evento_bloco = evento
                    continue

                intervalo = minutes_between(bloco_fim, evento["inicio"])
                maior_intervalo = max(maior_intervalo, intervalo)
                violacao = intervalo - limite > EPSILON
                if violacao:
                    atende = False
                    violacoes += 1
                intervalos.append(
                    {
                        "frente_key": front_key,
                        "frente_label": front_context.label,
                        "categoria": front_context.categoria,
                        "limite_min": limite,
                        "intervalo_min": intervalo,
                        "violacao": violacao,
                        "fim_descarga_anterior": bloco_fim,
                        "inicio_proxima_descarga": evento["inicio"],
                        "programacao_anterior": ultimo_evento_bloco["nome_programacao"],
                        "viagem_anterior": ultimo_evento_bloco["viagem"],
                        "programacao_proxima": evento["nome_programacao"],
                        "viagem_proxima": evento["viagem"],
                    }
                )
                bloco_fim = evento["fim"]
                ultimo_evento_bloco = evento

        resumo_por_frente[front_key] = {
            "limite_min": limite,
            "maior_intervalo_min": maior_intervalo,
            "atende": atende,
            "violacoes": violacoes,
            "frente_label": front_context.label,
            "categoria": front_context.categoria,
        }

    atende_global = all(item["atende"] for item in resumo_por_frente.values()) if resumo_por_frente else True
    return intervalos, resumo_por_frente, atende_global


def _group_continuity_satisfied(
    resultado: ResultadoCalculo,
    concretagens: list[Concretagem],
    group_key: str,
) -> bool:
    relevant_ids = {
        item.id
        for item in concretagens
        if item.grupo_bt == group_key and item.restricoes.existe_intervalo_maximo_entre_descargas
    }
    if not relevant_ids:
        return True

    resumo_por_id = {item["id"]: item for item in resultado.resumo}
    return all(
        resumo_por_id.get(concretagem_id, {}).get("atende_intervalo_descargas", True)
        for concretagem_id in relevant_ids
    )


def _continuity_violation_metrics(resultado: ResultadoCalculo) -> tuple[int, float]:
    violation_count = 0
    violation_total = 0.0
    for intervalo in resultado.intervalos_descarga:
        if not intervalo.get("violacao"):
            continue
        violation_count += 1
        violation_total += max(
            0.0,
            float(intervalo["intervalo_min"]) - float(intervalo["limite_min"]),
        )
    return violation_count, violation_total


def _suggest_bt_counts_for_continuity(
    concretagens: list[Concretagem],
    bt_counts: dict[str, int],
    sequenciar_por_prioridade: bool,
    base_date: date,
) -> dict[str, int]:
    groups_with_continuity = {
        item.grupo_bt
        for item in concretagens
        if item.restricoes.existe_intervalo_maximo_entre_descargas
    }
    if not groups_with_continuity:
        return {}

    suggestions: dict[str, int] = {}
    trips_by_scenario = gerar_viagens(concretagens)
    cached_results: dict[tuple[tuple[str, int], ...], ResultadoCalculo] = {}

    for group_key in groups_with_continuity:
        current_count = bt_counts.get(group_key, 0)
        group_trip_count = sum(
            len(trips_by_scenario[item.id]) for item in concretagens if item.grupo_bt == group_key
        )
        upper_bound = max(current_count + 8, current_count * 2, group_trip_count)

        for candidate_count in range(max(1, current_count), upper_bound + 1):
            candidate_counts = dict(bt_counts)
            candidate_counts[group_key] = candidate_count
            cache_key = tuple(sorted(candidate_counts.items()))
            candidate_result = cached_results.get(cache_key)
            if candidate_result is None:
                candidate_result = _simulate_with_bt_counts(
                    concretagens,
                    candidate_counts,
                    base_date=base_date,
                    automatico=False,
                    sequenciar_por_prioridade=sequenciar_por_prioridade,
                    include_recommendations=False,
                )
                cached_results[cache_key] = candidate_result
            if _group_continuity_satisfied(candidate_result, concretagens, group_key):
                suggestions[group_key] = candidate_count
                break

    return suggestions


def _build_summary(
    concretagens: list[Concretagem],
    trips_by_scenario: dict[str, list[Viagem]],
    bt_counts: dict[str, int],
    bt_group_labels: dict[str, str],
    base_date: date,
    intervalos_por_frente: dict[str, dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, bool], bool, float]:
    summary: list[dict[str, object]] = []
    prazo_por_cenario: dict[str, bool] = {}
    violacao_total = 0.0

    for concretagem in concretagens:
        trips = trips_by_scenario[concretagem.id]
        last_discharge = max((trip.fim_descarga for trip in trips), default=None)
        last_trip_end = max((trip.fim_viagem for trip in trips), default=None)
        deadline = concretagem.prazo_datetime(base_date)
        front_key = front_resource_key(
            concretagem.local,
            concretagem.elemento_frente,
            concretagem.restricoes.com_bomba,
        )
        intervalo_info = intervalos_por_frente.get(front_key, {})
        atende_prazo = deadline is None or (last_discharge is not None and last_discharge <= deadline)
        prazo_por_cenario[concretagem.id] = atende_prazo

        if deadline is not None and last_discharge is not None and last_discharge > deadline:
            violacao_total += minutes_between(deadline, last_discharge)

        summary.append(
            {
                "id": concretagem.id,
                "nome_programacao": concretagem.nome_programacao,
                "local": concretagem.local,
                "elemento_frente": concretagem.elemento_frente,
                "inicio_primeira_mistura": concretagem.inicio_primeira_mistura,
                "prioridade": concretagem.prioridade,
                "volume_total_m3": concretagem.volume_total_m3,
                "capacidade_bt_m3": concretagem.capacidade_bt_m3,
                "numero_viagens": len(trips),
                "volume_ultima_viagem_m3": trips[-1].volume_m3 if trips else 0.0,
                "volume_primeira_viagem_m3": trips[0].volume_m3 if trips else 0.0,
                "bts_utilizadas": bt_counts[concretagem.grupo_bt],
                "bts_sugeridas_continuidade": None,
                "grupo_bt_label": bt_group_labels[concretagem.grupo_bt],
                "termino_ultima_descarga_raw": last_discharge,
                "termino_ultima_viagem_raw": last_trip_end,
                "prazo_raw": deadline,
                "atende_prazo": atende_prazo,
                "intervalo_maximo_descargas_min": intervalo_info.get("limite_min"),
                "maior_intervalo_descargas_min": intervalo_info.get("maior_intervalo_min", 0.0),
                "atende_intervalo_descargas": intervalo_info.get("atende", True),
                "restricoes_adotadas": _describe_restrictions(concretagem),
            }
        )

    return summary, prazo_por_cenario, all(prazo_por_cenario.values()), violacao_total


def _build_recommendations(
    concretagens: list[Concretagem],
    bt_counts: dict[str, int],
    bt_group_labels: dict[str, str],
    continuidade_bt_sugerida: dict[str, int],
    gargalo: str,
    prazo_atendido: bool,
    atende_intervalo_descargas: bool,
    intervalos_descarga: list[dict[str, object]],
    violacao_total_min: float,
    automatico: bool,
    limite_bt_testado_atingido: bool = False,
) -> list[str]:
    if prazo_atendido and atende_intervalo_descargas:
        return []

    recomendacoes: list[str] = []
    if not prazo_atendido:
        atraso = round_minutes(violacao_total_min, 1)
        recomendacoes.append(
            f"Antecipar o início da 1ª mistura em pelo menos {atraso} min para eliminar o atraso hoje calculado."
        )

    if gargalo == "mistura":
        max_mistura = max(item.restricoes.max_bts_mistura for item in concretagens)
        recomendacoes.append(
            f"Revisar a capacidade de mistura da usina. O cenário está limitado a {max_mistura} BT(s) simultânea(s) na mistura."
        )
        recomendacoes.append(
            "Reduzir o tempo de mistura e/ou dosagem por viagem pode destravar a saída das primeiras cargas."
        )
    elif gargalo == "dosagem":
        max_dosagem = max(item.restricoes.max_bts_dosagem for item in concretagens)
        recomendacoes.append(
            f"Aumentar a simultaneidade de dosagem acima de {max_dosagem} BT(s) pode reduzir o atraso."
        )
        recomendacoes.append(
            "Revisar o tempo de dosagem por viagem tende a trazer ganho direto no prazo final."
        )
    elif gargalo == "bomba":
        max_frente = max(item.restricoes.max_bts_frente for item in concretagens if item.restricoes.com_bomba)
        recomendacoes.append(
            f"A bomba/frente está limitando o cenário. Avalie elevar a simultaneidade de descarga acima de {max_frente} BT(s) ou reduzir o tempo de descarga."
        )
        recomendacoes.append(
            "Se a simultaneidade não puder mudar, antecipar o início da concretagem costuma ser a alternativa mais direta."
        )
    elif gargalo == "frente":
        max_frente = max(item.restricoes.max_bts_frente for item in concretagens if not item.restricoes.com_bomba)
        recomendacoes.append(
            f"A frente de descarga está limitando o cenário. Avalie elevar a simultaneidade acima de {max_frente} BT(s)."
        )
    elif gargalo == "número insuficiente de BTs":
        recomendacoes.append(
            "Aumentar a quantidade de BTs disponíveis para a frente pode reduzir o prazo total."
        )
        if automatico and limite_bt_testado_atingido:
            recomendacoes.append(
                "O limite máximo de BTs testado no dimensionamento automático pode estar baixo para este cenário."
            )

    if not atende_intervalo_descargas and intervalos_descarga:
        pior_intervalo = max(intervalos_descarga, key=lambda item: item["intervalo_min"])
        recomendacoes.append(
            "Reduzir o intervalo ocioso entre descargas na "
            f"{pior_intervalo['frente_label']}. O maior intervalo calculado foi de "
            f"{round_minutes(pior_intervalo['intervalo_min'], 1)} min, acima do limite de "
            f"{round_minutes(pior_intervalo['limite_min'], 1)} min."
        )
        recomendacoes.append(
            "Para manter a continuidade do bombeamento ou do elemento estrutural, avalie antecipar o carregamento das próximas BTs, reduzir mistura, dosagem e ida, ou aumentar a disponibilidade de BTs na operação."
        )
        referencia_por_grupo: dict[str, str] = {}
        for concretagem in concretagens:
            referencia_por_grupo.setdefault(concretagem.grupo_bt, concretagem.nome_programacao)

        for grupo_bt, bt_sugerida in continuidade_bt_sugerida.items():
            bt_atual = bt_counts.get(grupo_bt, 0)
            if bt_sugerida <= bt_atual:
                continue
            recomendacoes.append(
                f"Para atender a continuidade, a frota {bt_group_labels.get(grupo_bt, grupo_bt)} "
                f"tende a exigir pelo menos {bt_sugerida} BT(s). O cenário atual está com {bt_atual} BT(s). "
                f"Referência principal: {referencia_por_grupo.get(grupo_bt, grupo_bt)}."
            )

    recomendacoes.append(
        "Revisar tempos de ida, descarga e volta também pode ser eficaz quando a operação já está no limite dos recursos."
    )
    return recomendacoes


def _simulate_with_bt_counts(
    concretagens: Iterable[Concretagem],
    bt_counts: dict[str, int],
    base_date: date,
    automatico: bool = False,
    sequenciar_por_prioridade: bool = False,
    extra_warnings: list[str] | None = None,
    include_recommendations: bool = True,
) -> ResultadoCalculo:
    concretagens = list(concretagens)
    validar_concretagens(concretagens)

    data_base = base_date
    ordered_groups, bt_group_labels, _ = _group_metadata(concretagens)
    for group in ordered_groups:
        if bt_counts.get(group, 0) <= 0:
            raise ValueError(f"{bt_group_labels[group]}: a quantidade de BTs deve ser maior que zero.")

    trips_by_scenario = gerar_viagens(concretagens)
    plants, fronts, warnings = aplicar_restricoes_compartilhadas(concretagens)
    if extra_warnings:
        warnings.extend(extra_warnings)
    fleets = _build_fleets(ordered_groups, bt_group_labels, bt_counts, data_base)
    sequencing = _build_sequencing_context(concretagens, sequenciar_por_prioridade)

    next_trip_index = {concretagem.id: 0 for concretagem in concretagens}
    all_trips: list[Viagem] = []
    all_stages: list[EtapaViagem] = []
    waits_by_resource = {
        "mistura": 0.0,
        "dosagem": 0.0,
        "bomba": 0.0,
        "frente": 0.0,
    }

    while True:
        pending = []
        for concretagem in concretagens:
            trips = trips_by_scenario[concretagem.id]
            current_index = next_trip_index[concretagem.id]
            if current_index >= len(trips):
                continue
            active_id = _resolve_group_active_concretagem(
                concretagem.grupo_bt,
                sequencing,
                trips_by_scenario,
                next_trip_index,
            )
            if active_id is not None and active_id != concretagem.id:
                continue
            trip = trips[current_index]
            fleet = fleets[trip.grupo_bt]
            truck = fleet.peek_next_available()
            truck_ready = max(truck.available_at, concretagem.inicio_datetime(data_base))
            front_key = front_resource_key(
                concretagem.local,
                concretagem.elemento_frente,
                concretagem.restricoes.com_bomba,
            )
            plant_context = plants[concretagem.usina]
            front_context = fronts[front_key]
            planned_start, mix_start = _plan_trip_start(
                concretagem,
                trip,
                truck_ready,
                plant_context,
                front_context,
            )
            pending.append(
                CandidateTrip(
                    concretagem=concretagem,
                    viagem=trip,
                    truck=truck,
                    truck_ready=truck_ready,
                    planned_start=planned_start,
                    mix_start=mix_start,
                )
            )

        if not pending:
            break

        candidate = min(
            pending,
            key=lambda item: (
                item.mix_start,
                (
                    _priority_sort_value(item.concretagem.prioridade)
                    if sequenciar_por_prioridade
                    else item.concretagem.ordem
                ),
                item.concretagem.prazo_datetime(data_base) or datetime.max,
                item.concretagem.ordem,
                item.viagem.numero_viagem,
                item.truck.truck_id,
            ),
        )

        concretagem = candidate.concretagem
        trip = candidate.viagem
        fleet = fleets[trip.grupo_bt]
        truck = fleet.reserve_next_available()
        trip.bt = truck.truck_id

        trip.inicio_viagem = candidate.planned_start
        mix_allocation = plants[concretagem.usina].mistura.reserve(
            trip.inicio_viagem,
            concretagem.ciclo.mistura_min,
        )
        trip.espera_mistura_min = minutes_between(trip.inicio_viagem, mix_allocation.start)
        waits_by_resource["mistura"] += trip.espera_mistura_min
        if trip.espera_mistura_min > EPSILON:
            _append_stage(
                trip,
                all_stages,
                "Espera mistura",
                trip.inicio_viagem,
                mix_allocation.start,
                "Aguardando liberação da mistura.",
            )
        _append_stage(
            trip,
            all_stages,
            "Mistura",
            mix_allocation.start,
            mix_allocation.end,
            f"Usina {concretagem.usina} - faixa {mix_allocation.lane_index + 1}",
        )

        dose_allocation = plants[concretagem.usina].dosagem.reserve(
            mix_allocation.end,
            concretagem.ciclo.dosagem_min,
        )
        trip.espera_dosagem_min = minutes_between(mix_allocation.end, dose_allocation.start)
        waits_by_resource["dosagem"] += trip.espera_dosagem_min
        if trip.espera_dosagem_min > EPSILON:
            _append_stage(
                trip,
                all_stages,
                "Espera dosagem",
                mix_allocation.end,
                dose_allocation.start,
                "Aguardando faixa de dosagem.",
            )
        _append_stage(
            trip,
            all_stages,
            "Dosagem",
            dose_allocation.start,
            dose_allocation.end,
            f"Faixa {dose_allocation.lane_index + 1}",
        )

        ida_start = dose_allocation.end
        ida_end = ida_start + pd.to_timedelta(concretagem.ciclo.ida_min, unit="m")
        _append_stage(trip, all_stages, "Ida", ida_start, ida_end)

        slump_start = ida_end
        slump_end = slump_start + pd.to_timedelta(concretagem.ciclo.slump_min, unit="m")
        _append_stage(trip, all_stages, "Slump", slump_start, slump_end)

        front_key = front_resource_key(
            concretagem.local,
            concretagem.elemento_frente,
            concretagem.restricoes.com_bomba,
        )
        front_context = fronts[front_key]
        descarga_duration = calcular_duracao_descarga(concretagem, trip.volume_m3)
        descarga_allocation = simular_descarga_com_fila(
            front_context.recurso,
            slump_end,
            descarga_duration,
        )
        wait_descarga = minutes_between(slump_end, descarga_allocation.start)
        wait_stage_name = "Espera bomba" if concretagem.restricoes.com_bomba else "Espera frente"
        if concretagem.restricoes.com_bomba:
            trip.espera_bomba_min = wait_descarga
            waits_by_resource["bomba"] += wait_descarga
        else:
            trip.espera_frente_min = wait_descarga
            waits_by_resource["frente"] += wait_descarga
        if wait_descarga > EPSILON:
            _append_stage(
                trip,
                all_stages,
                wait_stage_name,
                slump_end,
                descarga_allocation.start,
                "Fila de descarga aguardando liberação da frente.",
            )

        _append_stage(
            trip,
            all_stages,
            "Descarga",
            descarga_allocation.start,
            descarga_allocation.end,
            f"Volume {round(trip.volume_m3, 3)} m³",
        )
        trip.fim_descarga = descarga_allocation.end

        lavagem_start = descarga_allocation.end
        lavagem_end = lavagem_start + pd.to_timedelta(concretagem.ciclo.lavagem_min, unit="m")
        _append_stage(trip, all_stages, "Lavagem", lavagem_start, lavagem_end)

        volta_start = lavagem_end
        volta_end = volta_start + pd.to_timedelta(concretagem.ciclo.volta_min, unit="m")
        _append_stage(trip, all_stages, "Volta", volta_start, volta_end)
        trip.fim_viagem = volta_end
        truck.available_at = volta_end

        all_trips.append(trip)
        next_trip_index[concretagem.id] += 1

    intervalos_descarga, resumo_intervalos_por_frente, atende_intervalo_descargas = (
        _build_discharge_interval_analysis(
            concretagens,
            trips_by_scenario,
            fronts,
        )
    )
    summary, prazo_por_cenario, prazo_atendido, violacao_total = _build_summary(
        concretagens,
        trips_by_scenario,
        bt_counts,
        bt_group_labels,
        data_base,
        resumo_intervalos_por_frente,
    )
    termino_ultima_descarga = max(
        (trip.fim_descarga for trip in all_trips if trip.fim_descarga is not None),
        default=None,
    )
    termino_ultima_viagem = max(
        (trip.fim_viagem for trip in all_trips if trip.fim_viagem is not None),
        default=None,
    )
    gargalo_por_espera, recurso_mais_ocupado = _identify_bottlenecks(
        waits_by_resource,
        plants,
        fronts,
        fleets,
        all_trips,
    )
    gargalo = gargalo_por_espera if gargalo_por_espera != "sem espera" else recurso_mais_ocupado
    result = ResultadoCalculo(
        concretagens=concretagens,
        viagens=sorted(
            all_trips,
            key=lambda trip: (
                trip.inicio_viagem or datetime.max,
                trip.nome_programacao,
                trip.numero_viagem,
            ),
        ),
        etapas=sorted(
            all_stages,
            key=lambda etapa: (etapa.inicio, etapa.nome_programacao, etapa.viagem),
        ),
        resumo=summary,
        bt_counts=bt_counts,
        bt_group_labels=bt_group_labels,
        waits_by_resource=waits_by_resource,
        gargalo_principal=gargalo,
        gargalo_por_espera=gargalo_por_espera,
        recurso_mais_ocupado=recurso_mais_ocupado,
        prazo_atendido=prazo_atendido,
        prazo_por_cenario=prazo_por_cenario,
        termino_ultima_descarga=termino_ultima_descarga,
        termino_ultima_viagem=termino_ultima_viagem,
        premissas=_generate_premissas(
            concretagens,
            bt_counts,
            bt_group_labels,
            sequencing.enabled,
            data_base,
        ),
        data_base=data_base,
        warnings=warnings,
        automatico=automatico,
        violacao_total_min=violacao_total,
        sequenciamento_prioridade_ativo=sequencing.enabled,
        recomendacoes_ajuste=[],
        atende_intervalo_descargas=atende_intervalo_descargas,
        intervalos_descarga=intervalos_descarga,
    )
    if include_recommendations:
        continuidade_bt_sugerida = _suggest_bt_counts_for_continuity(
            concretagens,
            bt_counts,
            sequenciar_por_prioridade,
            data_base,
        )
        for resumo in result.resumo:
            sugerida = continuidade_bt_sugerida.get(
                next(
                    concretagem.grupo_bt
                    for concretagem in concretagens
                    if concretagem.id == resumo["id"]
                )
            )
            resumo["bts_sugeridas_continuidade"] = sugerida

        result.recomendacoes_ajuste = _build_recommendations(
            concretagens,
            bt_counts,
            bt_group_labels,
            continuidade_bt_sugerida,
            gargalo,
            prazo_atendido,
            atende_intervalo_descargas,
            intervalos_descarga,
            violacao_total,
            automatico,
        )
    result.dataframe_detalhado = _create_detalhamento_dataframe(result)
    return result


def simular_ciclo_bt(
    concretagens: Iterable[Concretagem],
    base_date: date,
    sequenciar_por_prioridade: bool = False,
) -> ResultadoCalculo:
    concretagens = list(concretagens)
    bt_counts, _, warnings = _resolve_fixed_bt_counts(concretagens)
    return _simulate_with_bt_counts(
        concretagens,
        bt_counts,
        base_date=base_date,
        automatico=False,
        sequenciar_por_prioridade=sequenciar_por_prioridade,
        extra_warnings=warnings,
    )


def _iter_compositions(total: int, groups: int) -> Iterable[tuple[int, ...]]:
    if groups == 1:
        yield (total,)
        return
    for first in range(1, total - groups + 2):
        for tail in _iter_compositions(total - first, groups - 1):
            yield (first,) + tail


def calcular_dimensionamento_minimo(
    concretagens: Iterable[Concretagem],
    base_date: date,
    max_total_bts: int = 20,
    sequenciar_por_prioridade: bool = False,
) -> ResultadoCalculo:
    concretagens = list(concretagens)
    validar_concretagens(concretagens)
    group_keys, labels, _ = _group_metadata(concretagens)

    if max_total_bts < len(group_keys):
        raise ValueError(
            "O limite máximo de BTs para o dimensionamento automático é menor que o número de grupos de frota."
        )

    best_bt_counts: dict[str, int] | None = None
    best_score: tuple[float, int, float, int] | None = None
    cached_results: dict[tuple[tuple[str, int], ...], ResultadoCalculo] = {}

    for total_bt in range(len(group_keys), max_total_bts + 1):
        for composition in _iter_compositions(total_bt, len(group_keys)):
            bt_counts = dict(zip(group_keys, composition, strict=True))
            cache_key = tuple(sorted(bt_counts.items()))
            result = cached_results.get(cache_key)
            if result is None:
                result = _simulate_with_bt_counts(
                    concretagens,
                    bt_counts,
                    base_date=base_date,
                    automatico=True,
                    sequenciar_por_prioridade=sequenciar_por_prioridade,
                    include_recommendations=False,
                )
                cached_results[cache_key] = result

            continuity_violations, continuity_excess = _continuity_violation_metrics(result)
            score = (
                result.violacao_total_min,
                continuity_violations,
                continuity_excess,
                total_bt,
            )
            if best_score is None or score < best_score:
                best_bt_counts = dict(bt_counts)
                best_score = score

            if result.prazo_atendido and result.atende_intervalo_descargas:
                final_result = _simulate_with_bt_counts(
                    concretagens,
                    bt_counts,
                    base_date=base_date,
                    automatico=True,
                    sequenciar_por_prioridade=sequenciar_por_prioridade,
                    include_recommendations=True,
                )
                final_result.dimensionamento_encontrado = True
                return final_result

    if best_bt_counts is None:
        raise RuntimeError("Não foi possível concluir o dimensionamento automático.")

    best_result = _simulate_with_bt_counts(
        concretagens,
        best_bt_counts,
        base_date=base_date,
        automatico=True,
        sequenciar_por_prioridade=sequenciar_por_prioridade,
        include_recommendations=True,
    )
    best_result.dimensionamento_encontrado = False
    best_result.warnings.append(
        "Não foi possível atender simultaneamente prazo e continuidade operacional até o limite máximo de BTs testado. "
        f"Melhor alternativa exibida com até {max_total_bts} BT(s) distribuídas entre {len(labels)} grupo(s)."
    )
    if best_result.recomendacoes_ajuste:
        limite_msg = (
            f"Aumentar o limite máximo do dimensionamento automático acima de {max_total_bts} BT(s) "
            "pode ser necessário para encontrar uma solução que atenda prazo e continuidade."
        )
        if limite_msg not in best_result.recomendacoes_ajuste:
            best_result.recomendacoes_ajuste.append(limite_msg)
    return best_result


def gerar_resumo(resultado: ResultadoCalculo) -> list[dict[str, object]]:
    return resultado.resumo
