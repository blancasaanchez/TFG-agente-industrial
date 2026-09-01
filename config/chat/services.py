from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.conf import settings

from agent.agent import Agent
from agent.db_access import DBAccess
from agent.db_setup import get_connection
from agent.dialogue_manager import DialogueManager
from agent.schemas import ParsedRequest, QueryPlan
from agent.query_builder import QueryBuilder
from agent.response_builder import ResponseBuilder

# ── Configuración del agente ────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent / "agent"
BASE_PATH = BASE_DIR / "Base.md"
SCHEMA_PATH = BASE_DIR / "Schema.md"
DB_PATH = BASE_DIR / "mes.db"

_agent = Agent(
    base_path=BASE_PATH,
    schema_path=SCHEMA_PATH,
    api_key=settings.MISTRAL_API_KEY,
)
_builder = QueryBuilder(schema_path=SCHEMA_PATH)
_responder = ResponseBuilder(schema_path=SCHEMA_PATH)

# ── Política de permisos centralizada en este archivo ───────────────────────

ENTIDADES_CON_OPERARIO = {"orden"}
ENTIDADES_CON_INSPECTOR = {"inspeccion"}

ENTIDADES_BLOQUEADAS_OPERARIO = {
    "operario",
    "maquina",
    "componente",
    "material",
}

ENTIDADES_BLOQUEADAS_SUPERVISOR = {
    "maquina",
    "componente",
    "material",
}


def _get_rol(user) -> str:
    if user.is_superuser:
        return "administrador"
    grupos = set(user.groups.values_list("name", flat=True))
    if "administrador" in grupos:
        return "administrador"
    if "supervisor" in grupos:
        return "supervisor"
    return "operario"


def _get_nombre_operario(user) -> str:
    nombre_completo = f"{user.first_name} {user.last_name}".strip()
    return nombre_completo if nombre_completo else user.username


def _get_connection():
    return get_connection(str(DB_PATH))


def _is_write_intent(intent: str | None) -> bool:
    return intent in {"registrar", "actualizar", "eliminar"}


def _humanize_field_name(name: str) -> str:
    mapping = {
        # entity_type "en bruto" (sin sufijo _id / _nombre) que necesitan tilde
        "maquina": "máquina",
        "inspeccion": "inspección",
        "entity_value": "identificador",
        "cantidad_producida": "cantidad producida",
        "cantidad_objetivo": "cantidad objetivo",
        "stock_actual": "stock actual",
        "stock_minimo": "stock mínimo",
        "fecha_inicio": "fecha de inicio",
        "fecha_fin": "fecha de fin",
        "fecha_apertura": "fecha de apertura",
        "fecha_cierre": "fecha de cierre",
        "operario_id": "operario",
        "maquina_id": "máquina",
        "material_id": "material",
        "orden_id": "orden",
        "componente_id": "componente",
        "maquina_nombre": "máquina",
        "operario_nombre": "operario",
        "material_nombre": "material",
        "componente_nombre": "componente",
        "ubicacion": "ubicación",
    }
    return mapping.get(name, name.replace("_", " "))


def _format_filter_text(filters) -> str:
    if not filters:
        return ""

    op_map = {
        "=": "sea",
        "!=": "no sea",
        ">": "sea mayor que",
        ">=": "sea mayor o igual que",
        "<": "sea menor que",
        "<=": "sea menor o igual que",
        "contains": "contenga",
    }

    parts = []
    for f in filters:
        field = _humanize_field_name(getattr(f, "field", ""))
        operator = op_map.get(getattr(f, "operator", "="), getattr(f, "operator", "="))
        value = getattr(f, "value", None)
        if value is None:
            if getattr(f, "operator", "=") == "=":
                parts.append(f"{field} esté vacío")
            else:
                parts.append(f"{field} no esté vacío")
        else:
            parts.append(f"{field} {operator} '{value}'")

    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " y " + parts[-1]


