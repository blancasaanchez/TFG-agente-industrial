# Schema.md

## Propósito

Este documento es la **fuente técnica de verdad** del sistema.

Su objetivo es describir el esquema de la base de datos del MES simulado, las relaciones entre entidades, los campos disponibles y los campos válidos para filtrado, selección, agrupación y ordenación.

Este documento debe ser usado por la capa de construcción de consultas para validar cualquier estructura intermedia producida por el agente.

---

## Base de datos

- Motor actual: `SQLite`
- Base simulada: `mes.db`
- Dominio: fábrica de componentes de automóvil

La base contiene ocho tablas principales:

1. `componentes`
2. `maquinas`
3. `operarios`
4. `ordenes_produccion`
5. `materiales`
6. `movimientos_almacen`
7. `incidencias_maquina`
8. `inspecciones`

---

## Convenciones de validación

1. Toda entidad lógica debe mapearse a tablas y campos reales.
2. Un filtro solo es válido si el campo existe en la entidad lógica correspondiente.
3. Los campos derivados o expuestos por joins deben declararse explícitamente.
4. Los filtros textuales deben permitir comparación insensible a acentos y mayúsculas.
5. Los filtros numéricos deben tratarse como números.
6. Los filtros con valor nulo deben transformarse en `IS NULL` o `IS NOT NULL`.
7. Para operaciones de escritura, los filtros deben usar columnas reales de la tabla escribible.
8. Los campos derivados por join pueden leerse, pero no siempre sirven como filtro directo en `UPDATE` o `DELETE`.
9. Cuando un campo sea seguro para escritura o filtrado en operaciones de escritura, debe declarar `write_expr`.

---

## Alias globales

Estos alias se usan para normalizar nombres de campo provenientes del agente.
El código los carga en tiempo de inicialización desde este bloque YAML.

```yaml
type: global_config
aliases:
  ubicación: ubicacion
  ubicacion: ubicacion
  nave: ubicacion
  stock mínimo: stock_minimo
  stock minimo: stock_minimo
  stock: stock_actual
  maquina.tipo: maquina_tipo
  maquina.estado: maquina_estado
  maquina.nombre: maquina_nombre
  tipo_movimiento: tipo
  unidad_medida: unidad
  unidades: unidad
  medida: unidad
  orden: referencia
  componente: componente_nombre
  operario: operario_nombre
  material: material_nombre
```

Etiquetas legibles para totales de `count_distinct`, usadas por la capa de presentación de resultados (`entidad.campo: etiqueta en plural`):

```yaml
type: global_config
distinct_labels:
  maquina.ubicacion: naves
  maquina.tipo: tipos de máquina
  maquina.estado: estados de máquina
  orden.estado: estados de orden
  material.unidad: unidades de medida
  movimiento.tipo: tipos de movimiento
```

---

# 1. Tabla `componentes`

## Descripción
Catálogo de componentes fabricados.

## Spec técnica
```yaml
entity: componente
plural_name: componentes
summary_title: Componentes encontrados
from_sql: "componentes c"
identifier_field: nombre
display_order: "c.nombre"
writable_table: componentes
writable_fields: [nombre, descripcion, categoria]
default_select: [nombre, descripcion, categoria]
default_aggregation_field: id
display_template: "{nombre} — {categoria} | {descripcion}"
fields:
  id:          { expr: "c.id",          write_expr: "id",          kind: number }
  nombre:      { expr: "c.nombre",      write_expr: "nombre",      kind: text   }
  descripcion: { expr: "c.descripcion", write_expr: "descripcion", kind: text   }
  categoria:   { expr: "c.categoria",   write_expr: "categoria",   kind: text   }
```

---

# 2. Tabla `maquinas`

## Descripción
Máquinas disponibles en planta.

## Reglas especiales
- `tipo` debe soportar búsqueda parcial (`contains`).
- `ubicacion` debe aceptar canonicalización funcional (`A` → `Nave A`, etc.).
- `estado` debe aceptar canonicalización léxica (`rota` → `averiada`, `en revisión` → `en_mantenimiento`, etc.).

## Spec técnica
```yaml
entity: maquina
plural_name: máquinas
summary_title: Máquinas encontradas
from_sql: "maquinas m"
identifier_field: nombre
display_order: "m.nombre"
writable_table: maquinas
writable_fields: [nombre, tipo, estado, ubicacion]
default_select: [nombre, tipo, estado, ubicacion]
default_aggregation_field: id
display_template: "{nombre} ({tipo}) — {ubicacion} [{estado}]"
fields:
  id:        { expr: "m.id",        write_expr: "id",        kind: number }
  nombre:    { expr: "m.nombre",    write_expr: "nombre",    kind: text   }
  tipo:      { expr: "m.tipo",      write_expr: "tipo",      kind: text   }
  estado:    { expr: "m.estado",    write_expr: "estado",    kind: text   }
  ubicacion: { expr: "m.ubicacion", write_expr: "ubicacion", kind: text   }
```

