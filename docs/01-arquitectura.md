# Arquitectura del sistema

**Versión del documento:** 1.0
**Aplica a:** firmware v0.2.x, análisis v0.2.x

---

## 1. Propósito de este documento

Describe la cadena de medición completa y justifica cada decisión de diseño que
la condiciona. Una arquitectura sin justificación es una colección de
preferencias; lo que sigue documenta qué alternativas se descartaron y por qué,
de modo que las decisiones sean auditables y revisables ante nueva evidencia.

## 2. Principio rector

El sistema está diseñado bajo una premisa que gobierna todo lo demás:

> **El dato crudo es irrecuperable; la interpretación siempre puede rehacerse.**

De ahí se derivan tres reglas que atraviesan firmware, transporte y análisis:

1. El firmware **mide y agrega**. No interpreta, no corrige, no evalúa
   cumplimiento normativo.
2. Cada registro transporta **su propio contexto**: versión de esquema, versión
   de firmware, estado de calibración, diagnóstico del nodo y número de muestras
   que lo sustentan.
3. Toda transformación con pérdida ocurre **aguas abajo** y es reproducible a
   partir de lo almacenado.

## 3. Cadena de medición

```
┌───────────────────────────────────────────────────────────┐
│  NODO EMBEBIDO                                            │
│                                                           │
│  Sensores            Adquisición         Agregación       │
│  ┌─────────┐         ┌──────────┐        ┌─────────────┐  │
│  │ AHT20   │──I2C──▶ │ cada 2 s │───────▶│ intervalo   │  │
│  │ BMP280  │         │          │        │ de 300 s    │  │
│  └─────────┘         └──────────┘        │ alineado    │  │
│  ┌─────────┐         ┌──────────┐        │ al reloj    │  │
│  │ sonido  │──ADC/──▶│ cada     │───────▶│             │  │
│  │         │  I2S    │ 125 ms   │        │ prom/min/   │  │
│  └─────────┘         └──────────┘        │ max/n       │  │
│  ┌─────────┐         ┌──────────┐        │ Leq (energía)│ │
│  │ GPS     │──UART──▶│ NMEA     │───────▶│ diagnóstico │  │
│  └─────────┘         └──────────┘        └──────┬──────┘  │
│                                                 │         │
│  Reloj: NTP (primario) / GPS (respaldo)         ▼         │
│                                          ┌─────────────┐  │
│                                          │ cola        │  │
│                                          │ LittleFS    │  │
│                                          │ (JSONL)     │  │
│                                          └──────┬──────┘  │
└─────────────────────────────────────────────────┼─────────┘
                                                  │ HTTPS
                                                  ▼
                                        ┌───────────────────┐
                                        │ Firebase RTDB     │
                                        │ /estaciones/<id>/ │
                                        │   datos/<epoch>   │
                                        └─────────┬─────────┘
                                                  │
                    ┌─────────────────────────────┴──────────┐
                    ▼                                        ▼
         ┌─────────────────────┐                  ┌────────────────────┐
         │ ingest.py           │                  │ Apps Script        │
         │ → data/bronze/*.pq  │                  │ → Google Sheets    │
         └──────────┬──────────┘                  │ (inspección)       │
                    │                             └────────────────────┘
                    ▼
         ┌─────────────────────┐
         │ qc.py               │  7 criterios de rechazo
         │ → data/silver/      │  atribución de causa
         └──────────┬──────────┘
                    ▼
         ┌─────────────────────┐
         │ aggregate.py        │  horario / diario
         │ estratificación     │  ley de varianza total
         └──────────┬──────────┘
                    ▼
         ┌─────────────────────┐      ┌──────────────────┐
         │ calibration.py      │◀─────│ reference.py     │
         │ → data/gold/        │      │ red de referencia│
         └──────────┬──────────┘      └──────────────────┘
                    ▼
         ┌─────────────────────┐
         │ viz.py → docs/figuras/
         └─────────────────────┘
```

## 4. Decisiones de diseño

### 4.1 Agregación en el nodo, no en el servidor

**Decisión.** El firmware muestrea a 0.5 Hz y transmite un resumen cada 300 s con
promedio, mínimo, máximo y número de muestras.

**Alternativa descartada.** Transmitir cada muestra cruda.

**Justificación.** Muestrear a 0.5 Hz y transmitir todo generaría ~43 000
registros diarios por nodo, dos órdenes de magnitud más tráfico, con dependencia
crítica de la conectividad: sin red, se pierde todo. La agregación local
preserva la información estadísticamente relevante (tendencia central y
dispersión) a un costo de transmisión que permite operar con enlaces
intermitentes.

**Costo asumido.** La forma exacta de la distribución dentro del intervalo se
pierde. Se mitiga reportando extremos y conteo, lo que permite estimar la
varianza intra-intervalo aguas abajo (ver `aggregate._var_desde_rango`).

