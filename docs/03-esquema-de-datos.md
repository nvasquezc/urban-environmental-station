# Esquema de datos

**Versión del esquema:** 1
**Aplica a firmware:** v0.2.x

Todo cambio incompatible incrementa `ESQUEMA_DATOS` en `config.h` y se documenta
en `CHANGELOG.md`.

## Ubicación en Firebase RTDB

```
/estaciones/<device_id>/
├── datos/<epoch_utc>     # un registro por intervalo cerrado
└── ultimo                # copia del registro más reciente
```

La clave es el epoch UTC del **fin** del intervalo. La escritura es idempotente:
reintentar nunca duplica.

Los registros generados sin sincronización horaria usan clave
`nt_<boot>_<seq>` y deben descartarse en el control de calidad.

## Campos de cabecera

| Campo | Tipo | Unidad | Descripción |
|---|---|---|---|
| `esquema` | int | — | Versión del esquema |
| `v` | string | — | Versión del firmware |
| `cal` | string | — | Identificador de campaña de calibración |
| `plat` | string | — | `esp8266` o `esp32` |
| `id` | string | — | Identificador del dispositivo |
| `boot` | int | — | Contador de arranques |
| `seq` | int | — | Secuencia dentro del arranque |
| `uptime_s` | int | s | Tiempo desde el último arranque |
| `intervalo_s` | int | s | Duración nominal del intervalo |
| `t_fin` | int \| null | s | Epoch UTC del fin del intervalo |

## Variables climáticas

Cada variable es un objeto con `prom`, `min`, `max`, `n`.

| Objeto | Unidad | Notas |
|---|---|---|
| `temp_c` | °C | Sin corrección mientras `cal == "sin-calibrar"` |
| `hr_pct` | % | Recortada a 0–100 |
| `p_hpa` | hPa | **QFE**, presión de estación |

`n` es el número de muestras válidas. Esperado con `PERIODO_CLIMA_MS = 2000`
e intervalo de 300 s: 150. Un valor menor a 120 indica pérdida de muestras y
motiva descartar el intervalo.

## Sonido (`son`)

| Campo | Unidad | Notas |
|---|---|---|
| `leq` | dB | Nivel equivalente, compuesto en energía |
| `lmax`, `lmin` | dB | Extremos entre bloques |
| `l10`, `l90` | dB | Nivel excedido el 10 % y 90 % del tiempo |
| `n` | — | Bloques acumulados. Esperado: `intervalo_s * 8` |
| `clip` | — | Bloques con saturación detectada |
| `k` | dB | Constante de calibración vigente |
| `escala` | string | `sin_ponderar_aprox` o `dBA_iec61672_aprox` |
| `trazable` | bool | **Campo crítico**, ver abajo |

> **`trazable`** distingue el frontend analógico, sin base metrológica, del
> frontend I2S, con sensibilidad declarada por el fabricante. Series con
> `trazable == false` **no deben combinarse** con series `true` en ningún
> análisis, ni compararse con estándares normativos.

## GPS (`gps`)

`fix` (bool) y, solo cuando hay fix reciente: `lat`, `lon`, `alt_m`, `sat`,
`hdop`.

No se registra velocidad ni rumbo: la estación es fija.

## Diagnóstico (`diag`)

| Campo | Notas |
|---|---|
| `rssi` | dBm, o null sin conexión |
| `heap` | Bytes libres |
| `frag` | % de fragmentación del heap, o −1 en ESP32 |
| `reset` | Causa del último arranque |
| `aht`, `bmp` | Estado de cada sensor |
| `descartados` | Registros perdidos por cola llena |
| `fallos_http` | Acumulado desde el arranque |

## Ejemplo

```json
{
  "esquema": 1,
  "v": "0.2.0",
  "cal": "sin-calibrar",
  "plat": "esp8266",
  "id": "ues-3a7f21",
  "boot": 12,
  "seq": 288,
  "uptime_s": 86400,
  "intervalo_s": 300,
  "t_fin": 1789243200,
  "temp_c": { "prom": 14.82, "min": 14.1, "max": 15.4, "n": 150 },
  "hr_pct": { "prom": 71.3, "min": 68.9, "max": 74.1, "n": 150 },
  "p_hpa":  { "prom": 752.41, "min": 752.2, "max": 752.6, "n": 150 },
  "son": {
    "leq": 58.4, "lmax": 71.2, "lmin": 49.8,
    "l10": 62.5, "l90": 51.5,
    "n": 2400, "clip": 0, "k": 40.0,
    "escala": "sin_ponderar_aprox", "trazable": false
  },
  "gps": { "fix": true, "lat": 4.6097, "lon": -74.0817,
           "alt_m": 2625.0, "sat": 9, "hdop": 1.2 },
  "diag": { "rssi": -67, "heap": 28104, "frag": 12,
            "reset": "Power on", "aht": true, "bmp": true,
            "descartados": 0, "fallos_http": 3 }
}
```

## Reglas de compatibilidad

- Agregar campos opcionales **no** incrementa `esquema`.
- Cambiar unidad, tipo o semántica de un campo existente **sí** lo incrementa.
- Renombrar un campo equivale a eliminar y agregar: incrementa.
- La capa de análisis debe rechazar registros con `esquema` desconocido, nunca
  intentar interpretarlos.
