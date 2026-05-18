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

AC_LLM_PROVIDER=openai_compatible
AC_LLM_BASE_URL=https://openrouter.ai/api/v1
AC_LLM_MODEL=minimax/minimax-m2.5
AC_LLM_API_KEY=tu_api_key
AC_LLM_TIMEOUT_SECONDS=120

### Ejemplo GitHub Models

AC_LLM_PROVIDER=github_models
AC_LLM_BASE_URL=https://models.github.ai/inference
AC_LLM_MODEL=openai/gpt-4.1
AC_LLM_API_KEY=tu_pat_con_scope_models
AC_LLM_TIMEOUT_SECONDS=120

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

## Ejemplos de pedidos en el chat

- "Quiero setup de qualy para tatuusfa1 en vallelunga, agresivo de entrada."
- "Tengo subviraje en media curva y falta traccion en salida, dame una version nueva."
- "Primero simulalo, no escribas nada."
- "Ahora aplicalo como nueva version y comparalo con el anterior."
- "Analiza mi stint y dame coaching por curva."
- "Compara mi stint base con el nuevo y optimiza sector 2."

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
- analyze_shared_memory_track
- analyze_shared_memory_corner_limits
- coach_shared_memory_corner_limits
- compare_shared_memory_stints
- list_shared_memory_sessions

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
