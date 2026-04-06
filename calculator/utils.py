from __future__ import annotations

from datetime import date, datetime, time, timedelta


TIME_FORMAT = "%H:%M"


def minutes_to_timedelta(minutes: float) -> timedelta:
    return timedelta(minutes=float(minutes))


def combine_date_and_time(base_date: date, clock: time) -> datetime:
    return datetime.combine(base_date, clock.replace(second=0, microsecond=0))


def parse_time_value(value: object | None) -> time | None:
    if value in (None, "", "null"):
        return None
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if isinstance(value, datetime):
        return value.time().replace(second=0, microsecond=0)
    if isinstance(value, str):
        return datetime.strptime(value.strip(), TIME_FORMAT).time()
    raise ValueError(f"Valor de horário inválido: {value!r}")


def resolve_deadline_datetime(
    base_date: date,
    start_clock: time,
    deadline_clock: time | None,
) -> datetime | None:
    if deadline_clock is None:
        return None
    start_dt = combine_date_and_time(base_date, start_clock)
    deadline_dt = combine_date_and_time(base_date, deadline_clock)
    if deadline_dt < start_dt:
        deadline_dt += timedelta(days=1)
    return deadline_dt


def format_clock(dt: datetime | None, reference_date: date | None = None) -> str:
    if dt is None:
        return "-"
    reference = reference_date or dt.date()
    label = dt.strftime(TIME_FORMAT)
    day_offset = (dt.date() - reference).days
    if day_offset > 0:
        label = f"{label} (+{day_offset}d)"
    return label


def round_minutes(value: float, digits: int = 1) -> float | int:
    rounded = round(float(value), digits)
    if float(rounded).is_integer():
        return int(rounded)
    return rounded


def minutes_between(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 60.0)


def safe_identifier(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned.strip("-")
    return cleaned or "item"


def front_resource_key(local: str, elemento: str, com_bomba: bool) -> str:
    return f"{safe_identifier(local)}::{safe_identifier(elemento)}::{'bomba' if com_bomba else 'frente'}"


def bt_group_key(alocacao_bts: str, usina: str, scenario_id: str) -> str:
    if alocacao_bts == "compartilhadas":
        return f"shared::{safe_identifier(usina)}"
    return f"dedicated::{safe_identifier(scenario_id)}"


def bt_group_label(alocacao_bts: str, usina: str, nome_programacao: str) -> str:
    if alocacao_bts == "compartilhadas":
        return f"BTs compartilhadas - {usina}"
    return f"BTs dedicadas - {nome_programacao}"