---

# 3. Tabla `operarios`

## Descripción
Operarios disponibles en el sistema.

## Spec técnica
```yaml
entity: operario
plural_name: operarios
summary_title: Operarios encontrados
from_sql: "operarios op"
identifier_field: nombre
display_order: "op.nombre"
writable_table: operarios
writable_fields: [nombre, turno, especialidad]
default_select: [nombre, turno, especialidad]
default_aggregation_field: id
display_template: "{nombre} — turno {turno} | {especialidad}"
fields:
  id:           { expr: "op.id",           write_expr: "id",           kind: number }
  nombre:       { expr: "op.nombre",       write_expr: "nombre",       kind: text   }
  turno:        { expr: "op.turno",        write_expr: "turno",        kind: text   }
  especialidad: { expr: "op.especialidad", write_expr: "especialidad", kind: text   }
```

---

# 4. Tabla `ordenes_produccion`

## Descripción
Órdenes de producción del sistema MES.

## Reglas especiales
- si se filtra por máquina asignada nula, usar `maquina_id IS NULL`;
- si se filtra por operario asignado nulo, usar `operario_id IS NULL`;
- `maquina_tipo` admite `contains` porque puede venir expresado como `torno`, `fresadora`, etc.;
- el identificador funcional principal es `referencia`.

## Spec técnica
```yaml
entity: orden
plural_name: órdenes
summary_title: Órdenes encontradas
from_sql: >
  ordenes_produccion o
  JOIN componentes c ON o.componente_id = c.id
  LEFT JOIN maquinas m ON o.maquina_id = m.id
  LEFT JOIN operarios op ON o.operario_id = op.id
identifier_field: referencia
display_order: "o.referencia"
writable_table: ordenes_produccion
writable_fields: [referencia, componente_id, cantidad_objetivo, cantidad_producida,
                  maquina_id, operario_id, estado, fecha_inicio, fecha_fin]
default_select: [referencia, componente_nombre, estado, cantidad_producida,
                 cantidad_objetivo, maquina_nombre, operario_nombre]
default_aggregation_field: id
display_template: "{referencia} — {componente_nombre} [{estado}] {cantidad_producida}/{cantidad_objetivo} | Máquina: {maquina_nombre} | Operario: {operario_nombre}"
fields:
  id:                 { expr: "o.id",                  write_expr: "id",                 kind: number }
  referencia:         { expr: "o.referencia",          write_expr: "referencia",         kind: text   }
  estado:             { expr: "o.estado",              write_expr: "estado",             kind: text   }
  cantidad_producida: { expr: "o.cantidad_producida",  write_expr: "cantidad_producida", kind: number }
  cantidad_objetivo:  { expr: "o.cantidad_objetivo",   write_expr: "cantidad_objetivo",  kind: number }
  fecha_inicio:       { expr: "o.fecha_inicio",        write_expr: "fecha_inicio",       kind: date   }
  fecha_fin:          { expr: "o.fecha_fin",           write_expr: "fecha_fin",          kind: date   }
  maquina_id:         { expr: "o.maquina_id",          write_expr: "maquina_id",         kind: number, fk_lookup: "maquinas.nombre" }
  operario_id:        { expr: "o.operario_id",         write_expr: "operario_id",        kind: number, fk_lookup: "operarios.nombre" }
  componente_id:      { expr: "o.componente_id",       write_expr: "componente_id",      kind: number, fk_lookup: "componentes.nombre" }
  componente_nombre:  { expr: "c.nombre",   kind: text, write_via_fk: "componente_id->componentes.nombre"   }
  maquina_nombre:     { expr: "m.nombre",   kind: text, write_via_fk: "maquina_id->maquinas.nombre"         }
  maquina_tipo:       { expr: "m.tipo",     kind: text, write_via_fk: "maquina_id->maquinas.tipo"           }
  maquina_estado:     { expr: "m.estado",   kind: text, write_via_fk: "maquina_id->maquinas.estado"         }
  operario_nombre:    { expr: "op.nombre",  kind: text, write_via_fk: "operario_id->operarios.nombre"       }
```

---

# 5. Tabla `materiales`

## Descripción
Catálogo de materiales y stocks actuales.

## Reglas especiales
- `unidad` acepta equivalencias como `unidad_medida`, `unidades`, `medida`.
- `stock_actual` y `stock_minimo` son numéricos.

