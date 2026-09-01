from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from mistralai import Mistral

from .schemas import ParsedRequest

load_dotenv()
MODEL_NAME = os.getenv("MISTRAL_MODEL", "mistral-small-latest")


# Solo instrucciones técnicas de formato.
# Todo el conocimiento semántico (dominio, vocabulario, ejemplos, reglas de negocio)
# vive en Base.md y Schema.md, que se inyectan en el system prompt en tiempo de ejecución.
PROMPT_RULES = """
Convierte lenguaje natural en JSON estructurado para un MES industrial.

REGLAS TÉCNICAS (no negociables):
1. Devuelve SOLO JSON válido. Nunca generes SQL.
2. Los intents permitidos son exactamente: consultar, registrar, actualizar, eliminar, pedir_aclaracion.
3. entity_type debe ser uno de los definidos en Schema.md. No inventes entidades.
4. Usa filters para condiciones de búsqueda, entity_value para identificadores concretos.
5. Usa write_values en registrar y actualizar. Nunca metas en write_values campos que se usen para identificar el registro (esos van en filters o entity_value).
6. Si la consulta es ambigua o faltan datos obligatorios, devuelve pedir_aclaracion con needs_clarification=true y clarification_question.
7. Si una consulta es de seguimiento conversacional, utiliza el contexto conversacional recibido.
8. Usa operadores canónicos: =, !=, >, >=, <, <=, contains. Nunca is, eq, gt, etc.
9. En registrar: siempre incluye write_values. Si faltan campos obligatorios, usa pedir_aclaracion.
10. En actualizar: siempre incluye write_values Y (entity_value o filters). Si falta el objetivo, usa pedir_aclaracion.
11. Si un campo de escritura termina en _id y Schema.md declara fk_lookup para ese campo, puedes usar en write_values una referencia humana (nombre o referencia funcional) en vez del id numérico. El backend la resolverá.
12. El backend resuelve automáticamente referencias textuales a FKs (ej. nombre de material → material_id, referencia de orden → orden_id). Úsalas con normalidad en entity_value y filters para identificar registros en UPDATE. Solo usa pedir_aclaracion si no hay ningún identificador en absoluto.
13. Cuando el contexto conversacional muestre una operación de escritura interrumpida por una aclaración, y el usuario proporcione ahora el identificador solicitado, reconstruye el write_values completo de esa operación pendiente. Nunca devuelvas write_values vacío si el contexto indica que había valores concretos a escribir.

Consulta Base.md para entender el dominio y el vocabulario del operario.
Consulta Schema.md para saber qué campos y entidades existen realmente.
""".strip()


