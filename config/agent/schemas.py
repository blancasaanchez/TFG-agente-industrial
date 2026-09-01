from __future__ import annotations

from typing import Any, Optional, TypeAlias, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Valores simples permitidos en filtros, parámetros y escrituras.
ScalarValue: TypeAlias = str | int | float | bool
QueryValue: TypeAlias = ScalarValue | None


class Filter(BaseModel):
    """Representa una condición lógica reusable del tipo campo-operador-valor."""

    model_config = ConfigDict(extra="ignore")

    field: str = Field(description="Campo lógico sobre el que se aplica el filtro")
    operator: Literal["=", "!=", ">", ">=", "<", "<=", "contains"] = Field(
        description="Operador lógico del filtro"
    )
    value: QueryValue = Field(
        default=None,
        description="Valor a comparar. None genera IS NULL / IS NOT NULL según el operador.",
    )

    @field_validator("field", mode="before")
    @classmethod
    def normalize_field_name(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("operator", mode="before")
    @classmethod
    def normalize_operator(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        op = value.strip().lower()
        mapping = {
            "is": "=",
            "eq": "=",
            "equals": "=",
            "igual": "=",
            "ne": "!=",
            "neq": "!=",
            "not_equals": "!=",
            "distinto": "!=",
            "gt": ">",
            "greater_than": ">",
            "mayor": ">",
            "gte": ">=",
            "greater_or_equal": ">=",
            "mayor_o_igual": ">=",
            "lt": "<",
            "less_than": "<",
            "menor": "<",
            "lte": "<=",
            "less_or_equal": "<=",
            "menor_o_igual": "<=",
            "like": "contains",
            "contiene": "contains",
        }
        return mapping.get(op, op)


class SortSpec(BaseModel):
    """Representa una ordenación por campo lógico."""

    model_config = ConfigDict(extra="ignore")

    field: str = Field(description="Campo lógico por el que ordenar")
    direction: Literal["asc", "desc"] = Field(default="asc")

    @field_validator("field", mode="before")
    @classmethod
    def normalize_field_name(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("direction", mode="before")
    @classmethod
    def normalize_direction(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class FKValidation(BaseModel):
    """Chequeo previo para una FK textual resuelta vía subquery.

    Si la consulta check_sql no devuelve filas, db_access abortará antes de ejecutar
    el SQL principal y devolverá un error legible.
    """

    model_config = ConfigDict(extra="ignore")

    label: str = Field(description="Descripción legible de la referencia que debe existir")
    check_sql: str = Field(description="SQL de validación previa")
    check_params: list[QueryValue] = Field(default_factory=list)


class ParsedRequest(BaseModel):
    """Contrato estructurado entre el LLM y el backend."""

    model_config = ConfigDict(extra="ignore")

    intent: Literal[
        "consultar",
        "registrar",
        "actualizar",
        "eliminar",
        "pedir_aclaracion",
    ] = Field(description="Tipo de operación solicitada")

    area: Literal[
        "produccion",
        "almacen",
        "mantenimiento",
        "calidad",
        "desconocida",
    ] = Field(default="desconocida", description="Área funcional principal")

    entity_type: Optional[
        Literal[
            "componente",
            "orden",
            "maquina",
            "operario",
            "material",
            "incidencia",
            "inspeccion",
            "movimiento",
            "desconocido",
        ]
    ] = Field(default=None, description="Entidad principal")

    entity_value: Optional[str] = Field(default=None, description="Identificador principal si aplica")

    scope: Literal["actual", "historico", "indefinido"] = Field(default="actual")

    filters: list[Filter] = Field(default_factory=list)
    requested_fields: list[str] = Field(default_factory=list)

    aggregation: Optional[Literal["count", "count_distinct", "sum", "avg", "max", "min"]] = Field(default=None)
    aggregation_field: Optional[str] = Field(default=None)
    group_by: list[str] = Field(default_factory=list)
    derived_metric: Optional[Literal["diferencia_objetivo_producido"]] = Field(default=None)
    sort: list[SortSpec] = Field(default_factory=list)
    limit: Optional[int] = Field(default=None, ge=1, le=200)

    write_values: dict[str, QueryValue] = Field(
        default_factory=dict,
        description="Campos a insertar o actualizar en operaciones de escritura",
    )

    notes: Optional[str] = Field(default=None)
    needs_clarification: bool = Field(default=False)
    clarification_question: Optional[str] = Field(default=None)

    @field_validator("entity_value", mode="before")
    @classmethod
    def normalize_entity_value(cls, value: Any) -> Any:
        if value is None:
            return None
        return str(value).strip()

    @field_validator("requested_fields", "group_by", mode="before")
    @classmethod
    def ensure_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if item is not None and str(item).strip()]

    @field_validator("scope", mode="before")
    @classmethod
    def normalize_scope(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        scope = value.strip().lower()
        mapping = {
            "concreto": "indefinido",
            "concreta": "indefinido",
            "especifico": "indefinido",
            "específico": "indefinido",
            "specific": "indefinido",
            "actual": "actual",
            "historico": "historico",
            "histórico": "historico",
            "indefinido": "indefinido",
        }
        return mapping.get(scope, scope)


class QueryPlan(BaseModel):
    """Plan SQL validado y listo para ejecutar."""

    model_config = ConfigDict(extra="ignore")

    intent: Literal["consultar", "registrar", "actualizar", "eliminar"]
    entity_type: str
    sql: str
    params: list[QueryValue] = Field(default_factory=list)
    rowcount_expected: bool = False
    select_fields: list[str] = Field(default_factory=list)
    is_analytic: bool = False
    metric_alias: Optional[str] = None
    group_fields: list[str] = Field(default_factory=list)
    summary_title: str = ""
    fk_validations: list[FKValidation] = Field(default_factory=list)