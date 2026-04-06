from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from calculator.utils import (
    bt_group_key,
    parse_time_value,
    resolve_deadline_datetime,
    combine_date_and_time,
)


@dataclass(slots=True)
class Ciclo:
    mistura_min: float
    dosagem_min: float
    ida_min: float
    slump_min: float
    descarga_min: float
    lavagem_min: float
    volta_min: float

    def as_rows(self) -> list[tuple[str, float]]:
        return [
            ("Mistura", self.mistura_min),
            ("Dosagem", self.dosagem_min),
            ("Ida", self.ida_min),
            ("Slump", self.slump_min),
            ("Descarga", self.descarga_min),
            ("Lavagem", self.lavagem_min),
            ("Volta", self.volta_min),
        ]


@dataclass(slots=True)
class Restricoes:
    com_bomba: bool
    max_bts_frente: int
    max_bts_mistura: int
    max_bts_dosagem: int
    existe_intervalo_entre_misturas: bool
    intervalo_entre_misturas_min: float
    existe_intervalo_maximo_entre_descargas: bool
    intervalo_maximo_entre_descargas_min: float
    ultima_viagem_parcial_proporcional: bool
    permitir_primeira_viagem_customizada: bool
    volume_primeira_viagem_m3: float | None
    alocacao_bts: str

    @property
    def intervalo_efetivo_min(self) -> float:
        if not self.existe_intervalo_entre_misturas:
            return 0.0
        return float(self.intervalo_entre_misturas_min)


@dataclass(slots=True)
class Concretagem:
    id: str
    nome_programacao: str
    local: str
    elemento_frente: str
    usina: str
    tipo_cimento: str
    observacoes: str
    volume_total_m3: float
    capacidade_bt_m3: float
    numero_bts_fixo: int | None
    inicio_primeira_mistura: time
    prazo_limite_descarga: time | None
    ciclo: Ciclo
    restricoes: Restricoes
    prioridade: int = 0
    ordem: int = 0

    def inicio_datetime(self, base_date: date) -> datetime:
        return combine_date_and_time(base_date, self.inicio_primeira_mistura)

    def prazo_datetime(self, base_date: date) -> datetime | None:
        return resolve_deadline_datetime(
            base_date,
            self.inicio_primeira_mistura,
            self.prazo_limite_descarga,
        )

    @property
    def grupo_bt(self) -> str:
        return bt_group_key(self.restricoes.alocacao_bts, self.usina, self.id)

    @classmethod
    def from_dict(cls, data: dict[str, Any], ordem: int = 0) -> "Concretagem":
        ciclo_data = data.get("ciclo", {})
        restricoes_data = data.get("restricoes", {})
        numero_bts = data.get("numero_bts_fixo")
        volume_primeira = restricoes_data.get("volume_primeira_viagem_m3")
        return cls(
            id=data.get("id") or f"concretagem-{ordem + 1}",
            nome_programacao=data.get("nome_programacao", f"Programação {ordem + 1}"),
            local=data.get("local", ""),
            elemento_frente=data.get("elemento_frente", ""),
            usina=data.get("usina", ""),
            tipo_cimento=data.get("tipo_cimento", ""),
            observacoes=data.get("observacoes", ""),
            volume_total_m3=float(data.get("volume_total_m3", 0.0)),
            capacidade_bt_m3=float(data.get("capacidade_bt_m3", 0.0)),
            numero_bts_fixo=int(numero_bts) if numero_bts not in (None, "", 0) else None,
            inicio_primeira_mistura=parse_time_value(data.get("inicio_primeira_mistura")) or time(7, 0),
            prioridade=max(0, int(data.get("prioridade", 0) or 0)),
            prazo_limite_descarga=parse_time_value(data.get("prazo_limite_descarga")),
            ciclo=Ciclo(
                mistura_min=float(ciclo_data.get("mistura_min", 0.0)),
                dosagem_min=float(ciclo_data.get("dosagem_min", 0.0)),
                ida_min=float(ciclo_data.get("ida_min", 0.0)),
                slump_min=float(ciclo_data.get("slump_min", 0.0)),
                descarga_min=float(ciclo_data.get("descarga_min", 0.0)),
                lavagem_min=float(ciclo_data.get("lavagem_min", 0.0)),
                volta_min=float(ciclo_data.get("volta_min", 0.0)),
            ),
            restricoes=Restricoes(
                com_bomba=bool(restricoes_data.get("com_bomba", False)),
                max_bts_frente=int(restricoes_data.get("max_bts_frente", 1)),
                max_bts_mistura=int(restricoes_data.get("max_bts_mistura", 1)),
                max_bts_dosagem=int(restricoes_data.get("max_bts_dosagem", 1)),
                existe_intervalo_entre_misturas=bool(
                    restricoes_data.get("existe_intervalo_entre_misturas", False)
                ),
                intervalo_entre_misturas_min=float(
                    restricoes_data.get("intervalo_entre_misturas_min", 0.0)
                ),
                existe_intervalo_maximo_entre_descargas=bool(
                    restricoes_data.get("existe_intervalo_maximo_entre_descargas", False)
                ),
                intervalo_maximo_entre_descargas_min=float(
                    restricoes_data.get("intervalo_maximo_entre_descargas_min", 0.0)
                ),
                ultima_viagem_parcial_proporcional=bool(
                    restricoes_data.get("ultima_viagem_parcial_proporcional", True)
                ),
                permitir_primeira_viagem_customizada=bool(
                    restricoes_data.get("permitir_primeira_viagem_customizada", False)
                ),
                volume_primeira_viagem_m3=(
                    float(volume_primeira) if volume_primeira not in (None, "", 0) else None
                ),
                alocacao_bts=restricoes_data.get("alocacao_bts", "dedicadas"),
            ),
            ordem=ordem,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nome_programacao": self.nome_programacao,
            "local": self.local,
            "elemento_frente": self.elemento_frente,
            "usina": self.usina,
            "tipo_cimento": self.tipo_cimento,
            "observacoes": self.observacoes,
            "volume_total_m3": self.volume_total_m3,
            "capacidade_bt_m3": self.capacidade_bt_m3,
            "numero_bts_fixo": self.numero_bts_fixo,
            "inicio_primeira_mistura": self.inicio_primeira_mistura.strftime("%H:%M"),
            "prioridade": self.prioridade,
            "prazo_limite_descarga": (
                self.prazo_limite_descarga.strftime("%H:%M")
                if self.prazo_limite_descarga
                else None
            ),
            "ciclo": {
                "mistura_min": self.ciclo.mistura_min,
                "dosagem_min": self.ciclo.dosagem_min,
                "ida_min": self.ciclo.ida_min,
                "slump_min": self.ciclo.slump_min,
                "descarga_min": self.ciclo.descarga_min,
                "lavagem_min": self.ciclo.lavagem_min,
                "volta_min": self.ciclo.volta_min,
            },
            "restricoes": {
                "com_bomba": self.restricoes.com_bomba,
                "max_bts_frente": self.restricoes.max_bts_frente,
                "max_bts_mistura": self.restricoes.max_bts_mistura,
                "max_bts_dosagem": self.restricoes.max_bts_dosagem,
                "existe_intervalo_entre_misturas": self.restricoes.existe_intervalo_entre_misturas,
                "intervalo_entre_misturas_min": self.restricoes.intervalo_entre_misturas_min,
                "existe_intervalo_maximo_entre_descargas": (
                    self.restricoes.existe_intervalo_maximo_entre_descargas
                ),
                "intervalo_maximo_entre_descargas_min": (
                    self.restricoes.intervalo_maximo_entre_descargas_min
                ),
                "ultima_viagem_parcial_proporcional": self.restricoes.ultima_viagem_parcial_proporcional,
                "permitir_primeira_viagem_customizada": self.restricoes.permitir_primeira_viagem_customizada,
                "volume_primeira_viagem_m3": self.restricoes.volume_primeira_viagem_m3,
                "alocacao_bts": self.restricoes.alocacao_bts,
            },
        }


