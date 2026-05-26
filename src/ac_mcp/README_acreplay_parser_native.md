# Parser Nativo de Replays (.acreplay)

Este documento describe el parser en Python implementado en este repositorio para archivos de replay de Assetto Corsa.

Objetivo principal:
- Parsear .acreplay en Windows sin depender de un binario C++ externo.
- Exportar CSVs por piloto con nombres de archivo compatibles con Windows.

Archivo principal:
- `src/ac_mcp/acreplay_parser_native.py`


## Estado actual

El parser actual soporta el flujo base de replays v16:

1. Lee el header principal del replay:
- version
- recording interval
- weather
- track y track config
- numero de coches y numero de frames

2. Recorre cada coche (driver) y lee sus frames base.

3. Exporta un CSV por piloto con:
- posicion y rotacion
- velocidad y dinamica de ruedas
- slip/load/dirt por rueda
- steer angle, drivetrain speed, rpm
- tiempos de vuelta y vuelta actual
- fuel, gear, gas, brake, boost
- damage basico
- bits utiles del campo status (luces, bocina, direccion de camara, estado de caja)

4. Sanitiza nombres para archivos en Windows:
- reemplaza caracteres invalidos (`<>:"/\\|?*`)
- evita errores por nombres como `01|Nombre:Piloto`


## Lo que se puede ampliar (opcional)

En el parser C++ original existe soporte para bloques CSP `EXT_PERCAR` (v6/v7) comprimidos.

Eso permite agregar columnas extra por frame, principalmente:
- clutch
- handbrake
- wipers
- turnSignals
- lowBeams
- flags adicionales (`extraOptionA` a `extraOptionJ`)

Si tu enfoque es setup/lap time clasico, esto suele ser opcional.
Si tu enfoque es analisis fino de inputs del piloto, puede aportar valor.


## Resumen tecnico de la extension EXT_PERCAR

Implementar esta extension requiere tres pasos:

1. Detectar y ubicar bloque CSP en el archivo:
- buscar el postfix `__AC_SHADERS_PATCH_v1__` al final del replay
- leer offset y version del bloque

2. Encontrar el tag de datos por coche:
- recorrer tags hasta hallar `EXT_PERCAR_v{n}:{carIndex}`
- validar version soportada (v6/v7 recomendadas)

3. Leer, descomprimir y mapear frames:
- leer `compressedSize`
- descomprimir con zlib
- interpretar frame extra por cada frame del coche
- anexar esas columnas al CSV base


## Estructura recomendada para implementarlo

Mantener el parser en capas para no romper lo actual:

1. Capa base (ya implementada):
- lectura de header
- lectura de coches
- parse de `CarFrame` base

2. Capa CSP (nueva):
- `get_csp_data_offset(stream) -> int | None`
- `find_ext_percar_chunk(stream, csp_offset, car_index) -> (version, compressed_blob) | None`
- `decode_ext_percar(version, blob, frame_count) -> list[dict]`

3. Capa de salida:
- merge por indice de frame: base + extra
- header CSV dinamico (con y sin extras)


## Estrategia de implementacion sugerida

Para minimizar riesgo:

1. Implementar primero deteccion de bloque CSP sin escribir columnas nuevas.
2. Agregar decoder solo para v7.
3. Agregar luego v6 (si los datos reales lo requieren).
4. Validar con tests sinteticos y, despues, con replays reales.


## Tests recomendados para la extension

1. Replay sin CSP:
- debe exportar CSV base sin fallar.

2. Replay con CSP y version soportada:
- debe exportar columnas extra y mantener mismo numero de frames.

3. Replay con CSP no soportado:
- debe seguir exportando base y loggear aviso (sin romper).

4. Nombres de piloto con caracteres invalidos:
- debe seguir creando archivos validos en Windows.


## Uso rapido actual

Ejemplo CLI:

```bash
python -m ac_mcp.acreplay_parser_native "ruta/al/replay.acreplay"
python -m ac_mcp.acreplay_parser_native "ruta/al/replay.acreplay" --driver-name "Nombre exacto"
python -m ac_mcp.acreplay_parser_native "ruta/al/replay.acreplay" --output "salida/"
```


## Decision recomendada hoy

Si no usas clutch manual y no necesitas esos estados adicionales para coaching avanzado,
mantener solo el parser base es una decision razonable por costo/beneficio.

Cuando quieras subir nivel de analisis de inputs, este README ya deja la guia para extenderlo a EXT_PERCAR.