def _format_write_values_text(write_values: dict[str, Any]) -> str:
    parts = []
    for key, value in write_values.items():
        parts.append(f"{_humanize_field_name(key)} = '{value}'")
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " y " + parts[-1]


def _summarize_write_operation(resolved: ParsedRequest, plan: QueryPlan) -> str:
    entidad = _humanize_field_name(resolved.entity_type or "registro")
    target = resolved.entity_value
    where_text = _format_filter_text(resolved.filters)
    values_text = _format_write_values_text(resolved.write_values)

    if resolved.intent == "registrar":
        return (
            f"Vas a registrar un nuevo {entidad}"
            + (f" con {values_text}." if values_text else ".")
        )

    if resolved.intent == "actualizar":
        target_text = ""
        if target:
            target_text = f" con identificador '{target}'"
        elif where_text:
            target_text = f" donde {where_text}"
        return (
            f"Vas a actualizar {entidad}{target_text}"
            + (f" cambiando {values_text}." if values_text else ".")
        )

    if resolved.intent == "eliminar":
        target_text = ""
        if target:
            target_text = f" con identificador '{target}'"
        elif where_text:
            target_text = f" donde {where_text}"
        return f"Vas a eliminar {entidad}{target_text}."

    return "Se va a ejecutar una operación de escritura."


# ── Gestión de sesión y estado ──────────────────────────────────────────────

def _load_dialogue(session) -> DialogueManager:
    dm = DialogueManager(schema_path=SCHEMA_PATH)
    raw = session.get("dialogue_state")
    if raw:
        data = json.loads(raw)
        if data.get("last_request"):
            dm.state.last_request = ParsedRequest(**data["last_request"])
        if data.get("pending_clarification"):
            dm.state.pending_clarification = data["pending_clarification"]
    return dm


def _save_dialogue(session, dm: DialogueManager) -> None:
    state = {
        "last_request": (
            dm.state.last_request.model_dump()
            if dm.state.last_request else None
        ),
        "pending_clarification": dm.state.pending_clarification,
    }
    session["dialogue_state"] = json.dumps(state)


def _load_pending_request(session) -> ParsedRequest | None:
    raw = session.get("pending_request")
    if not raw:
        return None
    try:
        return ParsedRequest(**json.loads(raw))
    except Exception:
        session.pop("pending_request", None)
        return None


def _save_pending_request(session, req: ParsedRequest) -> None:
    session["pending_request"] = json.dumps(req.model_dump())


def _clear_pending_write(session) -> None:
    session.pop("pending_write_input", None)
    session.pop("pending_plan", None)
    session.pop("pending_request", None)


def _clear_dialogue(session) -> None:
    session.pop("dialogue_state", None)


def _reset_after_cancel(session) -> None:
    _clear_pending_write(session)
    _clear_dialogue(session)

# ── Historial de chat en sesión ─────────────────────────────────────────────

def _load_chat_history(session) -> list[dict[str, str]]:
    raw = session.get("chat_history")
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        session.pop("chat_history", None)
        return []


def _save_chat_history(session, history: list[dict[str, str]]) -> None:
    session["chat_history"] = json.dumps(history)


def _append_chat_message(
    session,
    role: str,
    content: str,
    kind: str = "message",
) -> None:
    if not content:
        return

    history = _load_chat_history(session)
    history.append({
        "role": role,
        "kind": kind,
        "content": content,
    })

    history = history[-50:]
    _save_chat_history(session, history)


def _clear_chat_history(session) -> None:
    session.pop("chat_history", None)


def get_chat_history(session) -> list[dict[str, str]]:
    return _load_chat_history(session)

# ── Reconstrucción de aclaraciones pendientes ───────────────────────────────