@dataclass(slots=True)
class EtapaViagem:
    concretagem_id: str
    nome_programacao: str
    bt: str
    viagem: int
    volume_m3: float
    etapa: str
    inicio: datetime
    fim: datetime
    duracao_min: float
    observacao: str = ""


@dataclass(slots=True)
class Viagem:
    concretagem_id: str
    nome_programacao: str
    numero_viagem: int
    volume_m3: float
    grupo_bt: str
    bt: str = ""
    etapas: list[EtapaViagem] = field(default_factory=list)
    inicio_viagem: datetime | None = None
    fim_descarga: datetime | None = None
    fim_viagem: datetime | None = None
    espera_mistura_min: float = 0.0
    espera_dosagem_min: float = 0.0
    espera_bomba_min: float = 0.0
    espera_frente_min: float = 0.0


@dataclass
class ResultadoCalculo:
    concretagens: list[Concretagem]
    viagens: list[Viagem]
    etapas: list[EtapaViagem]
    resumo: list[dict[str, Any]]
    bt_counts: dict[str, int]
    bt_group_labels: dict[str, str]
    waits_by_resource: dict[str, float]
    gargalo_principal: str
    gargalo_por_espera: str
    recurso_mais_ocupado: str
    prazo_atendido: bool
    prazo_por_cenario: dict[str, bool]
    termino_ultima_descarga: datetime | None
    termino_ultima_viagem: datetime | None
    premissas: list[str]
    data_base: date
    warnings: list[str] = field(default_factory=list)
    automatico: bool = False
    dimensionamento_encontrado: bool = True
    violacao_total_min: float = 0.0
    dataframe_detalhado: Any = None
    sequenciamento_prioridade_ativo: bool = False
    recomendacoes_ajuste: list[str] = field(default_factory=list)
    atende_intervalo_descargas: bool = True
    intervalos_descarga: list[dict[str, Any]] = field(default_factory=list)
