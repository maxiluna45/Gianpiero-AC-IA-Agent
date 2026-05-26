# Gianpiero-AC-IA-Agent

Gianpiero-AC-IA-Agent es un servidor MCP para Assetto Corsa pensado para uso real en pista.
Te permite trabajar tus setups desde lenguaje natural, con un flujo seguro (simular antes de escribir) y con soporte de telemetria para tomar mejores decisiones.

## Que te permite hacer en la practica

- Encontrar rapido un setup base por auto y circuito.
- Generar una version de qualy o carrera segun tus sintomas.
- Aplicar cambios con control total: dry run, confirmacion y versionado.
- Comparar dos setups para entender exactamente que cambio.
- Registrar sesiones para iterar con contexto real.
- Analizar limites de pista por curva y recibir coaching accionable.
- Comparar stint A vs B con delta por sector y por curva, segun objetivo.

## Para quien esta pensado

- Pilotos que quieren bajar tiempo sin editar INI a mano.
- Entrenadores o ingenieros que buscan un flujo repetible y claro.
- Equipos de liga que quieren versionar setups sin riesgo de romper el original.

## Requisitos

- Python 3.11+
- Assetto Corsa en PC (si vas a usar shared memory)

## Instalacion

1. Crear entorno virtual:

   python -m venv .venv

2. Activar entorno:

   .venv\\Scripts\\activate

3. Instalar proyecto:

   pip install -e .

## Configuracion rapida

1. Copia .env.example a .env
2. Completa proveedor, modelo y API key
3. Inicia el servidor

El servidor carga .env automaticamente al arrancar.

### Ejemplo OpenRouter (recomendado si ya lo usas)

AC_REPLAY_ROOT=C:/ruta/a/tus/replays
AC_TELEMETRY_SIMULATOR=assetto_corsa
AC_LLM_PROVIDER=openai_compatible
AC_LLM_BASE_URL=https://openrouter.ai/api/v1
AC_LLM_MODEL=minimax/minimax-m2.5
AC_LLM_API_KEY=tu_api_key
AC_LLM_TIMEOUT_SECONDS=120

### Ejemplo GitHub Models

AC_REPLAY_ROOT=C:/ruta/a/tus/replays
AC_TELEMETRY_SIMULATOR=assetto_corsa
AC_LLM_PROVIDER=github_models
AC_LLM_BASE_URL=https://models.github.ai/inference
AC_LLM_MODEL=openai/gpt-4.1
AC_LLM_API_KEY=tu_pat_con_scope_models
AC_LLM_TIMEOUT_SECONDS=120

### Telemetria multi-simulador (AC + iRacing)

- Variable nueva: `AC_TELEMETRY_SIMULATOR`
  - `assetto_corsa` (default)
  - `iracing`
- Las tools de captura aceptan `simulator` por llamada. Si no lo envias, usa `AC_TELEMETRY_SIMULATOR`.

Para iRacing instala extra opcional:

`pip install -e .[iracing]`

Requisitos para iRacing:

- iRacing abierto y conectado a sesion o replay.
- `pyirsdk` instalado.

## Arranque

Puedes iniciar de dos formas:

- python -m ac_mcp
- ac-mcp

## Flujo recomendado de uso real

Piensalo como un ciclo corto de pista:

1. Definir objetivo (qualy, carrera corta, carrera larga).
2. Describir sintomas en lenguaje normal.
3. Simular cambios con dry run.
4. Si te gusta, aplicar con confirmacion y guardar nueva version.
5. Probar en pista, registrar feedback y repetir.

## Flujo de Replay - Comparate contra pilotos en carreras

Usa replays de carreras para comparar tu conducción contra pilotos de referencia:

### Flujo Recomendado (3 pasos):

**PASO 1:** Listar drivers disponibles en un replay
```
list_replay_drivers("tatuusfa1_ks_vallelunga_180526-230307.acreplay")
→ drivers: ["#1 | Kevin Woodward", "#2 | Luis Caetano", ...]
```

**PASO 2:** Convertir un driver a formato de stint (shared memory JSON)
```
replay_to_shared_memory_json(
  replay_path="tatuusfa1_ks_vallelunga_180526-230307.acreplay",
  driver_name="#1 | Kevin Woodward"
)
→ shared_memory_json_path: "...20260519T172815Z_replay_...json"
```

**PASO 3:** Comparar replay vs tu stint grabado
```
compare_shared_memory_stints(
  base_path="...replay_json_from_paso2.json",
  candidate_path="C:/path/to/your/recorded/stint.json"
)
→ corner_deltas: [
  {corner: "Cimini 1", delta_speed_kmh: +40.4, delta_brake: -0.5, delta_gas: +0.9, ...},
  {corner: "Roma", delta_speed_kmh: -73.2, ...},
  ...
]
```

### Alternativa: One-Shot (1 paso)
```
compare_replay_vs_stint(
  replay_path="...",
  replay_driver_name="#1 | Kevin Woodward",
  stint_path="C:/path/to/your/stint.json"
)
```

### Flujo iRacing Replay (sin convertir archivos .acreplay)

Para iRacing, el flujo usa el replay abierto en el simulador via SDK:

1. `get_iracing_replay_state()` para validar estado actual.
2. `search_iracing_replay(...)` o `seek_iracing_replay_time(...)` para posicionarte.
3. `iracing_replay_to_shared_memory_json(...)` para capturar el segmento actual.
4. `compare_iracing_replay_vs_stint(...)` para compararlo contra tu stint.

Ejemplo one-shot:

```
compare_iracing_replay_vs_stint(
  stint_path="C:/path/to/your/stint.json",
  sample_count=4000,
  interval_ms=33,
  objective="lap_time"
)
```

### ⚠️ Limitaciones de Replay

- **Replay NO incluye datos de off-track** (neumáticos sobre límite)
  - `number_of_tyres_out = 0` siempre en replay
  - **Válido:** Comparar velocidad, frenada, aceleración, wheel slip por curva
  - **NO válido:** Comparar límites de pista (track-limit deltas serán engañosos)

- **Usar las comparaciones para:**
  - ✅ "En Cimini 1, Kevin va +40 km/h, ¿por qué?"
  - ✅ "En Roma, Kevin frena -73 km/h, está entrando más lento"
  - ❌ NO "Kevin se sale menos que yo en Cimini 2" (replay no trae ese dato)

## Ejemplos de pedidos en el chat

- "Quiero setup de qualy para tatuusfa1 en vallelunga, agresivo de entrada."
- "Tengo subviraje en media curva y falta traccion en salida, dame una version nueva."
- "Primero simulalo, no escribas nada."
- "Ahora aplicalo como nueva version y comparalo con el anterior."
- "Analiza mi stint y dame coaching por curva."
- "Compara mi stint base con el nuevo y optimiza sector 2."
- "Busca replays de carrera en vallelunga con tatuusfa1."
- "Extrae a Kevin del replay y comparalo con mi último stint de 27 minutos."
- "En qué curvas soy más lento que Kevin según el replay?"

## Modo seguro (muy importante)

- dry_run=true: simula, no escribe.
- confirm=true: habilita escritura real.
- save_as_new_version=true: crea v001, v002, v003... y no pisa tu base.
- create_backup=true: guarda backup cuando corresponde.

Con esto, el setup original queda protegido.

## Telemetria y coaching

Si usas shared memory de AC, puedes:

- capturar un snapshot rapido
- grabar stints
- analizar trazado por porcentaje de vuelta
- detectar exceso de limites por curva
- recibir coaching priorizado (entrada, apice, salida)
- comparar dos stints/laps (A vs B) con objetivo cuantitativo

Flujo corto sugerido:

1. Captura stint.
2. Corre analisis por curva.
3. Genera coaching.
4. Compara base vs candidato por objetivo (vuelta, sector o salida lenta).
5. Ajusta setup y vuelve a pista.

Objetivos soportados en comparacion A/B:

- lap_time (mejorar tiempo total)
- sector_1 / sector_2 / sector_3 (atacar sector puntual)
- slow_corner_exit (mejorar salida de curvas lentas)

## Funcionalidades principales

Busqueda y gestion de setups:

- list_setups
- read_setup
- find_base_setup
- compare_setups

Generacion y aplicacion de cambios:

- start_from_base
- suggest_changes
- suggest_changes_heuristic
- apply_changes

Contexto de sesion:

- record_session
- list_sessions

Shared memory:

- capture_shared_memory_snapshot
- record_shared_memory_stint
- start_shared_memory_capture
- get_shared_memory_capture_status
- stop_shared_memory_capture
- list_telemetry_simulators
- get_telemetry_simulator_capabilities
- get_iracing_replay_state
- set_iracing_replay_play_speed
- pause_iracing_replay
- search_iracing_replay
- seek_iracing_replay_frame
- seek_iracing_replay_time
- iracing_replay_to_shared_memory_json
- compare_iracing_replay_vs_stint
- read_shared_memory_session
- analyze_shared_memory_track
- analyze_shared_memory_corner_limits
- coach_shared_memory_corner_limits
- compare_shared_memory_stints
- list_shared_memory_sessions

Replays:

- list_replays
- list_replay_drivers
- parse_acreplay
- analyze_replay_corner_limits
- coach_replay_corner_limits

Referencias externas:

- search_references
- search_base_setups
- get_circuit_info
- fetch_reference

## Problemas comunes

- Error 401: API key invalida o sin permisos.
- Error 404 de modelo: revisa el identificador exacto del modelo.
- Timeout: sube AC_LLM_TIMEOUT_SECONDS a 180.
- Rate limit: cambia a otro modelo temporalmente.

## Integracion en VS Code

Si usas Copilot Chat en modo Agent:

1. Configura el servidor MCP.
2. Inicia Gianpiero-AC-IA-Agent.
3. Pide objetivos en lenguaje normal.

Archivo de ejemplo incluido en el repo:

- mcp.config.example.json

## Archivos clave del proyecto

- .env.example: plantilla de variables
- mcp.config.example.json: ejemplo de configuracion MCP
- src/ac_mcp: logica del servidor y herramientas
- tests: pruebas automaticas

## Recomendacion final

Usa siempre este orden: simular -> validar -> aplicar -> probar -> repetir.

Es la forma mas rapida de mejorar vueltas sin perder setups buenos por el camino.