def _merge_pending_clarification(
    pending_req: ParsedRequest | None,
    parsed: ParsedRequest,
    resolved: ParsedRequest,
    raw_user_input: str,
) -> ParsedRequest:
    if pending_req is None:
        return resolved

    if pending_req.intent not in {"registrar", "actualizar"}:
        return resolved

    merged = Agent.merge_clarification_response(pending_req, resolved)
    if _is_write_intent(merged.intent) and merged.write_values:
        return merged

    current_entity_type = (
        resolved.entity_type
        if resolved.entity_type not in (None, "desconocido")
        else parsed.entity_type
    )
    current_entity_value = resolved.entity_value or parsed.entity_value
    current_filters = list(resolved.filters or parsed.filters or [])

    if not current_entity_value and not current_filters:
        cleaned = raw_user_input.strip()
        if cleaned and len(cleaned.split()) <= 8:
            current_entity_value = cleaned

    if not (current_entity_value or current_filters):
        return merged

    rebuilt = pending_req.model_copy(deep=True)
    if current_entity_type and current_entity_type != "desconocido":
        rebuilt.entity_type = current_entity_type
    rebuilt.entity_value = current_entity_value
    rebuilt.filters = current_filters
    rebuilt.write_values = dict(pending_req.write_values)
    rebuilt.needs_clarification = False
    rebuilt.clarification_question = None
    return rebuilt


# ── Permisos centralizados ──────────────────────────────────────────────────

def _apply_role_permissions(resolved: ParsedRequest, user) -> dict[str, Any] | None:
    if not _is_write_intent(resolved.intent):
        return None

    rol = _get_rol(user)
    nombre_operario = _get_nombre_operario(user)

    if rol == "operario":
        if resolved.entity_type in ENTIDADES_BLOQUEADAS_OPERARIO:
            return {
                "tipo": "error",
                "respuesta": "No tienes permisos para modificar estos datos. "
                             "Contacta con tu supervisor o administrador.",
            }

        resolved.write_values.pop("operario_nombre", None)

        if resolved.entity_type in ENTIDADES_CON_OPERARIO:
            resolved.write_values["operario_id"] = nombre_operario
        elif resolved.entity_type in ENTIDADES_CON_INSPECTOR:
            resolved.write_values["inspector"] = nombre_operario
        else:
            resolved.write_values.pop("operario_id", None)
            resolved.write_values.pop("inspector", None)

    elif rol == "supervisor":
        if resolved.entity_type in ENTIDADES_BLOQUEADAS_SUPERVISOR:
            return {
                "tipo": "error",
                "respuesta": "No tienes permisos para modificar el catálogo del sistema. "
                             "Contacta con el administrador.",
            }

    return None


# ── Fases del flujo ─────────────────────────────────────────────────────────

def _handle_pending_confirmation(session, user_input: str) -> dict[str, Any] | None:
    pending_plan = session.get("pending_plan")
    if not pending_plan:
        return None

    answer = user_input.strip().lower().strip(".,;:!¡¿? ")

    if answer in {"s", "si", "sí", "y", "yes"}:
        plan = QueryPlan(**pending_plan)
        _clear_pending_write(session)

        conn = _get_connection()
        try:
            db = DBAccess(conn)
            result = db.execute(plan)
            response_text = _responder.build(result)
        except Exception as e:
            conn.close()
            return {
                "tipo": "error",
                "respuesta": str(e),
            }
        finally:
            conn.close()

        return {"tipo": "respuesta", "respuesta": response_text}

    if answer in {"n", "no"}:
        _reset_after_cancel(session)
        return {"tipo": "respuesta", "respuesta": "Operación cancelada."}

    return {
        "tipo": "confirmacion_pendiente",
        "respuesta": "Responde solo 's' para confirmar o 'n' para cancelar.",
    }


def _build_effective_input(session, user_input: str) -> str:
    pending_write_input = session.get("pending_write_input")
    if pending_write_input:
        return f"{user_input} [contexto: {pending_write_input}]"
    return user_input


