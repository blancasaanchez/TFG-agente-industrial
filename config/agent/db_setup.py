from __future__ import annotations

import sqlite3
from pathlib import Path

from .query_builder import normalize_text


def get_connection(db_path: str = "mes.db") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("NORMALIZAR", 1, normalize_text)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS componentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            descripcion TEXT,
            categoria TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS maquinas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            tipo TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'operativa',
            ubicacion TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS operarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            turno TEXT NOT NULL,
            especialidad TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ordenes_produccion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referencia TEXT NOT NULL UNIQUE,
            componente_id INTEGER NOT NULL,
            cantidad_objetivo INTEGER NOT NULL,
            cantidad_producida INTEGER NOT NULL DEFAULT 0,
            maquina_id INTEGER,
            operario_id INTEGER,
            estado TEXT NOT NULL DEFAULT 'pendiente',
            fecha_inicio TEXT,
            fecha_fin TEXT,
            FOREIGN KEY (componente_id) REFERENCES componentes(id),
            FOREIGN KEY (maquina_id) REFERENCES maquinas(id),
            FOREIGN KEY (operario_id) REFERENCES operarios(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS materiales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            unidad TEXT NOT NULL,
            stock_actual REAL NOT NULL DEFAULT 0,
            stock_minimo REAL NOT NULL DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS movimientos_almacen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            cantidad REAL NOT NULL,
            motivo TEXT,
            fecha TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (material_id) REFERENCES materiales(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS incidencias_maquina (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            maquina_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            descripcion TEXT,
            estado TEXT NOT NULL DEFAULT 'abierta',
            fecha_apertura TEXT DEFAULT CURRENT_TIMESTAMP,
            fecha_cierre TEXT,
            FOREIGN KEY (maquina_id) REFERENCES maquinas(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS inspecciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            orden_id INTEGER NOT NULL,
            resultado TEXT NOT NULL,
            defectos_encontrados TEXT,
            inspector TEXT,
            fecha TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (orden_id) REFERENCES ordenes_produccion(id)
        )
        """
    )

    conn.commit()


# Demo opcional para pruebas locales.
def seed_demo_data(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    for tabla in [
        "inspecciones",
        "incidencias_maquina",
        "movimientos_almacen",
        "ordenes_produccion",
        "materiales",
        "operarios",
        "maquinas",
        "componentes",
    ]:
        cur.execute(f"DELETE FROM {tabla}")

    cur.execute("DELETE FROM sqlite_sequence")

    componentes = [
        ("Bloque de motor V6", "Bloque principal motor 6 cilindros", "motor"),
        ("Culata aluminio", "Culata para motor V6", "motor"),
        ("Disco de freno delantero", "Disco ventilado 320mm", "frenos"),
        ("Pastilla de freno", "Pastilla cerámica alto rendimiento", "frenos"),
        ("Paragolpes delantero", "Paragolpes ABS inyectado", "carroceria"),
        ("Panel puerta izquierda", "Panel exterior acero galvanizado", "carroceria"),
        ("Alternador 14V", "Alternador para sistemas eléctricos", "electrico"),
        ("Caja de cambios 6 vel", "Transmisión manual 6 velocidades", "transmision"),
    ]
    cur.executemany(
        "INSERT INTO componentes (nombre, descripcion, categoria) VALUES (?,?,?)",
        componentes,
    )

    maquinas = [
        ("Prensa P-01", "prensa hidráulica", "operativa", "Nave A"),
        ("Fresadora F-01", "fresadora CNC", "operativa", "Nave A"),
        ("Fresadora F-02", "fresadora CNC", "averiada", "Nave A"),
        ("Torno T-01", "torno CNC", "operativa", "Nave B"),
        ("Torno T-02", "torno CNC", "en_mantenimiento", "Nave B"),
        ("Soldadora S-01", "soldadora MIG", "operativa", "Nave C"),
        ("Inyectora I-01", "inyectora plástico", "operativa", "Nave C"),
        ("Rectificadora R-01", "rectificadora plana", "operativa", "Nave B"),
    ]
    cur.executemany(
        "INSERT INTO maquinas (nombre, tipo, estado, ubicacion) VALUES (?,?,?,?)",
        maquinas,
    )

    operarios = [
        ("Juan García", "mañana", "mecanizado"),
        ("María López", "mañana", "prensas"),
        ("Carlos Ruiz", "tarde", "soldadura"),
        ("Ana Martínez", "tarde", "mecanizado"),
        ("Pedro Sánchez", "noche", "inyección"),
        ("Laura Fernández", "mañana", "calidad"),
        ("Miguel Torres", "tarde", "mantenimiento"),
    ]
    cur.executemany(
        "INSERT INTO operarios (nombre, turno, especialidad) VALUES (?,?,?)",
        operarios,
    )

    ordenes = [
        ("OP-2024-001", 1, 50, 50, 2, 1, "completada", "2024-11-10", "2024-11-12"),
        ("OP-2024-002", 3, 200, 200, 1, 2, "completada", "2024-11-13", "2024-11-14"),
        ("OP-2024-003", 5, 30, 18, 7, 5, "en_curso", "2024-12-01", None),
        ("OP-2024-004", 7, 40, 40, 4, 4, "completada", "2024-12-02", "2024-12-03"),
        ("OP-2024-005", 2, 50, 0, None, None, "pendiente", None, None),
        ("OP-2024-006", 4, 500, 320, 8, 1, "en_curso", "2024-12-04", None),
        ("OP-2024-007", 6, 20, 20, 6, 3, "completada", "2024-12-05", "2024-12-06"),
        ("OP-2024-008", 8, 15, 0, None, None, "pendiente", None, None),
        ("OP-2024-009", 1, 30, 12, 2, 1, "en_curso", "2024-12-07", None),
        ("OP-2024-010", 3, 100, 100, 1, 2, "completada", "2024-12-08", "2024-12-09"),
    ]
    cur.executemany(
        """
        INSERT INTO ordenes_produccion
        (referencia, componente_id, cantidad_objetivo, cantidad_producida,
         maquina_id, operario_id, estado, fecha_inicio, fecha_fin)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        ordenes,
    )

    materiales = [
        ("Aluminio en lingotes", "kg", 1200.0, 500.0),
        ("Acero galvanizado", "kg", 3400.0, 1000.0),
        ("Granalla de acero", "kg", 80.0, 200.0),
        ("Resina ABS", "kg", 620.0, 300.0),
        ("Aceite de corte", "litros", 45.0, 100.0),
        ("Electrodos soldadura", "unidades", 850.0, 200.0),
        ("Pastillas abrasivas", "unidades", 30.0, 50.0),
        ("Fluido refrigerante", "litros", 180.0, 80.0),
    ]
    cur.executemany(
        "INSERT INTO materiales (nombre, unidad, stock_actual, stock_minimo) VALUES (?,?,?,?)",
        materiales,
    )

    movimientos = [
        (1, "entrada", 500.0, "Pedido proveedor AlumSur", "2024-12-01"),
        (2, "entrada", 1000.0, "Pedido proveedor AceroIbérico", "2024-12-02"),
        (1, "salida", 120.0, "Consumo orden OP-2024-001", "2024-12-03"),
        (4, "salida", 80.0, "Consumo orden OP-2024-003", "2024-12-04"),
        (3, "salida", 40.0, "Consumo producción Nave B", "2024-12-05"),
        (5, "salida", 30.0, "Mantenimiento fresadoras", "2024-12-06"),
        (6, "entrada", 200.0, "Pedido proveedor SoldEx", "2024-12-07"),
        (2, "salida", 250.0, "Consumo orden OP-2024-007", "2024-12-08"),
    ]
    cur.executemany(
        "INSERT INTO movimientos_almacen (material_id, tipo, cantidad, motivo, fecha) VALUES (?,?,?,?,?)",
        movimientos,
    )

    incidencias = [
        (3, "averia", "Rotura husillo principal", "abierta", "2024-12-05", None),
        (5, "revision_preventiva", "Revisión periódica 500h", "en_proceso", "2024-12-06", None),
        (2, "averia", "Fallo sensor temperatura", "resuelta", "2024-11-20", "2024-11-21"),
        (1, "revision_preventiva", "Cambio aceite hidráulico", "resuelta", "2024-11-15", "2024-11-15"),
        (4, "averia", "Vibración anormal en cabezal", "resuelta", "2024-12-01", "2024-12-03"),
        (3, "averia", "Fallo sistema refrigeración", "abierta", "2024-12-08", None),
    ]
    cur.executemany(
        """
        INSERT INTO incidencias_maquina
        (maquina_id, tipo, descripcion, estado, fecha_apertura, fecha_cierre)
        VALUES (?,?,?,?,?,?)
        """,
        incidencias,
    )

    inspecciones = [
        (1, "aprobada", None, "Laura Fernández", "2024-11-12"),
        (2, "aprobada", None, "Laura Fernández", "2024-11-14"),
        (4, "aprobada", None, "Laura Fernández", "2024-12-03"),
        (7, "rechazada", "Soldadura irregular en 3 piezas", "Laura Fernández", "2024-12-06"),
        (10, "aprobada", None, "Laura Fernández", "2024-12-09"),
    ]
    cur.executemany(
        "INSERT INTO inspecciones (orden_id, resultado, defectos_encontrados, inspector, fecha) VALUES (?,?,?,?,?)",
        inspecciones,
    )

    conn.commit()


if __name__ == "__main__":
    db_path = Path(__file__).parent / "mes.db"
    conn = get_connection(str(db_path))
    init_db(conn)
    seed_demo_data(conn)
    print(f"Base inicializada en {db_path.resolve()}")