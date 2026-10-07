# Visión y alcance

**Proyecto:** Urban Environmental Station
**Autor:** Néstor Oswaldo Vásquez Castro · ORCID 0009-0003-6483-790X
**DOI:** 10.5281/zenodo.22740968
**Estado:** v0.3.0 — prototipo en operación continua, sin calibrar

---

## 1. El problema

Bogotá opera del orden de veinte estaciones de referencia para una ciudad de casi
ocho millones de habitantes. La densidad espacial resultante no permite estudiar la
variabilidad ambiental a escala de barrio, que es precisamente la escala donde se
toman decisiones de planeación urbana.

Los sensores de bajo costo pueden cerrar esa brecha. La dificultad no es técnica sino
metrológica: **sin caracterización de incertidumbre, un dato de bajo costo no es
comparable con nada**, ni con la red de referencia ni con otros nodos de la misma red.

La literatura del área suele resolver esto mediante co-ubicación puntual: se calibra
una vez contra una referencia y se despliega. Ese procedimiento no escala. Una red de
doscientos nodos no puede rotar por una estación de referencia cada seis meses, y la
deriva de los sensores no se detiene porque resulte inconveniente medirla.

## 2. Pregunta de investigación

> ¿Es posible estimar la deriva de sensores ambientales de bajo costo a partir de los
> residuales entre nodos vecinos, sin recalibración física periódica?

La hipótesis: bajo el supuesto de que nodos próximos observan el mismo proceso
ambiental más un sesgo propio de variación lenta, la componente de baja frecuencia
de los residuales entre pares estima la diferencia de derivas. Con tres o más nodos y
una restricción de anclaje, el sistema es identificable.

La primera campaña añade una precisión necesaria a esa hipótesis: el residual de un
nodo contiene una componente sinóptica de varios días que comparte con sus vecinos.
Cualquier estimador de deriva entre nodos debe operar sobre diferencias que cancelen
esa componente común, no sobre los residuales individuales.

Esta línea continúa un trabajo sostenido sobre estimación de parámetros lentamente
variables a partir de residuales de observadores en sistemas embebidos con recursos
limitados.

## 3. Qué existe hoy

### Sistema en operación

Un nodo instrumentado con ESP8266, sensores de temperatura, humedad relativa y
presión barométrica, en operación continua desde el 15 de septiembre de 2026.

| Indicador | Valor (21.2 días) |
|---|---|
| Registros válidos | 5742 de 5757 (99.7 %) |
| Completitud | 94.0 % |
| Reinicios espontáneos | 0 de 8 arranques |
| Intervalos recuperados por la cola persistente | 464 |
| Deriva de memoria libre | +1.6 B/h |

### Cadena de análisis

Firmware que agrega intervalos alineados al reloj; control de calidad con siete
criterios de rechazo y atribución excluyente de causa; agregación temporal con
propagación de varianza; descomposición armónica; contraste de tendencia; separación
de escalas temporales; pronóstico con persistencia de régimen validado con origen
móvil; prescripción operativa; consola de monitoreo; exportación reproducible de
figuras e informe de resultados. Todo verificado mediante pruebas automatizadas sobre
datos sintéticos con defectos controlados.

### Hallazgos

**Escala del proceso frente a escala del período.** El tiempo de decorrelación del
residual completo crece con la longitud del registro: 75, 475, 860, 1185 y 1500 min a
medida que la serie se extendía, y entre 340 y 1570 min según el tramo de siete días
analizado. Separada la componente intradiaria, el valor se estabiliza en 145 min, con
coeficiente de variación de 0.07 a 0.15 entre particiones. Solo este último describe
el proceso, y fija una cadencia de transmisión de 50 min —una reducción del 90 %—
sin pérdida de dinámica intradiaria.

**Grados de libertad efectivos.** Con autocorrelación de primer orden de 0.998, las
5742 observaciones equivalen a unas 29 independientes. Tratar series de sensores
densamente muestreadas como observaciones independientes sobreestima la
significancia estadística en más de un orden de magnitud.

**Rechazo de un falso positivo.** A los nueve días, el ajuste global detectó una
pendiente de +0.27 °C/día, significativa incluso tras corregir por autocorrelación.
El contraste por bloques la rechazó por heterogeneidad (CV = 1.93). Con 21 días de
registro la pendiente estimada cayó a +0.05 °C/día. El sistema no reportó un resultado
positivo disponible porque los datos no lo sostenían, y la extensión del registro
confirmó la decisión.

