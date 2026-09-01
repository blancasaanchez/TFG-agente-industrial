from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import yaml


def _load_display_specs(schema_path: str | Path) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Lee Schema.md y extrae display_template, plural_name y distinct_labels."""
    text = Path(schema_path).read_text(encoding="utf-8")
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
    templates: dict[str, str] = {}
    plural_labels: dict[str, str] = {}
    distinct_labels: dict[str, str] = {}

    for raw in blocks:
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            continue

        if data.get("type") == "global_config":
            raw_distinct = data.get("distinct_labels", {})
            if isinstance(raw_distinct, dict):
                distinct_labels.update({str(k): str(v) for k, v in raw_distinct.items()})
            continue

        if "entity" not in data:
            continue
        entity = data["entity"]
        if "display_template" in data:
            templates[entity] = data["display_template"]
        if "plural_name" in data:
            plural_labels[entity] = data["plural_name"]

    return templates, plural_labels, distinct_labels


class ResponseBuilder:
    """Formatea resultados de consulta en texto legible para el operario.

    Los templates de visualización viven en Schema.md (campo display_template
    de cada entidad). Este módulo no codifica formato por entidad.
    """

    def __init__(self, schema_path: str | Path = "Schema.md") -> None:
        self._templates, self._plural_labels, self._distinct_labels = _load_display_specs(schema_path)

    @staticmethod
    def _clean(value: Any) -> Any:
        """Quita decimales sobrantes: 60.0 -> 60. No toca 12.5 ni texto."""
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    @staticmethod
    def _header(text: str) -> str:
        """Normaliza una cabecera de listado para que siempre acabe en ':'."""
        text = text.rstrip()
        return text if text.endswith(":") else f"{text}:"

    def build(self, execution_result: dict[str, Any]) -> str:
        intent = execution_result["intent"]
        if intent == "consultar":
            return self._build_read_response(execution_result)
        if intent == "registrar":
            return f"Registro insertado correctamente. Filas afectadas: {execution_result['rowcount']}."
        if intent == "actualizar":
            return f"Registro actualizado correctamente. Filas afectadas: {execution_result['rowcount']}."
        if intent == "eliminar":
            return f"Registro eliminado correctamente. Filas afectadas: {execution_result['rowcount']}."
        return "Operación completada."

    def _build_read_response(self, execution_result: dict[str, Any]) -> str:
        rows = execution_result["rows"]
        entity_type = execution_result["entity_type"]
        select_fields = execution_result["select_fields"]

        if not rows:
            return "No se encontraron resultados con esos criterios."

        if execution_result.get("is_analytic"):
            return self._format_analytic_result(
                entity_type=entity_type,
                rows=rows,
                group_fields=execution_result.get("group_fields", []),
                metric_alias=execution_result.get("metric_alias"),
            )

        header = self._header(execution_result.get("summary_title") or "Resultados")
        items = ["* " + self._format_row(entity_type, row, select_fields) for row in rows]
        return header + "\n\n" + "\n\n".join(items)

    def _format_analytic_result(
        self,
        entity_type: str,
        rows: list[sqlite3.Row],
        group_fields: list[str],
        metric_alias: str | None,
    ) -> str:
        if not rows or not metric_alias:
            return "No se encontraron resultados analíticos."

        # Escalar puro: una sola fila, solo la métrica (ej. COUNT total o COUNT DISTINCT)
        if not group_fields and len(rows) == 1 and list(rows[0].keys()) == [metric_alias]:
            label = self._scalar_metric_label(entity_type, metric_alias)
            return f"Total de {label}: {self._clean(rows[0][metric_alias])}"

        header = self._header(f"Resumen de {self._plural_label(entity_type)}")
        items: list[str] = []
        template = self._templates.get(entity_type)

        for row in rows:
            row_data = {k: (self._clean(row[k]) if row[k] is not None else "—") for k in row.keys()}
            metric_val = row_data.pop(metric_alias, "—")

            if group_fields:
                # Agrupación: mostrar solo los campos de grupo como contexto
                context = " | ".join(f"{f}: {row_data.get(f, '—')}" for f in group_fields)
            elif template:
                # Sin agrupación (ej. derived_metric por fila): usar display_template
                try:
                    context = template.format_map(row_data)
                except KeyError:
                    context = " | ".join(f"{k}: {v}" for k, v in row_data.items())
            else:
                context = " | ".join(f"{k}: {v}" for k, v in row_data.items())

            items.append(f"* {context} -> {metric_alias}: {metric_val}")

        return header + "\n\n" + "\n\n".join(items)

    def _format_row(self, entity_name: str, row: sqlite3.Row, select_fields: list[str]) -> str:
        """Aplica el display_template de la entidad. Fallback a formato genérico."""
        data = {field: (self._clean(row[field]) if row[field] is not None else "—") for field in select_fields}
        template = self._templates.get(entity_name)

        if template:
            try:
                return template.format_map(data)
            except KeyError:
                # El template requiere campos que no están en select_fields: usar genérico
                pass

        return self._generic_row(data, select_fields)

    @staticmethod
    def _generic_row(data: dict[str, Any], select_fields: list[str]) -> str:
        return " | ".join(f"{field}: {data.get(field, '—')}" for field in select_fields)

    def _plural_label(self, entity_type: str) -> str:
        return self._plural_labels.get(entity_type, entity_type)

    def _scalar_metric_label(self, entity_type: str, metric_alias: str) -> str:
        """Etiqueta legible para un total escalar (COUNT o COUNT DISTINCT).

        Para count_distinct, metric_alias tiene forma "distinct_<campo>"; buscamos
        una etiqueta específica en distinct_labels (Schema.md). Si no existe,
        recurrimos al plural genérico de la entidad.
        """
        if metric_alias.startswith("distinct_"):
            field = metric_alias[len("distinct_"):]
            label = self._distinct_labels.get(f"{entity_type}.{field}")
            if label:
                return label
        return self._plural_label(entity_type)