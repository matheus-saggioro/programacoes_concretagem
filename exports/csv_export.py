from __future__ import annotations

from io import BytesIO

import pandas as pd


def exportar_detalhamento_csv(dataframe: pd.DataFrame) -> bytes:
    return dataframe.to_csv(index=False).encode("utf-8-sig")


def exportar_programacao_cenario_csv(record: dict) -> bytes:
    payloads = record.get("payloads") or []
    rows: list[dict[str, object]] = []

    for ordem, payload in enumerate(payloads, start=1):
        ciclo = payload.get("ciclo", {})
        restricoes = payload.get("restricoes", {})
        rows.append(
            {
                "cenario_id": record.get("id", ""),
                "cenario_nome": record.get("name", ""),
                "cenario_label": record.get("label", ""),
                "cenario_data": record.get("date", ""),
                "cenario_turno": record.get("turno", ""),
                "cenario_calc_mode": record.get("calc_mode", ""),
                "cenario_max_total_bts": record.get("max_total_bts", ""),
                "cenario_sequenciar_por_prioridade": record.get(
                    "sequenciar_por_prioridade", False
                ),
                "programacao_ordem": ordem,
                "programacao_id": payload.get("id", ""),
                "programacao_nome": payload.get("nome_programacao", ""),
                "programacao_local": payload.get("local", ""),
                "programacao_elemento_frente": payload.get("elemento_frente", ""),
                "programacao_usina": payload.get("usina", ""),
                "programacao_tipo_cimento": payload.get("tipo_cimento", ""),
                "programacao_observacoes": payload.get("observacoes", ""),
                "programacao_volume_total_m3": payload.get("volume_total_m3", ""),
                "programacao_capacidade_bt_m3": payload.get("capacidade_bt_m3", ""),
                "programacao_numero_bts_fixo": payload.get("numero_bts_fixo", ""),
                "programacao_inicio_primeira_mistura": payload.get("inicio_primeira_mistura", ""),
                "programacao_prioridade": payload.get("prioridade", 0),
                "programacao_prazo_limite_descarga": payload.get("prazo_limite_descarga", ""),
                "ciclo_mistura_min": ciclo.get("mistura_min", ""),
                "ciclo_dosagem_min": ciclo.get("dosagem_min", ""),
                "ciclo_ida_min": ciclo.get("ida_min", ""),
                "ciclo_slump_min": ciclo.get("slump_min", ""),
                "ciclo_descarga_min": ciclo.get("descarga_min", ""),
                "ciclo_lavagem_min": ciclo.get("lavagem_min", ""),
                "ciclo_volta_min": ciclo.get("volta_min", ""),
                "restricao_com_bomba": restricoes.get("com_bomba", False),
                "restricao_max_bts_frente": restricoes.get("max_bts_frente", ""),
                "restricao_max_bts_mistura": restricoes.get("max_bts_mistura", ""),
                "restricao_max_bts_dosagem": restricoes.get("max_bts_dosagem", ""),
                "restricao_existe_intervalo_entre_misturas": restricoes.get(
                    "existe_intervalo_entre_misturas", False
                ),
                "restricao_intervalo_entre_misturas_min": restricoes.get(
                    "intervalo_entre_misturas_min", ""
                ),
                "restricao_existe_intervalo_maximo_entre_descargas": restricoes.get(
                    "existe_intervalo_maximo_entre_descargas", False
                ),
                "restricao_intervalo_maximo_entre_descargas_min": restricoes.get(
                    "intervalo_maximo_entre_descargas_min", ""
                ),
                "restricao_ultima_viagem_parcial_proporcional": restricoes.get(
                    "ultima_viagem_parcial_proporcional", False
                ),
                "restricao_permitir_primeira_viagem_customizada": restricoes.get(
                    "permitir_primeira_viagem_customizada", False
                ),
                "restricao_volume_primeira_viagem_m3": restricoes.get(
                    "volume_primeira_viagem_m3", ""
                ),
                "restricao_alocacao_bts": restricoes.get("alocacao_bts", ""),
            }
        )

    dataframe = pd.DataFrame(rows)
    return dataframe.to_csv(index=False).encode("utf-8-sig")


