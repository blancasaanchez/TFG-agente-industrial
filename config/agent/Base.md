# Base.md

## Rol del documento

Este archivo es la **fuente funcional de verdad** del agente industrial.

Su función es describir:
- el dominio de negocio;
- el vocabulario del operario;
- las reglas funcionales del sistema;
- las operaciones permitidas;
- los criterios de aclaración;
- ejemplos de interpretación y escritura.

Este documento **no es el esquema técnico de la base de datos**. La estructura exacta de tablas, campos, relaciones y tipos se define en `Schema.md`.

---

## Objetivo del sistema

Permitir que un operario consulte y, en versiones controladas, registre, actualice o elimine información de un MES industrial mediante lenguaje natural en español.

El sistema debe:
- interpretar preguntas de forma robusta;
- producir una estructura intermedia segura;
- pedir aclaración cuando la petición sea ambigua;
- impedir SQL libre generado directamente por el modelo;
- mantener trazabilidad de las acciones realizadas.

---

## Principios de funcionamiento

1. El modelo de lenguaje **no accede directamente a la base de datos**.
2. El modelo de lenguaje **no genera SQL final como fuente de verdad**.
3. La interpretación del lenguaje y la construcción técnica de SQL están separadas.
4. La semántica del dominio debe vivir preferentemente en documentación (`Base.md`) y no crecer indefinidamente en el backend.
5. La estructura real de la base de datos se valida contra `Schema.md`.
6. Las consultas ambiguas deben resolverse con `pedir_aclaracion`, no con suposiciones fuertes.
7. Las operaciones de escritura deben ser más restrictivas que las de lectura.

---

## Entidades funcionales

Las entidades de trabajo del sistema son:
- `maquina`
- `material`
- `orden`
- `operario`
- `componente`
- `incidencia`
- `inspeccion`
- `movimiento`

Estas son entidades lógicas. Su implementación técnica exacta se define en `Schema.md`.

---

## Operaciones permitidas

### `consultar`
Operación principal.

Permite:
- recuperar registros filtrados;
- consultar una entidad concreta por identificador;
- devolver campos concretos;
- realizar conteos;
- realizar agrupaciones, ordenaciones y métricas cuando la estructura lo soporte.

### `registrar`
Inserta un nuevo registro.

Condiciones:
- solo en entidades permitidas;
- solo con campos escribibles;
- validación obligatoria de tipos y valores mínimos;
- si faltan campos obligatorios, debe pedirse aclaración;
- antes de ejecutar la escritura, debe existir confirmación del usuario.

### `actualizar`
Modifica registros existentes.

Condiciones:
- requiere identificar al menos un registro objetivo mediante `entity_value` o filtros claros;
- solo permite campos escribibles;
- debe ser trazable;
- antes de ejecutar la escritura, debe existir confirmación del usuario.

### `eliminar`
Operación muy restringida.

Condiciones:
- no debe estar activa por defecto;
- requiere un objetivo claramente identificado;
- en producción debería priorizarse el borrado lógico frente al borrado físico.

### `pedir_aclaracion`
Se usa cuando no hay suficiente información para ejecutar una acción segura.

---

## Política de interpretación

### Intención
Cada petición debe clasificarse en una de las operaciones permitidas.

### Entidad principal
Siempre que sea posible, la petición debe resolverse sobre una única entidad principal.

### Filtros
La variabilidad de las preguntas debe expresarse mediante filtros reutilizables y no mediante intents específicos por caso. Los operadores deben devolverse en formato canónico: `=`, `!=`, `>`, `>=`, `<`, `<=`, `contains`. No usar `is`, `eq`, `neq`, `gt`, `gte`, `lt`, `lte`.

### Campos solicitados
Si el operario pide información concreta como quién, dónde, cuánto, estado, motivo o fecha, el sistema debe poblar `requested_fields`.

### Aclaración
Si no se puede determinar con seguridad la entidad, el alcance o la acción, debe emitirse `pedir_aclaracion`.

---

## Reglas de agregación

Expresiones como:
- `por nave`
- `por tipo`
- `por estado`
- `por turno`
- `por unidad`

implican funcionalmente:
- `aggregation`, normalmente `count` si el usuario pregunta `cuántas` o `cuántos`;
- `group_by` sobre el campo correspondiente;
- `aggregation_field` debe ser `"id"` cuando la agregación es `count`.

