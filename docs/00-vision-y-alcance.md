# Visión y alcance

**Proyecto:** Urban Environmental Station
**Autor:** Néstor Oswaldo Vásquez Castro · ORCID 0009-0003-6483-790X
**DOI:** 10.5281/zenodo.22740968
**Estado:** v0.2.0 — prototipo en operación, sin calibrar

---

## 1. El problema

Bogotá opera del orden de veinte estaciones de referencia para una ciudad de
casi ocho millones de habitantes. La densidad espacial resultante no permite
estudiar la variabilidad ambiental a escala de barrio, que es precisamente la
escala donde se toman decisiones de planeación urbana.

Los sensores de bajo costo pueden cerrar esa brecha. La dificultad no es
técnica sino metrológica: **sin caracterización de incertidumbre, un dato de
bajo costo no es comparable con nada**, ni con la red de referencia ni con
otros nodos de la misma red.

La literatura del área suele resolver esto mediante co-ubicación puntual: se
calibra una vez contra una referencia y se despliega. Ese procedimiento no
escala. Una red de doscientos nodos no puede rotar por una estación de
referencia cada seis meses, y la deriva de los sensores no se detiene porque
resulte inconveniente medirla.

## 2. Pregunta de investigación

> ¿Es posible estimar la deriva de sensores ambientales de bajo costo a partir
> de los residuales entre nodos vecinos, sin recalibración física periódica?

La hipótesis: bajo el supuesto de que nodos próximos observan el mismo proceso
ambiental más un sesgo propio de variación lenta, la componente de baja
frecuencia de los residuales entre pares estima la diferencia de derivas. Con
tres o más nodos y una restricción de anclaje, el sistema es identificable.

Esta línea continúa un trabajo sostenido sobre estimación de parámetros
lentamente variables a partir de residuales de observadores en sistemas
embebidos con recursos limitados.

## 3. Qué existe hoy

### Sistema en operación

Un nodo instrumentado con ESP8266, sensores de temperatura, humedad relativa
y presión barométrica, en operación continua desde el 15 de septiembre de 2026.

| Indicador | Valor |
|---|---|
| Registros válidos | 2 293 de 2 301 (99.7 %) |
| Completitud | 99.7 % |
| Reinicios espontáneos | 0 |
| Deriva de memoria | sin degradación apreciable |

### Cadena de análisis

Firmware que agrega intervalos alineados al reloj, control de calidad con siete
criterios de rechazo y atribución excluyente de causa, agregación temporal con
propagación de varianza, descomposición armónica, contraste de tendencia y
capa predictiva con validación fuera de muestra. **132 pruebas automatizadas.**

### Hallazgos

**Redundancia de muestreo.** El residual se decorrelaciona en 475 minutos
frente a un intervalo de muestreo de 5. El sistema opera con un sobremuestreo
de factor 95, lo que acota empíricamente la cadencia de transmisión mínima y
abre margen para reducir el consumo energético sin pérdida de información.

**Grados de libertad efectivos.** Con autocorrelación de primer orden ρ = 0.996,
las 2 305 observaciones equivalen a unas 12 independientes. Tratar series de
sensores densamente muestreadas como observaciones independientes —práctica
frecuente en la literatura del área— sobreestima la significancia estadística
en aproximadamente un orden de magnitud.

**Rechazo de una hipótesis propia.** El ajuste global detectó una pendiente de
+0.27 °C/día, estadísticamente significativa incluso tras corregir por
autocorrelación. El contraste por bloques la rechazó: las pendientes locales
resultaron heterogéneas (CV = 1.93), señal de variabilidad meteorológica antes
que de deriva sistemática. **El sistema no reportó un resultado positivo
disponible porque los datos no lo sostenían.**

**Límites de la capa predictiva.** El pronóstico a 24 h alcanza una destreza de
+0.20 sobre la referencia climatológica, con cobertura del 62 % frente al 95 %
nominal. El sistema declara ambas limitaciones y las traduce en recomendaciones
concretas, en lugar de presentar el modelo como suficiente.

## 4. Alcance declarado

### Dentro

- Caracterización de incertidumbre y deriva en sensores de bajo costo.
- Metodología de control de calidad y agregación reproducible.
- Estimación de deriva relativa entre nodos sin referencia trazable.
- Instrumentación, firmware y cadena de análisis de código abierto.

### Fuera

- Sustituir la red de referencia oficial.
- Declaraciones de cumplimiento normativo.
- Pronóstico meteorológico.
- Medición de nivel sonoro con trazabilidad, mientras no se incorpore un
  transductor con sensibilidad declarada.

## 5. Lo que bloquea el avance

| Necesidad | Estado | Consecuencia si no se resuelve |
|---|---|---|
| Referencia trazable para co-ubicación | pendiente | La incertidumbre permanece indeterminada |
| Tres o más nodos simultáneos | 1 de 3 | Sin dispersión entre unidades no hay Fase 0 |
| Campañas separadas por meses | pendiente | Sin deriva medida no hay contraste de la hipótesis |
| Sonómetro clase 1 o 2 | pendiente | El canal acústico no admite calibración |

El primero y el cuarto son los que un grupo de investigación con
infraestructura resuelve de inmediato.

## 6. Qué aporta y qué requiere una colaboración

**Aporta:** instrumentación propia en operación, firmware y cadena de análisis
verificados, protocolo experimental documentado con criterios de aceptación
cuantitativos y prueba de falsación declarada, y tres productos con DOI
registrados en 2026.

**Requiere:** acceso a instrumentación de referencia calibrada, respaldo
institucional para la gestión de co-ubicación con la red distrital, y vínculo
formal con un grupo reconocido que permita el registro de la producción y el
acceso a convocatorias.

## 7. Trayectoria prevista

| Etapa | Duración | Requisito |
|---|---|---|
| Fase 0 — dispersión entre unidades | 7 días | 3 nodos |
| Fase 1 — co-ubicación con referencia | 28 días | Sitio y referencia |
| v0.3 — migración a ESP32-S3 con micrófono I2S | — | Hardware |
| Fase 2 — verificación de coeficientes | 7 días | Fase 1 completa |
| Re-co-ubicación | 14 días a 6 y 12 meses | Continuidad |
| Estimación de deriva sin referencia | — | 6 a 8 nodos |

## 8. Productos registrados

| Producto | DOI |
|---|---|
| Urban Environmental Station | 10.5281/zenodo.22740968 |
| FireWatch Colombia | 10.5281/zenodo.22565857 |
| uestation (análisis) | 10.5281/zenodo.22740968 |

---

## Documentos relacionados

- [`01-arquitectura.md`](01-arquitectura.md) — decisiones de diseño
- [`02-protocolo-calibracion.md`](02-protocolo-calibracion.md) — procedimiento experimental
- [`06-limitaciones-conocidas.md`](06-limitaciones-conocidas.md) — restricciones vigentes