**Regímenes sinópticos.** El 64 % de la varianza no explicada por el ciclo diurno
corresponde a regímenes de varios días, con correlación de 0.55 entre medias diarias
consecutivas. Las jornadas de mayor amplitud térmica coinciden con las de nivel más
alto, consistente con condiciones despejadas.

**Capacidad predictiva acotada y declarada.** Incorporar la persistencia del régimen
vigente eleva la destreza frente a la climatología a +0.36 y aporta +0.09 sobre el
ciclo diurno por sí solo, en validación sobre cinco ventanas de 24 h. La banda de
predicción cubre el 78 % de las observaciones frente al 95 % nominal: el sistema
declara esta limitación y la traduce en recomendaciones, en lugar de presentar el
modelo como suficiente.

**Vulnerabilidad energética.** Dos interrupciones consecutivas del suministro
comercial el 4 y 5 de octubre detuvieron el registro durante 28 horas. Sin respaldo
de batería, una campaña de co-ubicación de 28 días continuos no es viable.

## 4. Alcance declarado

### Dentro

- Caracterización de incertidumbre y deriva en sensores de bajo costo.
- Metodología de control de calidad y agregación reproducible.
- Tratamiento de series densas con autocorrelación y regímenes de varias escalas.
- Estimación de deriva relativa entre nodos sin referencia trazable.
- Instrumentación, firmware y cadena de análisis de código abierto.

### Fuera

- Sustituir la red de referencia oficial.
- Declaraciones de cumplimiento normativo.
- Pronóstico meteorológico más allá de la persistencia del régimen local.
- Medición de nivel sonoro con trazabilidad, mientras no se incorpore un transductor
  con sensibilidad declarada.

## 5. Lo que bloquea el avance

| Necesidad | Estado | Consecuencia si no se resuelve |
|---|---|---|
| Respaldo energético | pendiente | Las campañas largas quedan expuestas a cortes del suministro |
| Tres o más nodos simultáneos | 1 de 3 | Sin dispersión entre unidades no hay Fase 0 |
| Referencia trazable para co-ubicación | pendiente | La incertidumbre permanece indeterminada |
| Campañas separadas por meses | pendiente | Sin deriva medida no hay contraste de la hipótesis |
| Sonómetro clase 1 o 2 | pendiente | El canal acústico no admite calibración |

## 6. Qué aporta y qué requiere una colaboración

**Aporta:** instrumentación propia en operación, firmware y cadena de análisis
verificados, protocolo experimental documentado con criterios de aceptación
cuantitativos y prueba de falsación declarada, y una metodología de tratamiento de
series densas trasladable a otros dominios urbanos con estructura temporal semejante,
como la movilidad.

**Requiere:** acceso a instrumentación de referencia calibrada, respaldo institucional
para la gestión de co-ubicación con la red distrital, y vínculo formal con un grupo
reconocido que permita el registro de la producción y el acceso a convocatorias.

## 7. Trayectoria prevista

| Etapa | Duración | Requisito |
|---|---|---|
| Fase 0 — dispersión entre unidades | 7 días | 3 nodos |
| Respaldo energético | — | Batería y gestión de carga |
| Fase 1 — co-ubicación con referencia | 28 días | Sitio, referencia y respaldo |
| v0.4 — migración a ESP32-S3 con micrófono I2S | — | Hardware |
| Fase 2 — verificación de coeficientes | 7 días | Fase 1 completa |
| Re-co-ubicación | 14 días a 6 y 12 meses | Continuidad |
| Estimación de deriva sin referencia | — | 6 a 8 nodos |

## 8. Productos registrados

| Producto | DOI |
|---|---|
| Urban Environmental Station | 10.5281/zenodo.22740968 |

---

## Documentos relacionados

- [`01-arquitectura.md`](01-arquitectura.md) — decisiones de diseño
- [`02-protocolo-calibracion.md`](02-protocolo-calibracion.md) — procedimiento experimental
- [`06-limitaciones-conocidas.md`](06-limitaciones-conocidas.md) — restricciones vigentes
- [`07-resultados-campania.md`](07-resultados-campania.md) — informe generado desde los datos
- [`../data/reference/bitacora.md`](../data/reference/bitacora.md) — eventos de campaña