def importar_programacao_cenario_csv(content: bytes) -> dict:
    dataframe = pd.read_csv(BytesIO(content), keep_default_na=False)
    if dataframe.empty:
        raise ValueError("O arquivo CSV importado está vazio.")

    required_columns = {
        "cenario_nome",
        "cenario_data",
        "cenario_turno",
        "cenario_calc_mode",
        "cenario_max_total_bts",
        "cenario_sequenciar_por_prioridade",
        "programacao_ordem",
        "programacao_id",
        "programacao_nome",
        "programacao_local",
        "programacao_elemento_frente",
        "programacao_usina",
        "programacao_tipo_cimento",
        "programacao_observacoes",
        "programacao_volume_total_m3",
        "programacao_capacidade_bt_m3",
        "programacao_numero_bts_fixo",
        "programacao_inicio_primeira_mistura",
        "programacao_prioridade",
        "programacao_prazo_limite_descarga",
        "ciclo_mistura_min",
        "ciclo_dosagem_min",
        "ciclo_ida_min",
        "ciclo_slump_min",
        "ciclo_descarga_min",
        "ciclo_lavagem_min",
        "ciclo_volta_min",
        "restricao_com_bomba",
        "restricao_max_bts_frente",
        "restricao_max_bts_mistura",
        "restricao_max_bts_dosagem",
        "restricao_existe_intervalo_entre_misturas",
        "restricao_intervalo_entre_misturas_min",
        "restricao_ultima_viagem_parcial_proporcional",
        "restricao_permitir_primeira_viagem_customizada",
        "restricao_volume_primeira_viagem_m3",
        "restricao_alocacao_bts",
    }
    missing = sorted(required_columns - set(dataframe.columns))
    if missing:
        raise ValueError(
            "O CSV não corresponde ao formato exportado pelo sistema. "
            f"Colunas ausentes: {', '.join(missing)}."
        )

    def as_bool(value: object) -> bool:
        return str(value).strip().lower() in {"1", "true", "sim", "yes"}

    def as_optional_text(value: object) -> str | None:
        text = str(value).strip()
        return text or None

    def as_optional_number(value: object) -> float | None:
        text = str(value).strip()
        if not text:
            return None
        return float(text)

    ordered_rows = dataframe.sort_values("programacao_ordem", kind="stable")
    first = ordered_rows.iloc[0]
    payloads: list[dict] = []
    for row in ordered_rows.to_dict(orient="records"):
        payloads.append(
            {
                "id": str(row["programacao_id"]).strip(),
                "nome_programacao": str(row["programacao_nome"]).strip(),
                "local": str(row["programacao_local"]).strip(),
                "elemento_frente": str(row["programacao_elemento_frente"]).strip(),
                "usina": str(row["programacao_usina"]).strip(),
                "tipo_cimento": str(row["programacao_tipo_cimento"]).strip(),
                "observacoes": str(row["programacao_observacoes"]).strip(),
                "volume_total_m3": float(row["programacao_volume_total_m3"]),
                "capacidade_bt_m3": float(row["programacao_capacidade_bt_m3"]),
                "numero_bts_fixo": int(float(row["programacao_numero_bts_fixo"]))
                if str(row["programacao_numero_bts_fixo"]).strip()
                else 0,
                "inicio_primeira_mistura": str(row["programacao_inicio_primeira_mistura"]).strip(),
                "prioridade": int(float(row["programacao_prioridade"])),
                "prazo_limite_descarga": as_optional_text(row["programacao_prazo_limite_descarga"]),
                "ciclo": {
                    "mistura_min": float(row["ciclo_mistura_min"]),
                    "dosagem_min": float(row["ciclo_dosagem_min"]),
                    "ida_min": float(row["ciclo_ida_min"]),
                    "slump_min": float(row["ciclo_slump_min"]),
                    "descarga_min": float(row["ciclo_descarga_min"]),
                    "lavagem_min": float(row["ciclo_lavagem_min"]),
                    "volta_min": float(row["ciclo_volta_min"]),
                },
                "restricoes": {
                    "com_bomba": as_bool(row["restricao_com_bomba"]),
                    "max_bts_frente": int(float(row["restricao_max_bts_frente"])),
                    "max_bts_mistura": int(float(row["restricao_max_bts_mistura"])),
                    "max_bts_dosagem": int(float(row["restricao_max_bts_dosagem"])),
                    "existe_intervalo_entre_misturas": as_bool(
                        row["restricao_existe_intervalo_entre_misturas"]
                    ),
                    "intervalo_entre_misturas_min": float(
                        row["restricao_intervalo_entre_misturas_min"]
                    ),
                    "existe_intervalo_maximo_entre_descargas": as_bool(
                        row.get("restricao_existe_intervalo_maximo_entre_descargas", False)
                    ),
                    "intervalo_maximo_entre_descargas_min": float(
                        row.get("restricao_intervalo_maximo_entre_descargas_min", 0.0) or 0.0
                    ),
                    "ultima_viagem_parcial_proporcional": as_bool(
                        row["restricao_ultima_viagem_parcial_proporcional"]
                    ),
                    "permitir_primeira_viagem_customizada": as_bool(
                        row["restricao_permitir_primeira_viagem_customizada"]
                    ),
                    "volume_primeira_viagem_m3": as_optional_number(
                        row["restricao_volume_primeira_viagem_m3"]
                    ),
                    "alocacao_bts": str(row["restricao_alocacao_bts"]).strip(),
                },
            }
        )

    return {
        "id": str(first.get("cenario_id", "")).strip(),
        "name": str(first["cenario_nome"]).strip(),
        "label": str(first.get("cenario_label", "")).strip(),
        "date": str(first["cenario_data"]).strip(),
        "turno": str(first["cenario_turno"]).strip(),
        "calc_mode": str(first["cenario_calc_mode"]).strip() or "fixo",
        "max_total_bts": int(float(first["cenario_max_total_bts"])),
        "sequenciar_por_prioridade": as_bool(first["cenario_sequenciar_por_prioridade"]),
        "payloads": payloads,
    }