## Spec técnica
```yaml
entity: material
plural_name: materiales
summary_title: Materiales encontrados
from_sql: "materiales mat"
identifier_field: nombre
display_order: "mat.nombre"
writable_table: materiales
writable_fields: [nombre, unidad, stock_actual, stock_minimo]
default_select: [nombre, unidad, stock_actual, stock_minimo]
default_aggregation_field: id
display_template: "{nombre}: {stock_actual} {unidad} (mínimo {stock_minimo})"
fields:
  id:           { expr: "mat.id",           write_expr: "id",           kind: number }
  nombre:       { expr: "mat.nombre",       write_expr: "nombre",       kind: text   }
  unidad:       { expr: "mat.unidad",       write_expr: "unidad",       kind: text   }
  stock_actual: { expr: "mat.stock_actual", write_expr: "stock_actual", kind: number }
  stock_minimo: { expr: "mat.stock_minimo", write_expr: "stock_minimo", kind: number }
```

---

# 6. Tabla `movimientos_almacen`

## Descripción
Movimientos de entrada y salida de materiales.

## Reglas especiales
- si el operario habla de materiales "movidos", "entradas" o "salidas", la entidad funcional debe ser `movimiento`;
- `tipo` debe resolverse a `entrada` o `salida`.

## Spec técnica
```yaml
entity: movimiento
plural_name: movimientos
summary_title: Movimientos encontrados
from_sql: "movimientos_almacen mv JOIN materiales mat ON mv.material_id = mat.id"
identifier_field: id
display_order: "mv.fecha DESC"
writable_table: movimientos_almacen
writable_fields: [material_id, tipo, cantidad, motivo, fecha]
default_select: [material_nombre, tipo, cantidad, motivo, fecha]
default_aggregation_field: id
display_template: "{material_nombre} — {tipo} {cantidad} | {motivo} | {fecha}"
fields:
  id:              { expr: "mv.id",          write_expr: "id",          kind: number }
  tipo:            { expr: "mv.tipo",        write_expr: "tipo",        kind: text   }
  cantidad:        { expr: "mv.cantidad",    write_expr: "cantidad",    kind: number }
  motivo:          { expr: "mv.motivo",      write_expr: "motivo",      kind: text   }
  fecha:           { expr: "mv.fecha",       write_expr: "fecha",       kind: date   }
  material_id:     { expr: "mv.material_id", write_expr: "material_id", kind: number, fk_lookup: "materiales.nombre" }
  material_nombre: { expr: "mat.nombre", kind: text, write_via_fk: "material_id->materiales.nombre" }
  unidad:          { expr: "mat.unidad", kind: text, write_via_fk: "material_id->materiales.unidad"  }
```

---

# 7. Tabla `incidencias_maquina`

## Descripción
Incidencias y revisiones asociadas a máquinas.

## Spec técnica
```yaml
entity: incidencia
plural_name: incidencias
summary_title: Incidencias encontradas
from_sql: "incidencias_maquina i JOIN maquinas m ON i.maquina_id = m.id"
identifier_field: id
display_order: "i.fecha_apertura DESC"
writable_table: incidencias_maquina
writable_fields: [maquina_id, tipo, descripcion, estado, fecha_apertura, fecha_cierre]
default_select: [maquina_nombre, tipo, descripcion, estado, fecha_apertura, fecha_cierre]
default_aggregation_field: id
display_template: "{maquina_nombre} — {tipo} [{estado}] | {descripcion} | apertura: {fecha_apertura}"
fields:
  id:             { expr: "i.id",             write_expr: "id",             kind: number }
  tipo:           { expr: "i.tipo",           write_expr: "tipo",           kind: text   }
  descripcion:    { expr: "i.descripcion",    write_expr: "descripcion",    kind: text   }
  estado:         { expr: "i.estado",         write_expr: "estado",         kind: text   }
  fecha_apertura: { expr: "i.fecha_apertura", write_expr: "fecha_apertura", kind: date   }
  fecha_cierre:   { expr: "i.fecha_cierre",   write_expr: "fecha_cierre",   kind: date   }
  maquina_id:     { expr: "i.maquina_id",     write_expr: "maquina_id",     kind: number, fk_lookup: "maquinas.nombre" }
  maquina_nombre: { expr: "m.nombre", kind: text, write_via_fk: "maquina_id->maquinas.nombre" }
  maquina_estado: { expr: "m.estado", kind: text, write_via_fk: "maquina_id->maquinas.estado" }
  maquina_tipo:   { expr: "m.tipo",   kind: text, write_via_fk: "maquina_id->maquinas.tipo"   }
  nombre:         { expr: "m.nombre", kind: text, write_via_fk: "maquina_id->maquinas.nombre" }
```

---

# 8. Tabla `inspecciones`

## Descripción
Inspecciones de calidad asociadas a órdenes.