### 4.2 Intervalos alineados al reloj

**Decisión.** Los intervalos se cierran en múltiplos exactos de 300 s desde el
epoch UTC, no cada 300 s desde el arranque.

**Justificación.** Permite que nodos independientes produzcan intervalos
directamente comparables sin interpolación, y que la agregación horaria sea
exacta (12 intervalos por hora). La comparación entre nodos es el objeto central
del estudio de deriva (protocolo §7.3); cualquier desalineación introduciría un
sesgo temporal que se confundiría con diferencia instrumental.

**Costo asumido.** El primer intervalo tras cada arranque es parcial. Se
identifica mediante `seq == 1` y se descarta en control de calidad.

### 4.3 Clave de escritura idempotente

**Decisión.** La clave de cada registro es el epoch UTC del fin del intervalo.

**Alternativa descartada.** Claves autogeneradas por el servidor (`push`).

**Justificación.** Reintentar una escritura fallida no puede producir
duplicados. Con claves autogeneradas, un fallo de red tras una escritura exitosa
pero antes de recibir la confirmación produciría un registro duplicado
indistinguible de un dato legítimo.

### 4.4 Cola persistente con reenvío diferido

**Decisión.** Cada intervalo cerrado se escribe primero en LittleFS; el envío
ocurre después, en orden FIFO, con hasta tres registros por ciclo.

**Justificación.** Desacopla medición de conectividad. Una caída de red de
varios días no produce pérdida de datos, solo retraso en su disponibilidad. Con
una partición de 2 MB, la capacidad de la cola supera los ocho días de
operación autónoma.

**Protección.** Cuando el sistema de archivos supera el 85 % de ocupación, los
registros nuevos se descartan y se contabilizan en `diag.descartados`. Se prefiere
perder datos recientes de forma **declarada** antes que corromper el sistema de
archivos.

### 4.5 Reloj: NTP primario, GPS de respaldo

**Decisión.** El reloj interno se sincroniza por NTP; el GPS actúa como respaldo
cuando no hay red.

**Justificación.** NTP ofrece mejor exactitud y no depende de visibilidad
satelital. El GPS resulta inviable en instalaciones interiores y consume 40–50 mA
de forma continua. Un intervalo cerrado sin sincronización recibe clave
`nt_<boot>_<seq>` y se descarta en control de calidad: **es preferible un dato
ausente a uno mal fechado**.

### 4.6 Abstracción del frontend de sonido

**Decisión.** La adquisición de nivel sonoro se define mediante una interfaz
(`SoundSensor`) con dos implementaciones: analógica y digital I2S.

**Justificación.** El transductor analógico disponible carece de ponderación
frecuencial y de sensibilidad declarada. La migración a un micrófono MEMS con
base metrológica es inevitable, y la abstracción la reduce a un cambio de
directiva de compilación. Cada implementación declara su propia trazabilidad en
el campo `son.trazable`, que viaja en cada registro.

**Consecuencia analítica.** Series con `trazable == false` y `true` **no se
combinan**. La separación está codificada en el esquema de datos, no delegada a
la memoria del analista.

### 4.7 Composición energética del nivel sonoro

**Decisión.** Los niveles sonoros se componen como
`Leq = 10·log10(Σ 10^(Lᵢ/10) / n)`, tanto en firmware como en análisis.

**Justificación.** El decibelio es una escala logarítmica de razón de potencias.
Su promedio aritmético subestima sistemáticamente la contribución de eventos
intensos, que son precisamente los que determinan el nivel equivalente. Para
niveles de 50, 50, 50 y 80 dB, el promedio aritmético da 57.5 dB y la
composición energética 74.0 dB: una diferencia de 16.5 dB, suficiente para
invertir un juicio de cumplimiento normativo.

Este error es frecuente en implementaciones de sensores de bajo costo. La
verificación está codificada como prueba (`test_supera_la_media_aritmetica`).

### 4.8 Propagación de la dispersión en la agregación

**Decisión.** La desviación estándar horaria se obtiene por la ley de varianza
total, combinando dispersión intra e inter-intervalo.

**Justificación.** Doce intervalos con idéntico promedio pero rango interno no
nulo producirían, bajo un cálculo ingenuo sobre los promedios, una desviación
estándar de cero. Eso declararía una precisión inexistente y subestimaría la
incertidumbre expandida del resultado final.

**Limitación declarada.** El firmware no reporta desviación estándar por
intervalo, solo extremos. La varianza intra se estima desde el rango asumiendo
normalidad aproximada (factor d₂ ≈ 5.3 para n ≈ 150). La aproximación sesga
hacia arriba ante valores atípicos, por lo que el resultado es **conservador**:
nunca subestima la incertidumbre.

### 4.9 Control de calidad con atribución excluyente

