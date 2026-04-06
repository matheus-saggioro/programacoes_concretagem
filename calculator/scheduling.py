from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from calculator.utils import minutes_to_timedelta


@dataclass(slots=True)
class LaneAllocation:
    start: datetime
    end: datetime
    lane_index: int


@dataclass
class LaneResource:
    name: str
    capacity: int
    min_gap_minutes: float = 0.0
    lane_available_at: list[datetime] = field(default_factory=list)
    allocations: list[tuple[datetime, datetime, int]] = field(default_factory=list)
    last_start: datetime | None = None

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError(f"Capacidade inválida para o recurso {self.name}.")
        if not self.lane_available_at:
            self.lane_available_at = [datetime.min for _ in range(self.capacity)]

    def peek(self, earliest_start: datetime, duration_min: float) -> LaneAllocation:
        gap_ready = earliest_start
        if self.min_gap_minutes > 0 and self.last_start is not None:
            gap_ready = max(gap_ready, self.last_start + minutes_to_timedelta(self.min_gap_minutes))

        best_lane = 0
        best_start = max(gap_ready, self.lane_available_at[0])
        for lane_index, available_at in enumerate(self.lane_available_at):
            candidate_start = max(gap_ready, available_at)
            if candidate_start < best_start or (
                candidate_start == best_start and lane_index < best_lane
            ):
                best_lane = lane_index
                best_start = candidate_start

        return LaneAllocation(
            start=best_start,
            end=best_start + minutes_to_timedelta(duration_min),
            lane_index=best_lane,
        )

    def reserve(self, earliest_start: datetime, duration_min: float) -> LaneAllocation:
        allocation = self.peek(earliest_start, duration_min)
        self.lane_available_at[allocation.lane_index] = allocation.end
        self.allocations.append((allocation.start, allocation.end, allocation.lane_index))
        self.last_start = allocation.start
        return allocation


@dataclass(slots=True)
class TruckState:
    truck_id: str
    available_at: datetime


@dataclass
class TruckFleet:
    group_key: str
    label: str
    trucks: list[TruckState]

    def peek_next_available(self) -> TruckState:
        return min(self.trucks, key=lambda truck: (truck.available_at, truck.truck_id))

    def reserve_next_available(self) -> TruckState:
        return self.peek_next_available()


def simular_descarga_com_fila(
    resource: LaneResource,
    earliest_start: datetime,
    duration_min: float,
) -> LaneAllocation:
    return resource.reserve(earliest_start, duration_min)