## Spec técnica
```yaml
entity: inspeccion
plural_name: inspecciones
summary_title: Inspecciones encontradas
from_sql: "inspecciones ins JOIN ordenes_produccion o ON ins.orden_id = o.id"
identifier_field: referencia
display_order: "ins.fecha DESC"
writable_table: inspecciones
writable_fields: [orden_id, resultado, defectos_encontrados, inspector, fecha]
default_select: [referencia, resultado, defectos_encontrados, inspector, fecha]
default_aggregation_field: id
display_template: "{referencia} — {resultado} | inspector: {inspector} | defectos: {defectos_encontrados} | fecha: {fecha}"
fields:
  id:                   { expr: "ins.id",                   write_expr: "id",                   kind: number }
  resultado:            { expr: "ins.resultado",            write_expr: "resultado",            kind: text   }
  estado:               { expr: "ins.resultado",            write_expr: "resultado",            kind: text   }
  defectos_encontrados: { expr: "ins.defectos_encontrados", write_expr: "defectos_encontrados", kind: text }
  inspector:            { expr: "ins.inspector",            write_expr: "inspector",            kind: text   }
  fecha:                { expr: "ins.fecha",                write_expr: "fecha",                kind: date   }
  orden_id:             { expr: "ins.orden_id",             write_expr: "orden_id",             kind: number, fk_lookup: "ordenes_produccion.referencia" }
  referencia:           { expr: "o.referencia", kind: text, write_via_fk: "orden_id->ordenes_produccion.referencia" }
```

---

## Relaciones principales

- `ordenes_produccion.componente_id` → `componentes.id`
- `ordenes_produccion.maquina_id` → `maquinas.id`
- `ordenes_produccion.operario_id` → `operarios.id`
- `movimientos_almacen.material_id` → `materiales.id`
- `incidencias_maquina.maquina_id` → `maquinas.id`
- `inspecciones.orden_id` → `ordenes_produccion.id`

---

## Campos válidos para `requested_fields`

### `maquina`
- `nombre`
- `tipo`
- `estado`
- `ubicacion`

### `material`
- `nombre`
- `unidad`
- `stock_actual`
- `stock_minimo`

### `orden`
- `referencia`
- `estado`
- `cantidad_producida`
- `cantidad_objetivo`
- `fecha_inicio`
- `fecha_fin`
- `componente_nombre`
- `maquina_nombre`
- `maquina_tipo`
- `operario_nombre`

### `operario`
- `nombre`
- `turno`
- `especialidad`

### `componente`
- `nombre`
- `descripcion`
- `categoria`

### `movimiento`
- `material_nombre`
- `tipo`
- `cantidad`
- `motivo`
- `fecha`
- `unidad`

### `incidencia`
- `maquina_nombre`
- `maquina_tipo`
- `tipo`
- `descripcion`
- `estado`
- `fecha_apertura`
- `fecha_cierre`
- `maquina_estado`

### `inspeccion`
- `referencia`
- `resultado`
- `defectos_encontrados`
- `inspector`
- `fecha`

---

## Agregaciones permitidas

- `count`
- `count_distinct`
- `sum`
- `avg`
- `max`
- `min`

`count_distinct` siempre debe ir sin `group_by`: cuenta cuántos valores distintos existen de `aggregation_field`, no un desglose por grupo.

## Campos razonables para agregación
- `stock_actual`
- `stock_minimo`
- `cantidad`
- `cantidad_producida`
- `cantidad_objetivo`

## Campos razonables para `group_by`
- `ubicacion`
- `estado`
- `tipo`
- `turno`
- `unidad`
- `resultado`

---

## Reglas para construcción SQL segura

1. Nunca usar campos no declarados en este documento.
2. Toda consulta debe validarse contra la entidad lógica correspondiente.
3. Toda consulta con joins debe usar únicamente relaciones declaradas aquí.
4. Los filtros nulos deben traducirse a `IS NULL` / `IS NOT NULL`.
5. Las búsquedas parciales deben usar `contains` y terminar en `LIKE` seguro o equivalente controlado.
6. El sistema debe poder reconstruir qué entidad lógica, qué campos y qué filtros se usaron.
7. En operaciones de escritura, las condiciones del `WHERE` deben usar `write_expr` si existe; si un campo no declara `write_expr`, debe considerarse no apto para filtrar directamente en `UPDATE` o `DELETE`.

---

## Correspondencia recomendada entre documentos

- `Base.md` responde a: qué significa el dominio y cómo habla el operario.
- `Schema.md` responde a: qué existe realmente en la base de datos y cómo se puede consultar o escribir con seguridad.
- `Acciones.md`, si existe, responde a: qué interacciones o casos reales se han producido.