from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .schemas import FKValidation, Filter, ParsedRequest, QueryPlan


@dataclass(frozen=True)
class FieldSpec:
    expression: str
    kind: str  # text | number | date
    write_expression: str | None = None
    fk_lookup: str | None = None      # write_values FK: "tabla.campo"
    write_via_fk: str | None = None   # filtros de escritura: "fk_col->tabla.campo"


@dataclass
class EntitySpec:
    name: str
    plural_name: str
    summary_title: str
    from_sql: str
    identifier_field: str | None
    display_order: str
    writable_table: str | None
    writable_fields: set[str]
    default_select: list[str]
    default_aggregation_field: str | None
    fields: dict[str, FieldSpec]


def _is_numeric(value: Any) -> bool:
    try:
        float(str(value))
        return True
    except (ValueError, TypeError):
        return False


def normalize_text(value: Any) -> str:
    """Normaliza texto para comparaciones: minúsculas, sin acentos, sin
    guiones ni espacios internos.

    Los identificadores con guión (matrículas de máquina como "Torno T-01",
    referencias de orden como "OP-2024-001") llegan transcritos de voz con
    formato inconsistente según el dispositivo: "T-01", "T01" y "T 0 1" son
    el mismo identificador para el operario, pero motores de transcripción
    distintos los escriben de forma distinta. Quitar guiones y espacios
    aquí hace que las tres formas normalicen al mismo valor, en vez de
    depender de que el LLM adivine dónde va el guión.
    """
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[\s\-]+", "", text)


def _load_specs_from_schema(
    schema_path: str | Path,
) -> tuple[dict[str, EntitySpec], dict[str, str]]:
    text = Path(schema_path).read_text(encoding="utf-8")
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
    specs: dict[str, EntitySpec] = {}
    aliases: dict[str, str] = {}

    for raw in blocks:
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            continue

        if data.get("type") == "global_config":
            raw_aliases = data.get("aliases", {})
            if isinstance(raw_aliases, dict):
                aliases.update({normalize_text(k): str(v) for k, v in raw_aliases.items()})
            continue

        if "entity" not in data:
            continue

        raw_fields = data.get("fields", {})
        fields = {
            name: FieldSpec(
                expression=fdef["expr"],
                kind=fdef.get("kind", "text"),
                write_expression=fdef.get("write_expr"),
                fk_lookup=fdef.get("fk_lookup"),
                write_via_fk=fdef.get("write_via_fk"),
            )
            for name, fdef in raw_fields.items()
        }

        specs[data["entity"]] = EntitySpec(
            name=data["entity"],
            plural_name=data.get("plural_name", data["entity"]),
            summary_title=data.get("summary_title", data["entity"]),
            from_sql=data["from_sql"].strip(),
            identifier_field=data.get("identifier_field") or None,
            display_order=data.get("display_order", "1"),
            writable_table=data.get("writable_table") or None,
            writable_fields=set(data.get("writable_fields", [])),
            default_select=list(data.get("default_select", [])),
            default_aggregation_field=data.get("default_aggregation_field"),
            fields=fields,
        )

    return specs, aliases