Si el usuario pregunta `qué nave tiene más...`, `qué tipo tiene más...` o `cuál tiene menos...`, debe producirse además ordenación por la métrica agregada y, si procede, `limit=1`.

### Ejemplos JSON de agregación

Usuario: "¿Cuántas máquinas hay por nave?"
```json
{
  "intent": "consultar",
  "area": "produccion",
  "entity_type": "maquina",
  "aggregation": "count",
  "aggregation_field": "id",
  "group_by": ["ubicacion"],
  "sort": [{"field": "ubicacion", "direction": "asc"}]
}
```

Usuario: "¿Cuántas máquinas averiadas hay por nave?"
```json
{
  "intent": "consultar",
  "area": "produccion",
  "entity_type": "maquina",
  "filters": [{"field": "estado", "operator": "=", "value": "averiada"}],
  "aggregation": "count",
  "aggregation_field": "id",
  "group_by": ["ubicacion"]
}
```

Usuario: "¿Cuántas órdenes hay por estado?"
```json
{
  "intent": "consultar",
  "area": "produccion",
  "entity_type": "orden",
  "aggregation": "count",
  "aggregation_field": "id",
  "group_by": ["estado"]
}
```

Usuario: "¿Cuántas incidencias hay por tipo?"
```json
{
  "intent": "consultar",
  "area": "mantenimiento",
  "entity_type": "incidencia",
  "aggregation": "count",
  "aggregation_field": "id",
  "group_by": ["tipo"]
}
```

Usuario: "¿Qué nave tiene más máquinas operativas?"
```json
{
  "intent": "consultar",
  "area": "produccion",
  "entity_type": "maquina",
  "filters": [{"field": "estado", "operator": "=", "value": "operativa"}],
  "aggregation": "count",
  "aggregation_field": "id",
  "group_by": ["ubicacion"],
  "sort": [{"field": "__metric__", "direction": "desc"}],
  "limit": 1
}
```

Regla general de ranking — singular vs. plural: cuando la pregunta pide un ranking (por `aggregation`+`group_by` o por `derived_metric`) y está en **singular** ("qué nave tiene más...", "qué orden está más...", "cuál es la máquina que..."), el usuario espera un único ganador: añade siempre `"limit": 1` junto al `sort`. Cuando está en **plural** ("qué naves tienen más...", "qué órdenes están más..."), el usuario espera el ranking completo: usa `sort` sin `limit`. Esta regla se aplica igual con `derived_metric` que con `aggregation`+`group_by` — ver los dos ejemplos de `diferencia_objetivo_producido` más abajo, uno en plural y otro en singular.

Usuario: "¿Cuántas máquinas hay en total?"
```json
{
  "intent": "consultar",
  "area": "produccion",
  "entity_type": "maquina",
  "aggregation": "count",
  "aggregation_field": "id"
}
```

Usuario: "¿Qué órdenes tienen mayor diferencia entre objetivo y producido?"
```json
{
  "intent": "consultar",
  "area": "produccion",
  "entity_type": "orden",
  "derived_metric": "diferencia_objetivo_producido",
  "sort": [{"field": "__metric__", "direction": "desc"}]
}
```

Usuario: "¿Qué órdenes están más lejos de completarse?"
```json
{
  "intent": "consultar",
  "area": "produccion",
  "entity_type": "orden",
  "derived_metric": "diferencia_objetivo_producido",
  "sort": [{"field": "__metric__", "direction": "desc"}]
}
```

Usuario: "¿Qué orden está más lejos de completarse?" (singular → un único resultado, ver regla de ranking singular/plural más arriba)
```json
{
  "intent": "consultar",
  "area": "produccion",
  "entity_type": "orden",
  "derived_metric": "diferencia_objetivo_producido",
  "sort": [{"field": "__metric__", "direction": "desc"}],
  "limit": 1
}
```

IMPORTANTE: cuando el usuario pregunte por la diferencia, distancia, desvío o brecha entre `cantidad_objetivo` y `cantidad_producida` en órdenes, usa siempre `derived_metric: "diferencia_objetivo_producido"`. Nunca uses `aggregation` con `aggregation_field: "diferencia"` porque "diferencia" no es un campo real de la base de datos.

---

## Reglas de conteo de valores distintos (`count_distinct`)

Hay dos preguntas que suenan parecidas pero son semánticamente distintas y **no deben confundirse**:

1. **"¿Cuántas máquinas hay por nave?"** → el usuario quiere un desglose: cuántas máquinas hay *en cada* nave. Esto es `aggregation: "count"` + `group_by: ["ubicacion"]`. Devuelve varias filas, una por nave.
2. **"¿Cuántas naves existen?" / "¿Cuántas naves hay en total?" / "¿Cuántas ubicaciones hay?"** → el usuario quiere un único número: cuántos valores *distintos* de nave existen. Esto es `aggregation: "count_distinct"` sobre el campo `ubicacion`, **sin `group_by`**. Devuelve una sola fila con un total.

Regla de desambiguación: si la pregunta pide contar cuántos valores distintos existen de una dimensión (nave, tipo, estado, unidad...) y **no** pide un desglose de otra entidad "por" esa dimensión, usa `count_distinct` y nunca `group_by`. La palabra clave suele ser "existen", "hay en total", "distintas", "diferentes" aplicada directamente sobre la propia dimensión — no sobre otra entidad contada "por" esa dimensión.

Mapeo funcional:
- `¿Cuántas naves existen?` / `¿Cuántas ubicaciones hay?` → `entity_type: "maquina"`, `aggregation: "count_distinct"`, `aggregation_field: "ubicacion"`.
- `¿Cuántos tipos de máquina hay?` / `¿Cuántos tipos de máquinas distintos hay?` → `entity_type: "maquina"`, `aggregation: "count_distinct"`, `aggregation_field: "tipo"`.
- `¿Cuántos estados de orden hay?` / `¿Cuántos estados distintos puede tener una orden?` → `entity_type: "orden"`, `aggregation: "count_distinct"`, `aggregation_field: "estado"`.
- `¿Cuántas unidades de medida se usan?` → `entity_type: "material"`, `aggregation: "count_distinct"`, `aggregation_field: "unidad"`.

### Ejemplos JSON

Usuario: `¿Cuántas naves existen?`
```json
{
  "intent": "consultar",
  "area": "produccion",
  "entity_type": "maquina",
  "aggregation": "count_distinct",
  "aggregation_field": "ubicacion"
}
```

Usuario: `¿Cuántos tipos de máquina hay?`
```json
{
  "intent": "consultar",
  "area": "produccion",
  "entity_type": "maquina",
  "aggregation": "count_distinct",
  "aggregation_field": "tipo"
}
```

Usuario: `¿Cuántos estados de orden hay?`
```json
{
  "intent": "consultar",
  "area": "produccion",
  "entity_type": "orden",
  "aggregation": "count_distinct",
  "aggregation_field": "estado"
}
```

Contraste, para que quede claro que NO es lo mismo — Usuario: `¿Cuántas máquinas hay por nave?`
```json
{
  "intent": "consultar",
  "area": "produccion",
  "entity_type": "maquina",
  "aggregation": "count",
  "aggregation_field": "id",
  "group_by": ["ubicacion"]
}
```

---

## Reglas de conversación

1. Si el turno actual es una continuación elíptica clara (frase corta, sin entidad ni alcance propios, que depende gramaticalmente del turno anterior — p. ej. "y las averiadas", "y en nave B"), el sistema puede heredar entidad y filtros del contexto reciente.
2. **Si el turno actual es una pregunta completa y autocontenida (tiene su propia entidad y alcance explícitos), debe tratarse como independiente: no debe heredar filtros, aggregation, group_by ni derived_metric del turno anterior**, aunque haya contexto conversacional disponible. Esta es la regla por defecto: ante la duda de si un turno es continuación o pregunta nueva, trátalo como pregunta nueva. Es preferible perder una continuación válida que arrastrar una agregación o un filtro obsoleto a una pregunta que no los pedía.
3. `aggregation`, `group_by` y `derived_metric` **nunca se heredan implícitamente**, ni siquiera en una continuación elíptica válida, salvo que el turno actual repita explícitamente una palabra de cómputo (cuántos, cuántas, total, media, promedio, suma, máximo, mínimo, distintos, distintas). Una continuación elíptica que solo cambia un filtro (p. ej. "y las averiadas" tras "qué máquinas están operativas") sigue siendo un listado, no un agregado — aunque el turno original sí lo fuera.
4. Si el nuevo turno cambia el valor de un mismo campo de filtro, el filtro nuevo sustituye al anterior.
5. Si el nuevo turno añade un campo de filtro distinto, se acumula sobre los heredados.
6. **Si hay una aclaración pendiente (`pedir_aclaracion`) y el turno actual responde a ella — con una palabra suelta, con una de las opciones ofrecidas, o repitiendo parte de la pregunta original —, debe RESOLVERSE: construye el `ParsedRequest` completo con `intent`, `entity_type` y el resto de campos ya determinados, `needs_clarification: false` y `clarification_question: null`. Nunca repitas la misma `clarification_question` si el turno actual ya contiene la respuesta**, aunque sea escueta ("consultar", "registrar máquinas", "la primera"). Repetir la pregunta solo está justificado si el turno actual sigue sin decir nada que la responda.