def _handle_clarification(
    session,
    dm: DialogueManager,
    parsed: ParsedRequest,
    resolved: ParsedRequest,
    user_input: str,
    pending_request: ParsedRequest | None,
) -> dict[str, Any]:
    if pending_request is None and (
        _is_write_intent(resolved.intent)
        or bool(resolved.write_values)
        or _is_write_intent(parsed.intent)
    ):
        base_req = parsed if _is_write_intent(parsed.intent) else resolved
        _save_pending_request(session, base_req)

    if not session.get("pending_write_input"):
        session["pending_write_input"] = user_input

    dm.update(resolved)
    _save_dialogue(session, dm)

    return {
        "tipo": "aclaracion",
        "respuesta": resolved.clarification_question or "Necesito más detalle para continuar.",
    }


def _handle_write_confirmation(
    session,
    dm: DialogueManager,
    resolved: ParsedRequest,
    plan: QueryPlan,
) -> dict[str, Any]:
    session["pending_plan"] = plan.model_dump()
    _save_pending_request(session, resolved)

    dm.update(resolved)
    _save_dialogue(session, dm)

    resumen = _summarize_write_operation(resolved, plan)
    return {
        "tipo": "confirmacion_pendiente",
        "respuesta": f"{resumen}\n\n¿Confirmas la operación? (s/n)",
    }


def _handle_read_query(
    session,
    dm: DialogueManager,
    resolved: ParsedRequest,
    plan: QueryPlan,
) -> dict[str, Any]:
    conn = _get_connection()
    try:
        db = DBAccess(conn)
        result = db.execute(plan)
        response_text = _responder.build(result)
    finally:
        conn.close()

    _clear_pending_write(session)
    dm.update(resolved)
    _save_dialogue(session, dm)

    return {
        "tipo": "respuesta",
        "respuesta": response_text,
    }


# ── Función principal ────────────────────────────────────────────────────────

def procesar_consulta(user_input: str, session, user) -> dict[str, Any]:
    """
    Orquesta el flujo completo del agente web:
    - confirmación pendiente
    - contexto conversacional
    - parseo + resolución
    - permisos
    - aclaración / confirmación / ejecución
    """

    confirmation_response = _handle_pending_confirmation(session, user_input)
    if confirmation_response is not None:
        return confirmation_response

    dm = _load_dialogue(session)
    pending_request = _load_pending_request(session)

    effective_input = _build_effective_input(session, user_input)

    parsed = _agent.parse(
        effective_input,
        extra_context=dm.build_context_for_agent(),
    )
    resolved = dm.resolve(user_input, parsed)

    if pending_request is not None:
        resolved = _merge_pending_clarification(
            pending_req=pending_request,
            parsed=parsed,
            resolved=resolved,
            raw_user_input=user_input,
        )

    if resolved.intent == "pedir_aclaracion" or resolved.needs_clarification:
        return _handle_clarification(
            session=session,
            dm=dm,
            parsed=parsed,
            resolved=resolved,
            user_input=user_input,
            pending_request=pending_request,
        )

    permission_error = _apply_role_permissions(resolved, user)
    if permission_error is not None:
        _clear_pending_write(session)
        return permission_error

    plan = _builder.build(resolved)

    if _is_write_intent(resolved.intent):
        return _handle_write_confirmation(
            session=session,
            dm=dm,
            resolved=resolved,
            plan=plan,
        )

    return _handle_read_query(
        session=session,
        dm=dm,
        resolved=resolved,
        plan=plan,
    )

def append_chat_turn(session, user_text: str, result: dict[str, Any]) -> None:
    _append_chat_message(session, "user", user_text, "message")
    _append_chat_message(
        session,
        "assistant",
        result.get("respuesta", ""),
        result.get("tipo", "message"),
    )

def reset_sesion(session) -> None:
    """Borra todo el contexto conversacional y de escritura pendiente."""
    _clear_dialogue(session)
    _clear_pending_write(session)
    _clear_chat_history(session)

def clear_chat(session) -> None:
    """Borra solo el historial visual del chat, sin tocar el contexto del agente."""
    _clear_chat_history(session)