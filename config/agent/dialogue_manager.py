from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from .schemas import Filter, ParsedRequest

FOLLOWUP_PREFIXES = (
    "y ",
    "y, ",
    "y cuáles",
    "y cuales",
    "y las",
    "y los",
    "y en",
    "y de",
    "entonces",
    "de esas",
    "de esos",
    "de ellas",
    "de ellos",
)

PRONOUN_REFS = ("esas", "esos", "ellas", "ellos", "mismas", "mismos")


def _load_aliases_from_schema(schema_path: str | Path) -> dict[str, str]:
    """Carga el bloque global_config de aliases desde Schema.md.

    Misma fuente que usa QueryBuilder, eliminando la tercera copia hardcodeada.
    """
    try:
        text = Path(schema_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}

    import re as _re
    blocks = _re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
    for raw in blocks:
        data = yaml.safe_load(raw)
        if isinstance(data, dict) and data.get("type") == "global_config":
            raw_aliases = data.get("aliases", {})
            if isinstance(raw_aliases, dict):
                return {_normalize(k): str(v) for k, v in raw_aliases.items()}
    return {}


def _normalize(text: str) -> str:
    text = str(text).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


@dataclass
class ConversationState:
    last_request: Optional[ParsedRequest] = None
    history: list[ParsedRequest] = field(default_factory=list)
    pending_clarification: Optional[str] = None


class DialogueManager:
    def __init__(self, schema_path: str | Path = "Schema.md") -> None:
        self.state = ConversationState()
        self._aliases = _load_aliases_from_schema(schema_path)

    def resolve(self, user_input: str, current: ParsedRequest) -> ParsedRequest:
        previous = self.state.last_request
        if previous is None:
            return current

        if not self._looks_like_followup(user_input, current):
            return current

        return self._merge(previous, current)

    def update(self, resolved: ParsedRequest) -> None:
        self.state.last_request = resolved
        self.state.history.append(resolved)
        self.state.pending_clarification = resolved.clarification_question if resolved.needs_clarification else None

    def reset(self) -> None:
        self.state = ConversationState()

    def build_context_for_agent(self) -> str:
        """Construye el contexto conversacional que verá el LLM.

        Deliberadamente incluye SOLO los campos que _merge() puede llegar a
        heredar (intent, entity_type, area, scope, entity_value, filters).
        No se vuelca aggregation/group_by/derived_metric/sort/limit/
        requested_fields/write_values del turno anterior: _merge() nunca los
        usa, y mostrárselos al LLM como JSON solo lo predispone a copiar esa
        forma en preguntas nuevas que no la piden (ver Base.md, "Reglas de
        conversación", regla 3).
        """
        lines: list[str] = []
        if self.state.last_request is not None:
            r = self.state.last_request
            summary = {
                "intent": r.intent,
                "entity_type": r.entity_type,
                "area": r.area,
                "scope": r.scope,
                "entity_value": r.entity_value,
                "filters": [f.model_dump(exclude_none=True) for f in r.filters],
            }
            lines.append(
                "Última consulta resuelta (solo campos de continuidad; "
                "no incluye aggregation/group_by/derived_metric — no se heredan): "
                f"{json.dumps(summary, ensure_ascii=False)}"
            )
        if self.state.pending_clarification:
            lines.append(f"Pregunta de aclaración pendiente: {self.state.pending_clarification}")
        return "\n".join(lines)

    def _looks_like_followup(self, user_input: str, current: ParsedRequest) -> bool:
        text = _normalize(user_input)

        if any(text.startswith(prefix) for prefix in FOLLOWUP_PREFIXES):
            return True

        if any(token in text.split() for token in PRONOUN_REFS):
            return True

        if len(text.split()) <= 4 and self._is_structurally_incomplete(current):
            return True

        if current.filters and self._is_missing_entity(current):
            return True

        return False

    def _merge(self, previous: ParsedRequest, current: ParsedRequest) -> ParsedRequest:
        merged = current.model_copy(deep=True)

        if merged.intent == "pedir_aclaracion" and previous.intent != "pedir_aclaracion":
            merged.intent = previous.intent

        if self._is_missing_entity(merged):
            merged.entity_type = previous.entity_type

        if merged.area == "desconocida":
            merged.area = previous.area

        if merged.scope == "indefinido":
            merged.scope = previous.scope

        if not merged.entity_value and previous.entity_value:
            merged.entity_value = previous.entity_value

        merged.filters = self._merge_filters(previous.filters, current.filters)

        if merged.entity_type and merged.entity_type != "desconocido":
            merged.needs_clarification = False
            merged.clarification_question = None

        return merged

    def _merge_filters(self, previous_filters: list[Filter], current_filters: list[Filter]) -> list[Filter]:
        result: list[Filter] = []
        seen_fields: dict[str, int] = {}

        for filt in previous_filters:
            seen_fields[self._canonical_field(filt.field)] = len(result)
            result.append(filt.model_copy(deep=True))

        for filt in current_filters:
            field_key = self._canonical_field(filt.field)
            idx = seen_fields.get(field_key)
            if idx is not None:
                result[idx] = filt.model_copy(deep=True)
            else:
                seen_fields[field_key] = len(result)
                result.append(filt.model_copy(deep=True))

        return result

    def _canonical_field(self, field_name: str) -> str:
        """Normaliza un nombre de campo usando los aliases cargados de Schema.md."""
        return self._aliases.get(_normalize(field_name), field_name.strip())

    @staticmethod
    def _is_missing_entity(req: ParsedRequest) -> bool:
        return req.entity_type in (None, "desconocido")

    def _is_structurally_incomplete(self, req: ParsedRequest) -> bool:
        has_signal = bool(
            req.filters
            or req.entity_value
            or req.requested_fields
            or req.aggregation
            or req.write_values
        )
        return self._is_missing_entity(req) and has_signal