Ejemplos:
- `qué máquinas están averiadas` → `y cuáles operativas` (continúa; hereda entidad, sustituye filtro de estado; sigue siendo listado)
- `qué máquinas están en nave B` → `y las averiadas` (continúa; acumula filtro de estado sobre el de nave; sigue siendo listado)
- `qué materiales están en kg` → `y con stock mínimo mayor a 100` (continúa; acumula filtro)
- `¿cuántas máquinas hay?` → `¿qué máquinas hay?` (NO continúa: la segunda es una pregunta completa con su propia entidad y alcance — debe ignorar el `aggregation: count` del turno anterior y devolver un listado, no un total)
- `¿cuántas naves existen?` → `¿qué máquinas hay en nave A?` (NO continúa: pregunta completa nueva; no hereda `count_distinct` ni ningún filtro)

Resolución de aclaración pendiente — ejemplo completo:

Usuario: `Máquina` (entidad sola, sin acción: ambiguo)
```json
{
  "intent": "pedir_aclaracion",
  "area": "produccion",
  "entity_type": "maquina",
  "needs_clarification": true,
  "clarification_question": "¿Qué acción deseas realizar con la máquina? ¿Consultar, registrar, actualizar o eliminar información?"
}
```

Usuario (con esa aclaración pendiente en el contexto): `Consultar` — o igualmente `Consultar máquinas`
```json
{
  "intent": "consultar",
  "area": "produccion",
  "entity_type": "maquina",
  "needs_clarification": false,
  "clarification_question": null
}
```

Este patrón es general: aplica igual si la aclaración pendiente era sobre `orden`, `material`, `incidencia` o cualquier otra entidad — en cuanto el turno actual nombra una de las acciones ofrecidas (consultar/registrar/actualizar/eliminar) o responde de cualquier otra forma inequívoca a lo que se preguntó, se resuelve; no se vuelve a preguntar.

---

## Vocabulario del operario y equivalencias funcionales

### Ubicación
Términos habituales:
- nave
- ubicación
- ubicacion

Canonicalización funcional esperada:
- `A` o `nave A` → `Nave A`
- `B` o `nave B` → `Nave B`
- `C` o `nave C` → `Nave C`

### Estado de máquina
Variantes aceptables:
- operativa
- operativo
- funcionando
- activa
- averiada
- averiado
- rota
- roto
- estropeada
- estropeado
- fallida
- fallido
- en mantenimiento
- mantenimiento
- en revisión
- en revision

Valores canónicos:
- `operativa`
- `averiada`
- `en_mantenimiento`

### Estado de orden
Variantes aceptables:
- completada
- completado
- terminada
- finalizada
- en curso
- activa
- pendiente

Valores canónicos:
- `completada`
- `en_curso`
- `pendiente`

### Tipo de movimiento
Variantes aceptables:
- entrada
- entradas
- por entrada
- de entrada
- salida
- salidas
- por salida
- de salida

Valores canónicos:
- `entrada`
- `salida`

### Tipos de máquina
El operario puede usar términos parciales como:
- torno
- fresadora
- prensa
- soldadora
- inyectora
- rectificadora
- taladro

Regla:
- los tipos de máquina deben resolverse como búsqueda parcial (`contains`), no igualdad exacta.

---

## Reglas de negocio funcionales

1. Cuando el usuario pregunte por máquinas en una nave, debe resolverse sobre la ubicación canónica.
2. Cuando el usuario pregunte por tipos de máquina con términos parciales, se debe usar búsqueda parcial.
3. Cuando el usuario pregunte por una orden concreta, la resolución debe hacerse por referencia.
4. Si el usuario pregunta quién trabaja en una orden o en qué máquina está una orden, la entidad principal sigue siendo normalmente `orden`.
5. Si el usuario habla de materiales `movidos`, `entradas` o `salidas`, la entidad principal funcional debe ser `movimiento`.
6. Las comparaciones textuales deben ser insensibles a mayúsculas y acentos.
7. Las comparaciones numéricas deben tratarse como numéricas.
8. Las reglas de negocio del dominio deben intentarse resolver antes de llegar al constructor SQL.