**Decisión.** Los siete criterios de rechazo se evalúan en orden fijo; cada
registro descartado se atribuye a la **primera** causa que aplica.

**Justificación.** Garantiza que el resumen de descartes sea una partición del
conjunto rechazado: la suma de causas iguala el total. Sin esa propiedad, un
registro con dos defectos se contaría dos veces y el informe de calidad
exageraría la tasa de fallo. La propiedad está verificada por prueba
(`test_causas_suman_el_total`).

### 4.10 Separación entre descartes y huecos

**Decisión.** Los registros rechazados y los intervalos ausentes se reportan por
separado.

**Justificación.** Un intervalo descartado existió y falló un criterio; un hueco
nunca se generó. Fundirlos en una sola cifra de completitud ocultaría caídas del
nodo detrás de una métrica de calidad del dato.

### 4.11 Firebase RTDB como almacenamiento de prototipo

**Decisión.** Firebase Realtime Database para la fase de prototipo.

**Justificación.** Cliente HTTPS ligero compatible con ESP8266, sin
infraestructura que administrar, con nivel gratuito suficiente para la escala
actual (≈ 200 kB diarios por nodo frente a 1 GB disponibles).

**Limitación reconocida.** No es una base de datos de series temporales. A
escala de decenas de nodos, el costo por lectura y la ausencia de consultas de
rango eficientes la vuelven inadecuada. La migración prevista es a
TimescaleDB o InfluxDB con transporte MQTT. El esquema de datos versionado
(`docs/03-esquema-de-datos.md`) hace que esa migración no afecte al firmware.

### 4.12 Arquitectura medallion en el análisis

**Decisión.** Tres capas: `bronze` (crudo), `silver` (validado), `gold`
(publicable).

**Justificación.** La capa bronze es inmutable y reproducible desde el origen;
silver contiene el resultado del control de calidad; gold, los productos
citables. Cualquier revisión metodológica se aplica reprocesando desde bronze
sin volver a campo. Solo la capa gold se versiona en el repositorio: bronze y
silver se regeneran.

## 5. Modelo de fallos

| Fallo | Detección | Respuesta del sistema |
|---|---|---|
| Sensor I2C no responde | `aht.getEvent()` devuelve falso | `diag.aht = false`, reintento cada 60 s, intervalo descartado en QC |
| Pérdida de conectividad | `WiFi.status()` | Cola persistente; reconexión forzada tras 5 min |
| Sistema de archivos lleno | `LittleFS.info()` > 85 % | Descarte declarado en `diag.descartados` |
| Reloj no sincronizado | `time(nullptr)` < umbral | Clave `nt_*`; descarte en QC |
| Reinicio inesperado | `boot` incrementa, `diag.reset` | Intervalo parcial descartado; causa auditable |
| Saturación del canal de sonido | `son.clip > 0` | Registrado, no corregido |
| Degradación de memoria | `diag.heap` en cada registro | Detectable por regresión (`diagnostico_estabilidad`) |

Ningún fallo detiene la adquisición. El sistema degrada su cobertura antes que
su integridad.

## 6. Restricciones de plataforma

| | ESP8266 D1 mini | ESP32-S3 |
|---|---|---|
| RAM total | 80 kB | 320 kB |
| RAM utilizada | 38.8 kB (47.4 %) | 54.4 kB (16.6 %) |
| Margen tras handshake TLS | ≈ 6.6 kB | ≈ 250 kB |
| UART para GPS | SoftwareSerial | Hardware |
| Frontend de sonido | Analógico (ADC 10 bit) | I2S 24 bit |
| Ponderación A en firmware | Inviable | Implementada |

El margen de memoria del ESP8266 tras el establecimiento de la conexión TLS es
el factor limitante y la razón principal de la migración prevista a ESP32-S3.

## 7. Trazabilidad de versiones

Cada registro transporta los identificadores necesarios para reconstruir las
condiciones de su generación:

| Campo | Permite determinar |
|---|---|
| `esquema` | Interpretación válida de la estructura |
| `v` | Versión de firmware y, por tanto, algoritmos aplicados |
| `cal` | Campaña de calibración cuyos coeficientes se aplicaron |
| `plat` | Plataforma de hardware |
| `son.escala`, `son.trazable` | Base metrológica del canal acústico |
| `boot`, `seq` | Posición dentro de la sesión de operación |

Esta información viaja **con el dato**, no en una tabla de metadatos externa.
Un registro extraído de su contexto sigue siendo interpretable.

## 8. Documentos relacionados

- [`02-protocolo-calibracion.md`](02-protocolo-calibracion.md) — procedimiento experimental
- [`03-esquema-de-datos.md`](03-esquema-de-datos.md) — contrato del registro
- [`06-limitaciones-conocidas.md`](06-limitaciones-conocidas.md) — restricciones vigentes