class Agent:
    """Interpreta lenguaje natural y devuelve un ParsedRequest.

    Este módulo NO genera SQL. Su responsabilidad es:
    - leer Base.md y Schema.md;
    - usar esos documentos como contexto del modelo;
    - transformar la frase del operario en una estructura segura.
    """

    def __init__(
        self,
        base_path: str | os.PathLike[str] = "Base.md",
        schema_path: str | os.PathLike[str] = "Schema.md",
        api_key: str | None = None,
    ) -> None:
        api_key = api_key or os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise RuntimeError("No se encontró MISTRAL_API_KEY en el .env")

        self.client = Mistral(api_key=api_key)
        self.base_path = Path(base_path)
        self.schema_path = Path(schema_path)

        # Cache de documentos: evita releer disco en cada llamada
        self._doc_cache: dict[str, tuple[float, str]] = {}  # path → (mtime, content)

    def _read_doc(self, path: Path) -> str:
        """Lee un documento con caché invalidada por mtime."""
        if not path.exists():
            return ""
        mtime = path.stat().st_mtime
        cached = self._doc_cache.get(str(path))
        if cached and cached[0] == mtime:
            return cached[1]
        content = path.read_text(encoding="utf-8")
        self._doc_cache[str(path)] = (mtime, content)
        return content

    def _build_system_prompt(self, extra_context: str | None = None) -> str:
        base_text = self._read_doc(self.base_path)
        schema_text = self._read_doc(self.schema_path)
        prompt = (
            f"{PROMPT_RULES}\n\n"
            f"BASE DE CONOCIMIENTO FUNCIONAL (Base.md):\n{base_text}\n\n"
            f"ESQUEMA TÉCNICO DE LA BD (Schema.md):\n{schema_text}\n\n"
            "Devuelve únicamente JSON que cumpla ParsedRequest."
        )
        if extra_context:
            prompt += f"\n\nCONTEXTO CONVERSACIONAL:\n{extra_context}"
        return prompt

    def parse(self, user_input: str, extra_context: str | None = None) -> ParsedRequest:
        response = self.client.chat.complete(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": self._build_system_prompt(extra_context)},
                {"role": "user", "content": user_input},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content  # type: ignore
        content = self._extract_json(str(raw).strip())
        data = json.loads(content)
        data = self._sanitize(data, user_input=user_input)
        return ParsedRequest(**data)

    @staticmethod
    def _sanitize(data: dict, user_input: str = "") -> dict:
        """Sanitización estructural de la salida del modelo.

        Solo corrige problemas de formato y estructura: campos ausentes, tipos
        incorrectos, valores fuera de enum. NO aplica lógica semántica del dominio
        (esa vive en Base.md y se resuelve vía prompt).

        user_input se pasa para el mecanismo de rescate: cuando el LLM devuelve
        pedir_aclaracion pese a que el texto contiene identificador y valores,
        se recupera la operación sin molestar al operario.
        """
        # Área: normalizar a valor válido o 'desconocida'
        valid_areas = {"produccion", "almacen", "mantenimiento", "calidad", "desconocida"}
        if "area" not in data or data["area"] not in valid_areas:
            data["area"] = "desconocida"

        # Filtros: normalizar dict suelto → lista, eliminar items mal formados
        raw_filters = data.get("filters", [])
        if isinstance(raw_filters, dict):
            raw_filters = [
                {"field": field, "operator": "=", "value": value}
                for field, value in raw_filters.items()
            ]
        if isinstance(raw_filters, list):
            raw_filters = [
                item for item in raw_filters
                if isinstance(item, dict) and "field" in item and "operator" in item
            ]
        data["filters"] = raw_filters

        # Listas opcionales: garantizar tipo lista
        for key in ("requested_fields", "group_by", "sort"):
            if not isinstance(data.get(key), list):
                data[key] = []

        # write_values: garantizar dict
        if not isinstance(data.get("write_values"), dict):
            data["write_values"] = {}

        # scope: default
        data.setdefault("scope", "actual")

        # derived_metric: asegurar que sea un string literal válido o None
        # El LLM a veces confunde este campo con un sort spec u otro objeto
        valid_derived_metrics = {"diferencia_objetivo_producido"}
        dm = data.get("derived_metric")
        if dm is not None and (not isinstance(dm, str) or dm not in valid_derived_metrics):
            data["derived_metric"] = None

        # Reparación: el LLM a veces expresa "diferencia objetivo-producido" como
        # aggregation=max/sum + aggregation_field="diferencia" (campo que no existe).
        # Lo remapeamos al derived_metric correcto.
        DIFERENCIA_FIELD_HINTS = {"diferencia", "diferencia_objetivo_producido", "diferencia_objetivo", "brecha", "desvio", "desvío"}
        if (
            data.get("entity_type") == "orden"
            and data.get("aggregation_field", "") in DIFERENCIA_FIELD_HINTS
            and not data.get("derived_metric")
        ):
            data["derived_metric"] = "diferencia_objetivo_producido"
            data["aggregation"] = None
            data["aggregation_field"] = None
            # Si no hay sort explícito, ordenar descendente por la métrica
            if not data.get("sort"):
                data["sort"] = [{"field": "__metric__", "direction": "desc"}]

        # ── Guardianes de escritura ──────────────────────────────────────────
        # Antes de aplicarlos intentamos rescatar operaciones que el LLM ha
        # convertido erróneamente en pedir_aclaracion, extrayendo del texto
        # original el identificador y/o los valores que el modelo ha perdido.
        if data.get("intent") == "pedir_aclaracion" and user_input:
            data = Agent._try_rescue_action_clarification(data, user_input)
        if data.get("intent") == "pedir_aclaracion" and user_input:
            data = Agent._try_rescue(data, user_input)

        intent = data.get("intent")

        if intent in {"registrar", "actualizar"} and not data.get("write_values"):
            data["intent"] = "pedir_aclaracion"
            data["needs_clarification"] = True
            data["clarification_question"] = (
                "Necesito los valores concretos que quieres escribir para poder continuar."
            )

        if intent == "actualizar" and not data.get("entity_value") and not data.get("filters"):
            data["intent"] = "pedir_aclaracion"
            data["needs_clarification"] = True
            data["clarification_question"] = (
                "Necesito identificar qué registro quieres actualizar. "
                "¿Puedes indicarme un nombre, referencia u otro identificador?"
            )

        return data

    # ── Patrones de rescate ─────────────────────────────────────────────────
    # Expresiones regulares para extraer identificadores y valores del texto
    # libre cuando el LLM los pierde al generar pedir_aclaracion.

    # Referencia de orden estilo OP-2024-001
    _RE_OP_REF = re.compile(r'\b(OP[-\s]?\d{4}[-\s]?\d{3,})\b', re.IGNORECASE)

    # Nombre de material tras "del material / del / de la / de" (para movimientos)
    _RE_MATERIAL = re.compile(
        r'(?:del?\s+material|del?\s+la\s+entrada\s+de|del?\s+la\s+salida\s+de)\s+'
        r'([^,\.;\ny]+?)(?=\s+y\s|\s+con\s|\s+pon\s|\s+cambia|$)',
        re.IGNORECASE,
    )

    # "pon/cambia/establece/fija <campo> [a/en/como] <valor>"
    # Verbos que preceden campo+valor. Se excluye "actualiza" solo al inicio
    # de frase para no capturar "Actualiza el movimiento..." como campo.
    # La preposición (a/en/como) es opcional.
    _RE_WRITE = re.compile(
        r'(?:(?:^|\s)(?:y\s+)?(?:pon|cambia|establece|fija)\s+([\w_]+)\s+(?:(?:a|en|como)\s+)?)'
        r'([^,\.;\n]+?)(?=\s*(?:,|\.|;|\s+y\s|\s+con\s|\s*$))',
        re.IGNORECASE | re.MULTILINE,
    )

    # Palabras gramaticales que nunca son nombres de campo
    _STOP_WORDS = frozenset({
        "el", "la", "los", "las", "un", "una", "unos", "unas",
        "de", "del", "al", "en", "y", "o", "que", "se", "su",
        "este", "esta", "ese", "esa",
    })

    # Verbos de acción reconocibles en la respuesta a una aclaración sobre
    # "qué acción quieres realizar" (consultar/registrar/actualizar/eliminar).
    _ACTION_VERBS = {
        "consultar": "consultar", "consulta": "consultar", "consultame": "consultar",
        "registrar": "registrar", "registra": "registrar",
        "actualizar": "actualizar", "actualiza": "actualizar",
        "eliminar": "eliminar", "elimina": "eliminar", "borrar": "eliminar", "borra": "eliminar",
    }

    @staticmethod
    def _try_rescue_action_clarification(data: dict, user_input: str) -> dict:
        """Rescata el caso en que el LLM pidió aclaración sobre QUÉ ACCIÓN
        realizar (consultar/registrar/actualizar/eliminar) y el turno actual
        ya nombra una de esas acciones, pero el modelo ha vuelto a devolver
        pedir_aclaracion — normalmente repitiendo la misma clarification_question
        de antes en vez de resolverla.

        General por diseño: no depende de qué entidad estaba pendiente
        (máquina, orden, material...) ni de la redacción exacta de la
        pregunta — solo comprueba si el usuario ya ha nombrado una acción
        válida en su respuesta. Si es así, resuelve el intent directamente;
        si no, deja el pedir_aclaracion tal cual para que _try_rescue (u
        otro turno de aclaración) lo maneje.
        """
        text = user_input.strip().lower()
        for palabra, accion in Agent._ACTION_VERBS.items():
            if re.search(rf"\b{re.escape(palabra)}\b", text):
                rescued = dict(data)
                rescued["intent"] = accion
                rescued["needs_clarification"] = False
                rescued["clarification_question"] = None
                return rescued
        return data

    @staticmethod
    def _try_rescue(data: dict, user_input: str) -> dict:
        """Intenta revertir un pedir_aclaracion innecesario extrayendo del texto
        el identificador y los valores a escribir que el LLM ha descartado.

        Actúa sobre cualquier entity_type; no codifica lógica por entidad salvo
        los patrones de identificador canónicos (referencia de orden, material).
        Solo rescata si tras la extracción hay al menos un valor a escribir.
        """
        entity_type = data.get("entity_type")
        rescued = dict(data)

        # 1. Extraer write_values del texto si el LLM los perdió
        if not rescued.get("write_values"):
            extracted_wv: dict = {}
            for m in Agent._RE_WRITE.finditer(user_input):
                campo = m.group(1).strip().lower()
                if campo in Agent._STOP_WORDS:
                    continue   # artículo/preposición capturado por error
                valor_raw = m.group(2).strip()
                # Intentar conversión numérica
                try:
                    valor: object = int(valor_raw)
                except ValueError:
                    try:
                        valor = float(valor_raw)
                    except ValueError:
                        valor = valor_raw
                extracted_wv[campo] = valor
            if extracted_wv:
                rescued["write_values"] = extracted_wv

        # Sin valores que escribir no hay operación rescatable
        if not rescued.get("write_values"):
            return data

        # 2. Extraer identificador si el LLM también lo perdió
        has_id = rescued.get("entity_value") or any(
            isinstance(f, dict) and f.get("value") is not None
            for f in rescued.get("filters", [])
        )

        if not has_id:
            # Referencia de orden (inspecciones, órdenes)
            m_op = Agent._RE_OP_REF.search(user_input)
            if m_op and entity_type in ("inspeccion", "orden", None):
                rescued["entity_value"] = m_op.group(1).upper().replace(" ", "-")
                rescued["entity_type"] = rescued.get("entity_type") or "inspeccion"
                has_id = True

            # Nombre de material (movimientos)
            if not has_id:
                m_mat = Agent._RE_MATERIAL.search(user_input)
                if m_mat and entity_type in ("movimiento", None):
                    material = m_mat.group(1).strip()
                    filters = list(rescued.get("filters", []))
                    filters.append({"field": "material_nombre", "operator": "=", "value": material})
                    rescued["filters"] = filters
                    rescued["entity_type"] = rescued.get("entity_type") or "movimiento"
                    has_id = True

        # Solo rescatamos si tenemos identificador + valores
        if not has_id:
            return data

        rescued["intent"] = "actualizar"
        rescued["needs_clarification"] = False
        rescued["clarification_question"] = None
        return rescued

    @staticmethod
    def _extract_json(content: str) -> str:
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.IGNORECASE)
            content = re.sub(r"\s*```$", "", content.strip())
        match = re.search(r"\{.*\}", content, re.DOTALL)
        return match.group() if match else content

    @staticmethod
    def merge_clarification_response(
        pending_op: ParsedRequest,
        clarification_response: ParsedRequest,
    ) -> ParsedRequest:
        """Fusiona la respuesta a una aclaración con la operación de escritura pendiente.

        Cuando el guardián convierte un actualizar/registrar en pedir_aclaracion,
        el bucle principal (main.py) debe guardar la operación original. Al recibir
        la respuesta del operario, llamar a este método para restaurar el contexto
        de escritura que el modelo puede haber perdido.

        Solo fusiona si:
        - la respuesta tiene intent de escritura (actualizar / registrar);
        - el write_values de la respuesta está vacío;
        - la operación pendiente sí tenía write_values.
        """
        if (
            clarification_response.intent in {"actualizar", "registrar"}
            and not clarification_response.write_values
            and pending_op.write_values
        ):
            data = clarification_response.dict()
            data["write_values"] = dict(pending_op.write_values)
            return ParsedRequest(**data)
        return clarification_response

    def parse_request(self, user_input: str, extra_context: str | None = None) -> ParsedRequest:
        return self.parse(user_input, extra_context)