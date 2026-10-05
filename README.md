# Agente de IA para sistemas MES por voz

Prototipo de un agente de inteligencia artificial que permite a un operario de
fábrica consultar y modificar la información de un sistema MES (Manufacturing
Execution System) hablando en castellano, desde una interfaz web pensada para
el móvil.

Trabajo de Fin de Grado del Grado en Ingeniería Informática, Escuela Superior
de Ingeniería de la Universidad de Cádiz.

---

## Cómo funciona

El modelo de lenguaje **no genera SQL ni accede a la base de datos**. Su única
tarea es interpretar la petición del operario y devolver una estructura
intermedia validada, con la intención, la entidad y los filtros. A partir de
ahí, una capa determinista escrita en código construye la consulta y la
ejecuta.

El conocimiento del dominio no está programado, sino escrito en dos documentos
que se cargan al arrancar la aplicación:

- **`Base.md`** — la parte funcional: qué entidades existen, qué operaciones se
  pueden hacer, cómo llama el operario a cada cosa y las reglas para
  interpretar una petición.
- **`Schema.md`** — la parte técnica: las ocho tablas, sus campos y tipos, qué
  se puede consultar, qué se puede modificar y cómo se presenta cada resultado.

Gracias a eso, ampliar el dominio o cambiar la forma en que se interpreta una
petición se hace editando estos documentos, sin tocar el código.

---

## Requisitos

- Python 3.14.5 (se ha desarrollado y probado con esta versión)
- Una clave de API de [Mistral AI](https://mistral.ai/), dentro de su nivel gratuito
- Una clave de API de [Deepgram](https://deepgram.com/) para la transcripción de voz

Las instrucciones siguientes son para **Windows con PowerShell**. En la memoria
del proyecto, el Anexo A las recoge con más detalle.

---

## Instalación

### 1. Entorno virtual

Desde la raíz del proyecto:

```powershell
py -m venv venv
venv\Scripts\activate
```

Si PowerShell impide la ejecución del script de activación, hay que habilitarla
una única vez:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 2. Dependencias

```powershell
pip install -r requirements.txt
```

### 3. Variables de entorno

En `config/config/` hay un fichero `.env` con las variables necesarias y los
valores de las claves vacíos. Rellénalo con tus propias claves:

```
# API del LLM
MISTRAL_API_KEY=<clave API>
MISTRAL_MODEL=mistral-small-latest

# Selección de backend STT
STT_PROVIDER=deepgram

# Deepgram
DEEPGRAM_API_KEY=<clave API>
DEEPGRAM_STT_MODEL=nova-3
DEEPGRAM_STT_LANGUAGE=es
```

El modelo de lenguaje se elige con `MISTRAL_MODEL`, así que puede sustituirse
por otro de la misma API sin tocar el código. Para usar la transcripción local
en lugar de Deepgram, se cambia `STT_PROVIDER` a `faster-whisper`.

### 4. Bases de datos

El sistema usa dos bases de datos SQLite independientes:

- **`db.sqlite3`** — gestionada por Django. Guarda los usuarios, las sesiones y
  los permisos de la aplicación web. **No se incluye en el repositorio**, hay
  que crearla.
- **`agent/mes.db`** — contiene los datos simulados del sistema MES. Sí está
  incluida, ya poblada con datos de demostración.

Para crear la de Django, desde la carpeta `config` (la que contiene
`manage.py`):

```powershell
py manage.py migrate
py manage.py createsuperuser
```

El segundo comando crea la primera cuenta con acceso al panel de administración
(`/admin`).

### 5. Roles y usuarios

Desde el panel de administración hay que crear primero **tres grupos**, que son
los roles del sistema:

```
administrador
supervisor
operario
```

Escritos exactamente así, **en minúsculas y sin tildes**, porque el sistema usa
esos nombres para identificar el rol del usuario.

Después se crean los usuarios y se asigna a cada uno su grupo.

Cada rol puede modificar cosas distintas:

- **Operario** — órdenes, incidencias, inspecciones y movimientos de almacén.
  No puede modificar operarios, máquinas, componentes ni materiales, ni
  registrar una orden a nombre de otro operario.
- **Supervisor** — todo lo anterior, salvo máquinas, componentes y materiales.
- **Administrador** — sin restricciones.

Las operaciones de eliminación están desactivadas para todos los roles.

### 6. Restablecer los datos de demostración

Para dejar el escenario simulado como estaba al principio, se borra
`agent/mes.db` y se vuelve a ejecutar, desde la carpeta `config`:

```powershell
py -m agent.db_setup
```

Esto no afecta a los usuarios ni a las sesiones de Django, que están en un
fichero distinto.

---

## Arranque

Desde la carpeta `config`:

```powershell
py manage.py runserver
```

La aplicación queda en `http://127.0.0.1:8000`.

### Acceso desde un móvil

Para probarlo en un dispositivo real hay que arrancar el servidor escuchando en
todas las interfaces:

```powershell
py manage.py runserver 0.0.0.0:8000
```

Y, en una segunda terminal, exponerlo con [ngrok](https://ngrok.com/):

```powershell
ngrok http 8000
```

Ngrok devuelve una URL temporal que puede abrirse desde el navegador del móvil.

La interfaz se ha desarrollado y validado para **Android**. En iOS se detectaron
problemas de representación conocidos del motor WebKit.

---

## Consultas de ejemplo

La aplicación incluye una página de ejemplos accesible desde la barra superior.
Algunas de las consultas que admite:

```
¿Qué máquinas están averiadas?
¿Qué fresadoras hay en la nave A?
¿Qué materiales tienen menos de 100 kg de stock?
¿Qué órdenes no tienen máquina asignada?
¿Cuántas máquinas hay por nave?
¿Qué operario lleva más órdenes?
Registra un operario llamado Luis García, turno tarde y especialidad mantenimiento
Pon cantidad 50 en el material Aceite de corte
```

También admite continuaciones de la conversación. Después de preguntar
«¿qué máquinas están averiadas?», se puede preguntar simplemente
«¿y cuáles operativas?».

---

## Estructura del proyecto

```
config/
├── manage.py
├── agent/              Núcleo del agente
│   ├── Base.md         Conocimiento funcional del dominio
│   ├── Schema.md       Especificación técnica de las tablas
│   ├── query_builder.py    Construcción determinista del SQL
│   ├── db_setup.py         Creación y poblado de la base MES
│   ├── stt.py              Transcripción de voz a texto
│   └── mes.db              Datos simulados del sistema MES
├── config/
│   ├── settings.py
│   └── .env            Variables de entorno (sin claves)
└── chat/               Aplicación web: vistas, plantillas y estáticos
```

---

## Licencia

Este proyecto se distribuye bajo la **Licencia Pública General de GNU versión
3.0 (GPL-3.0)**. El texto completo está en el fichero `LICENSE`.
