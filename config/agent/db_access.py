from __future__ import annotations

import sqlite3
from typing import Any

from .schemas import QueryPlan


class DBAccess:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def execute(self, plan: QueryPlan) -> dict[str, Any]:
        cur = self.conn.cursor()

        # Validaciones FK previas: permiten devolver un error legible cuando
        # una referencia textual no existe, antes de entrar al SQL principal.
        for check in plan.fk_validations:
            cur.execute(check.check_sql, check.check_params)
            if cur.fetchone() is None:
                raise ValueError(
                    f"No se encontró {check.label}. "
                    "Verifica que el registro existe antes de continuar."
                )

        cur.execute(plan.sql, plan.params)

        if plan.intent == "consultar":
            rows = cur.fetchall()
            return {
                "intent": plan.intent,
                "entity_type": plan.entity_type,
                "rows": rows,
                "select_fields": plan.select_fields,
                "is_analytic": plan.is_analytic,
                "metric_alias": plan.metric_alias,
                "group_fields": plan.group_fields,
                "summary_title": plan.summary_title,
            }

        self.conn.commit()

        if plan.rowcount_expected and cur.rowcount == 0:
            raise ValueError(
                "No se ha modificado ningún registro. La referencia indicada puede no existir "
                "o los filtros no han encontrado un registro coincidente."
            )

        return {
            "intent": plan.intent,
            "entity_type": plan.entity_type,
            "rowcount": cur.rowcount,
            "lastrowid": cur.lastrowid,
        }