class QueryBuilder:
    """Traduce ParsedRequest → QueryPlan (SQL + params).

    Objetivo: mantener la capa SQL técnica, reutilizable y segura.
    Toda la metadata sale de Schema.md; aquí solo se valida y se traduce.
    """

    def __init__(
        self,
        schema_path: str | Path = "Schema.md",
        allow_deletes: bool = False,
    ) -> None:
        self.allow_deletes = allow_deletes
        self.specs, self._aliases = _load_specs_from_schema(schema_path)

    def build(self, req: ParsedRequest) -> QueryPlan:
        entity_type = req.entity_type or "desconocido"
        spec = self.specs.get(entity_type)
        if not spec:
            raise ValueError(
                f"Entidad '{entity_type}' no encontrada en Schema.md. "
                f"Entidades disponibles: {list(self.specs.keys())}"
            )
        if req.intent == "consultar":
            return self._build_select(req, spec)
        if req.intent == "registrar":
            return self._build_insert(req, spec)
        if req.intent == "actualizar":
            return self._build_update(req, spec)
        if req.intent == "eliminar":
            return self._build_delete(req, spec)
        raise ValueError(f"Intent '{req.intent}' no soportado por QueryBuilder.")

    def _canonical_field(self, raw: str) -> str:
        key = normalize_text(raw)
        return self._aliases.get(key, raw.strip())

    def _normalize_filters(self, req: ParsedRequest, spec: EntitySpec) -> list[Filter]:
        result: list[Filter] = []
        for item in req.filters:
            logical = self._canonical_field(item.field)
            if logical not in spec.fields:
                raise ValueError(
                    f"Campo '{item.field}' (→ '{logical}') no válido para "
                    f"'{spec.name}'. Válidos: {sorted(spec.fields)}"
                )
            result.append(Filter(field=logical, operator=item.operator, value=item.value))

        if req.entity_value and spec.identifier_field:
            result.append(Filter(field=spec.identifier_field, operator="=", value=req.entity_value))
        return result

    @staticmethod
    def _resolve_fk_reference(fk_ref: str, value: Any) -> tuple[str, list[Any], FKValidation | None]:
        """Único helper de resolución FK textual → id.

        Sirve para INSERT, UPDATE y filtros de escritura vía write_via_fk.
        Devuelve:
        - expresión SQL que resuelve el id (`?` o subquery)
        - parámetros para esa expresión
        - validación previa opcional, para dar errores legibles cuando la referencia no existe
        """
        fk_table, fk_field = fk_ref.split(".", 1)

        if _is_numeric(value):
            return "?", [float(value)], None

        text_value = str(value)
        expr = f"(SELECT id FROM {fk_table} WHERE NORMALIZAR({fk_field}) = NORMALIZAR(?))"
        validation = FKValidation(
            label=f"{fk_table} con {fk_field}='{text_value}'",
            check_sql=f"SELECT 1 FROM {fk_table} WHERE NORMALIZAR({fk_field}) = NORMALIZAR(?)",
            check_params=[text_value],
        )
        return expr, [text_value], validation

    def _build_where(
        self,
        spec: EntitySpec,
        filters: list[Filter],
        *,
        for_write: bool = False,
    ) -> tuple[str, list[Any], list[FKValidation]]:
        if not filters:
            return "", [], []

        clauses: list[str] = []
        params: list[Any] = []
        validations: list[FKValidation] = []
        unresolvable: list[str] = []

        for item in filters:
            fspec = spec.fields[item.field]

            if not for_write:
                expr = fspec.expression
            else:
                write_expr = fspec.write_expression or fspec.expression
                if "." not in write_expr:
                    expr = write_expr
                elif fspec.write_via_fk:
                    fk_col, fk_ref = fspec.write_via_fk.split("->", 1)
                    fk_table, fk_field = fk_ref.split(".", 1)

                    if item.value is None:
                        op = "IS NOT NULL" if item.operator == "!=" else "IS NULL"
                        clauses.append(f"{fk_col} {op}")
                        continue

                    if item.operator == "contains":
                        clauses.append(
                            f"{fk_col} IN (SELECT id FROM {fk_table} WHERE NORMALIZAR({fk_field}) LIKE ?)"
                        )
                        params.append(f"%{normalize_text(item.value)}%")
                        continue

                    if item.operator not in {"=", "!="}:
                        raise ValueError(
                            f"El campo '{item.field}' solo admite filtros de escritura con '=', '!=' o 'contains'."
                        )

                    value_expr, fk_params, fk_validation = self._resolve_fk_reference(fk_ref, item.value)
                    clauses.append(f"{fk_col} {item.operator} {value_expr}")
                    params.extend(fk_params)
                    if fk_validation is not None:
                        validations.append(fk_validation)
                    continue
                else:
                    unresolvable.append(item.field)
                    continue

            if item.value is None:
                op = "IS NOT NULL" if item.operator == "!=" else "IS NULL"
                clauses.append(f"{expr} {op}")
                continue

            # FK textual sobre columna directa: campo numérico (ej. operario_id,
            # maquina_id) con fk_lookup declarado y valor de texto (ej. "María
            # López"). Debe comprobarse ANTES de las ramas genéricas de
            # "contains" y "referencia a otro campo", o estas la interceptan
            # primero y generan SQL incorrecto sobre una columna entera.
            # Reutiliza _resolve_fk_reference, la misma fuente que usa
            # write_via_fk, para mantener una única vía de validación FK.
            if fspec.kind == "number" and fspec.fk_lookup and isinstance(item.value, str) and not _is_numeric(item.value):
                if item.operator == "contains":
                    fk_table, fk_field = fspec.fk_lookup.split(".", 1)
                    clauses.append(
                        f"{expr} IN (SELECT id FROM {fk_table} WHERE NORMALIZAR({fk_field}) LIKE ?)"
                    )
                    params.append(f"%{normalize_text(item.value)}%")
                    continue

                if item.operator in {"=", "!="}:
                    value_expr, fk_params, fk_validation = self._resolve_fk_reference(
                        fspec.fk_lookup, item.value
                    )
                    clauses.append(f"{expr} {item.operator} {value_expr}")
                    params.extend(fk_params)
                    if fk_validation is not None:
                        validations.append(fk_validation)
                    continue
                # Operadores de comparación (>, >=, <, <=) sobre un FK textual
                # no tienen sentido; caen al bloque "Numérico" de abajo, que
                # lanzará un ValueError claro de "no es numérico".

            if item.operator == "contains":
                clauses.append(f"NORMALIZAR({expr}) LIKE ?")
                params.append(f"%{normalize_text(item.value)}%")
                continue

            if isinstance(item.value, str):
                canonical_val = self._canonical_field(item.value)
                if canonical_val in spec.fields:
                    other_fspec = spec.fields[canonical_val]
                    other_expr = (other_fspec.write_expression or other_fspec.expression) if for_write else other_fspec.expression
                    if for_write and "." in other_expr and not other_fspec.write_via_fk:
                        unresolvable.append(f"{item.field}={item.value}")
                        continue
                    clauses.append(f"{expr} {item.operator} {other_expr}")
                    continue

            if fspec.kind == "number":
                try:
                    params.append(float(item.value))
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"'{item.value}' no es numérico para '{item.field}'.") from exc
                clauses.append(f"{expr} {item.operator} ?")
                continue

            clauses.append(f"NORMALIZAR({expr}) {item.operator} NORMALIZAR(?)")
            params.append(str(item.value))

        if for_write and not clauses and unresolvable:
            raise ValueError(
                f"Los campos {unresolvable} no tienen write_via_fk en Schema.md y no pueden "
                "usarse como filtros de escritura. Proporciona un identificador directo (id)."
            )

        return "WHERE " + " AND ".join(clauses), params, validations

    def _select_fields(self, req: ParsedRequest, spec: EntitySpec) -> list[str]:
        if not req.requested_fields:
            return spec.default_select
        selected: list[str] = []
        if spec.identifier_field and spec.identifier_field in spec.fields:
            selected.append(spec.identifier_field)
        for raw in req.requested_fields:
            logical = self._canonical_field(raw)
            if logical in spec.fields and logical not in selected:
                selected.append(logical)
        return selected or spec.default_select

    def _metric(self, spec: EntitySpec, req: ParsedRequest) -> tuple[str, str]:
        if req.derived_metric == "diferencia_objetivo_producido":
            if spec.name != "orden":
                raise ValueError("diferencia_objetivo_producido solo aplica a 'orden'.")
            return "(o.cantidad_objetivo - o.cantidad_producida)", "diferencia"

        if req.aggregation == "count":
            return "COUNT(*)", "total"

        if req.aggregation == "count_distinct":
            if req.group_by:
                raise ValueError(
                    "'count_distinct' no debe combinarse con group_by: son operaciones "
                    "semánticamente incompatibles (total de valores distintos vs. desglose por grupo)."
                )
            agg_field = req.aggregation_field or spec.default_aggregation_field
            if not agg_field:
                raise ValueError("'count_distinct' requiere aggregation_field.")
            logical = self._canonical_field(agg_field)
            if logical not in spec.fields:
                raise ValueError(f"Campo de agregación no válido: {agg_field}")
            return f"COUNT(DISTINCT {spec.fields[logical].expression})", f"distinct_{logical}"

        if req.aggregation:
            agg_field = req.aggregation_field or spec.default_aggregation_field
            if not agg_field:
                raise ValueError(f"'{req.aggregation}' requiere aggregation_field.")
            logical = self._canonical_field(agg_field)
            if logical not in spec.fields:
                raise ValueError(f"Campo de agregación no válido: {agg_field}")
            return f"{req.aggregation.upper()}({spec.fields[logical].expression})", f"{req.aggregation}_{logical}"

        raise ValueError("No se ha solicitado ninguna métrica.")

    def _group_by(self, spec: EntitySpec, req: ParsedRequest) -> tuple[str, list[str]]:
        if not req.group_by:
            return "", []
        group_fields: list[str] = []
        for raw in req.group_by:
            logical = self._canonical_field(raw)
            if logical not in spec.fields:
                raise ValueError(f"Campo no válido para agrupar: {raw}")
            group_fields.append(logical)
        sql = "GROUP BY " + ", ".join(spec.fields[field].expression for field in group_fields)
        return sql, group_fields

    def _order_by(self, spec: EntitySpec, req: ParsedRequest, metric_alias: str | None = None) -> str:
        if not req.sort:
            if req.group_by:
                ordered_groups = []
                for raw in req.group_by:
                    logical = self._canonical_field(raw)
                    ordered_groups.append(f"{spec.fields[logical].expression} ASC")
                return "ORDER BY " + ", ".join(ordered_groups)
            return f"ORDER BY {spec.display_order}"

        parts: list[str] = []
        for item in req.sort:
            direction = "DESC" if item.direction.lower() == "desc" else "ASC"
            if item.field == "__metric__":
                parts.append(f"{metric_alias or '__metric__'} {direction}")
                continue
            logical = self._canonical_field(item.field)
            if logical not in spec.fields:
                raise ValueError(f"Campo no válido para ordenar: {item.field}")
            parts.append(f"{spec.fields[logical].expression} {direction}")
        return "ORDER BY " + ", ".join(parts)

    def _build_select(self, req: ParsedRequest, spec: EntitySpec) -> QueryPlan:
        filters = self._normalize_filters(req, spec)
        where_sql, params, _ = self._build_where(spec, filters)

        if req.aggregation or req.derived_metric:
            metric_expr, metric_alias = self._metric(spec, req)
            group_sql, group_fields = self._group_by(spec, req)
            order_sql = self._order_by(spec, req, metric_alias=metric_alias)

            parts = [f"{spec.fields[field].expression} AS {field}" for field in group_fields]
            if req.derived_metric and not group_fields:
                for field in self._select_fields(req, spec):
                    if field not in group_fields:
                        parts.append(f"{spec.fields[field].expression} AS {field}")
            parts.append(f"{metric_expr} AS {metric_alias}")

            sql = f"SELECT {', '.join(parts)} FROM {spec.from_sql} {where_sql} {group_sql} {order_sql}".strip()
            if req.limit:
                sql += " LIMIT ?"
                params.append(req.limit)
            return QueryPlan(
                intent="consultar",
                entity_type=spec.name,
                sql=sql,
                params=params,
                select_fields=group_fields,
                is_analytic=True,
                metric_alias=metric_alias,
                group_fields=group_fields,
                summary_title=spec.summary_title,
            )

        selected = self._select_fields(req, spec)
        select_sql = ", ".join(f"{spec.fields[field].expression} AS {field}" for field in selected)
        order_sql = self._order_by(spec, req, metric_alias=None)
        sql = f"SELECT {select_sql} FROM {spec.from_sql} {where_sql} {order_sql}".strip()
        if req.limit:
            sql += " LIMIT ?"
            params.append(req.limit)
        return QueryPlan(
            intent="consultar",
            entity_type=spec.name,
            sql=sql,
            params=params,
            select_fields=selected,
            is_analytic=False,
            summary_title=spec.summary_title,
        )

    def _build_insert(self, req: ParsedRequest, spec: EntitySpec) -> QueryPlan:
        if not spec.writable_table:
            raise ValueError(f"'{spec.name}' no admite inserciones.")
        if not req.write_values:
            raise ValueError("No se han proporcionado write_values.")

        cols: list[str] = []
        params: list[Any] = []
        value_exprs: list[str] = []
        fk_validations: list[FKValidation] = []

        for raw, value in req.write_values.items():
            field = self._canonical_field(raw)
            if field not in spec.writable_fields:
                raise ValueError(f"Campo no escribible para {spec.name}: {raw}")
            fspec = spec.fields.get(field)
            cols.append(field)

            if fspec and fspec.kind == "number" and fspec.fk_lookup and value is not None:
                value_expr, fk_params, fk_validation = self._resolve_fk_reference(fspec.fk_lookup, value)
                value_exprs.append(value_expr)
                params.extend(fk_params)
                if fk_validation is not None:
                    fk_validations.append(fk_validation)
            else:
                value_exprs.append("?")
                params.append(value)

        sql = (
            f"INSERT INTO {spec.writable_table} ({', '.join(cols)}) "
            f"VALUES ({', '.join(value_exprs)})"
        )
        return QueryPlan(
            intent="registrar",
            entity_type=spec.name,
            sql=sql,
            params=params,
            rowcount_expected=True,
            fk_validations=fk_validations,
        )

    def _build_update(self, req: ParsedRequest, spec: EntitySpec) -> QueryPlan:
        if not spec.writable_table:
            raise ValueError(f"'{spec.name}' no admite actualizaciones.")
        if not req.write_values:
            raise ValueError("No se han proporcionado write_values.")

        filters = self._normalize_filters(req, spec)
        if not filters:
            raise ValueError("Actualizar requiere al menos un filtro identificador.")

        assignments: list[str] = []
        params: list[Any] = []
        fk_validations: list[FKValidation] = []

        for raw, value in req.write_values.items():
            field = self._canonical_field(raw)
            if field not in spec.writable_fields:
                raise ValueError(f"Campo no escribible para {spec.name}: {raw}")

            fspec = spec.fields.get(field)
            if fspec and fspec.kind == "number" and fspec.fk_lookup and value is not None:
                value_expr, fk_params, fk_validation = self._resolve_fk_reference(fspec.fk_lookup, value)
                assignments.append(f"{field} = {value_expr}")
                params.extend(fk_params)
                if fk_validation is not None:
                    fk_validations.append(fk_validation)
            else:
                assignments.append(f"{field} = ?")
                params.append(value)

        where_sql, where_params, where_validations = self._build_where(spec, filters, for_write=True)
        params.extend(where_params)
        fk_validations.extend(where_validations)

        sql = f"UPDATE {spec.writable_table} SET {', '.join(assignments)} {where_sql}".strip()
        return QueryPlan(
            intent="actualizar",
            entity_type=spec.name,
            sql=sql,
            params=params,
            rowcount_expected=True,
            fk_validations=fk_validations,
        )

    def _build_delete(self, req: ParsedRequest, spec: EntitySpec) -> QueryPlan:
        if not self.allow_deletes:
            raise ValueError("Eliminar está desactivado. Usa --allow-deletes para activarlo.")
        if not spec.writable_table:
            raise ValueError(f"'{spec.name}' no admite eliminación.")

        filters = self._normalize_filters(req, spec)
        if not filters:
            raise ValueError("Eliminar requiere al menos un filtro identificador.")

        where_sql, params, fk_validations = self._build_where(spec, filters, for_write=True)
        sql = f"DELETE FROM {spec.writable_table} {where_sql}".strip()
        return QueryPlan(
            intent="eliminar",
            entity_type=spec.name,
            sql=sql,
            params=params,
            rowcount_expected=True,
            fk_validations=fk_validations,
        )