---

## Reglas específicas para operaciones de escritura

### Política general de escritura

Las operaciones `registrar` y `actualizar` deben cumplir estas reglas:

1. Nunca se debe ejecutar una escritura si faltan datos obligatorios.
2. Nunca se debe escribir sobre campos que no sean escribibles para la entidad.
3. En `registrar`, los valores nuevos deben devolverse en `write_values`.
4. En `actualizar`, además de `write_values`, debe existir una forma clara de identificar el registro objetivo mediante:
   - `entity_value`, o
   - filtros suficientemente concretos.
5. Si no hay suficiente información para registrar o actualizar con seguridad, el sistema debe usar `pedir_aclaracion`.
6. Antes de ejecutar una escritura, el sistema debe mostrar un resumen de la operación y pedir confirmación al operario.
7. En producción, `eliminar` debe seguir siendo la operación más restringida y preferiblemente sustituirse por borrado lógico.

### Entidades razonables para registrar

Son buenas candidatas para `registrar`:
- `operario`
- `material`
- `componente`
- `incidencia`
- `inspeccion`
- `maquina`

También puede registrarse:
- `movimiento`
- `orden`

pero estas entidades suelen requerir mayor cuidado por los identificadores, relaciones o validaciones funcionales.

### Entidades razonables para actualizar

Son buenas candidatas para `actualizar`:
- `maquina`
- `orden`
- `material`
- `operario`
- `componente`
- `incidencia`
- `inspeccion`
- `movimiento`

### Ejemplos esperados de registrar

Usuario: "Registra un operario llamado Luis Pérez, turno tarde y especialidad mantenimiento"
Respuesta esperada:
{
  "intent": "registrar",
  "area": "produccion",
  "entity_type": "operario",
  "write_values": {
    "nombre": "Luis Pérez",
    "turno": "tarde",
    "especialidad": "mantenimiento"
  }
}

Usuario: "Registra una máquina llamada Taladro T-03, tipo taladro CNC, estado operativa y ubicación Nave C"
Respuesta esperada:
{
  "intent": "registrar",
  "area": "produccion",
  "entity_type": "maquina",
  "write_values": {
    "nombre": "Taladro T-03",
    "tipo": "taladro CNC",
    "estado": "operativa",
    "ubicacion": "Nave C"
  }
}

Usuario: "Registra un material llamado Cobre laminado, unidad kg, stock_actual 250 y stock_minimo 80"
Respuesta esperada:
{
  "intent": "registrar",
  "area": "almacen",
  "entity_type": "material",
  "write_values": {
    "nombre": "Cobre laminado",
    "unidad": "kg",
    "stock_actual": 250,
    "stock_minimo": 80
  }
}

### Ejemplos esperados de actualizar

Usuario: "Actualiza la máquina Torno T-01 y cambia su estado a averiada"
Respuesta esperada:
{
  "intent": "actualizar",
  "area": "mantenimiento",
  "entity_type": "maquina",
  "filters": [
    {"field": "nombre", "operator": "=", "value": "Torno T-01"}
  ],
  "write_values": {
    "estado": "averiada"
  }
}

Usuario: "Actualiza la orden OP-2024-006 y pon cantidad_producida a 350"
Respuesta esperada:
{
  "intent": "actualizar",
  "area": "produccion",
  "entity_type": "orden",
  "entity_value": "OP-2024-006",
  "write_values": {
    "cantidad_producida": 350
  }
}

Usuario: "Actualiza el material Aceite de corte y pon stock_actual a 60"
Respuesta esperada:
{
  "intent": "actualizar",
  "area": "almacen",
  "entity_type": "material",
  "filters": [
    {"field": "nombre", "operator": "=", "value": "Aceite de corte"}
  ],
  "write_values": {
    "stock_actual": 60
  }
}

Usuario: "Actualiza la orden OP-2024-006 y pon operario_id a María López"
Respuesta esperada:
{
  "intent": "actualizar",
  "area": "produccion",
  "entity_type": "orden",
  "entity_value": "OP-2024-006",
  "write_values": {
    "operario_id": "María López"
  }
}



### Resolución de claves foráneas en escritura

Si un campo escribible termina en `_id` y la especificación técnica de `Schema.md` declara `fk_lookup`,
el agente puede devolver en `write_values` una referencia humana en vez del identificador numérico exacto.

Ejemplos válidos:
- `orden_id: "OP-2024-006"`
- `operario_id: "María López"`
- `maquina_id: "Torno T-01"`
- `material_id: "Aceite de corte"`

En esos casos, el backend resolverá la referencia textual al id real antes de ejecutar la escritura.

### Restricción para actualizaciones potencialmente ambiguas

En entidades donde puede haber varios registros asociados a la misma referencia funcional, el sistema no debe
actualizar directamente si no puede identificar un registro concreto.

Casos típicos:
- `movimiento`: no debe actualizarse solo con `material_nombre`
- `inspeccion`: no debe actualizarse solo con `referencia` de orden

En esos casos, el sistema debe usar `pedir_aclaracion` y solicitar al menos:
- `id`, o
- información adicional suficiente para distinguir el registro correcto.

### Casos que deben pedir aclaración en escritura

- `Registra una orden nueva` → faltan datos obligatorios
- `Actualiza la máquina` → no identifica cuál
- `Cambia el estado a averiada` → no identifica entidad ni registro
- `Registra una incidencia` → falta al menos la máquina o información mínima útil
- `Actualiza la inspección de la orden OP-2024-006 y pon resultado rechazada` → puede haber varias inspecciones para esa orden; debe pedir más detalle
- `Actualiza el movimiento del material Aceite de corte y pon cantidad a 50` → puede haber varios movimientos para ese material; debe pedir más detalle

---

## Casos que deben pedir aclaración

Ejemplos:
- `qué hay en la nave A`
- `muéstrame lo pendiente`
- `qué está activo`
- `dime cuál va peor`

Regla:
- si la entidad no se puede inferir con seguridad razonable, no se debe ejecutar consulta directa.

---

## Ejemplos de consultas esperadas

### Máquinas
- ¿Qué máquinas están averiadas?
- ¿Qué máquinas están en nave B?
- ¿Qué tornos hay?
- ¿Qué fresadoras están averiadas?
- ¿Qué máquinas operativas hay en nave A?
- ¿Cuántas máquinas averiadas hay por nave?

### Materiales
- ¿Qué materiales están en kg?
- ¿Qué materiales tienen stock mínimo superior a 100?
- ¿Qué materiales tienen stock actual menor a 100?
- ¿Qué materiales están por debajo del stock mínimo?

IMPORTANTE: `material` no tiene campo `descripcion`. Cuando el operario busque un material
por nombre parcial (ej. "aluminio en lingotes", "aceite de corte"), usa un único filtro
`nombre contains "<término completo>"`. No dividas el término en varios filtros.

Ejemplo:
Usuario: "Qué materiales se llaman aluminio en lingotes"
```json
{
  "intent": "consultar",
  "area": "almacen",
  "entity_type": "material",
  "filters": [{"field": "nombre", "operator": "contains", "value": "aluminio en lingotes"}]
}
```

### Órdenes
- ¿Qué órdenes están en curso?
- Muéstrame la orden OP-2024-006
- ¿Quién está trabajando en la orden OP-2024-006?
- ¿Qué órdenes están asignadas a tornos?
- ¿Qué órdenes no tienen máquina asignada?

### Operarios
- ¿Qué operarios están en turno de mañana?
- ¿Qué operarios tienen especialidad de mecanizado?

### Componentes
- ¿Qué componentes hay de categoría motor?

### Incidencias
- ¿Qué incidencias siguen abiertas?
- ¿Qué incidencias tienen máquinas averiadas?

### Inspecciones
- ¿Qué inspecciones fueron rechazadas?

### Movimientos
- ¿Qué materiales se han movido por salida?
- ¿Qué movimientos de entrada hay?

---

## Qué NO debe hacer el sistema

- No debe inventar tablas ni columnas.
- No debe ejecutar operaciones de escritura si faltan datos obligatorios.
- No debe responder consultas ambiguas con seguridad falsa.
- No debe usar `Acciones.md` como fuente principal de conocimiento en tiempo de ejecución.
- No debe trasladar indefinidamente reglas de negocio nuevas al backend técnico si esas reglas pueden consolidarse en `Base.md`.