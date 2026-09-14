# Protocolo de calibración y validación por co-ubicación

**Versión del documento:** 1.0
**Aplica a firmware:** v0.2.x en adelante
**Autor:** Néstor Oswaldo Vásquez Castro (ORCID 0009-0003-6483-790X)

---

## 1. Propósito

Este documento define el procedimiento experimental para:

1. Cuantificar el sesgo y la dispersión de cada variable medida respecto a una
   referencia trazable.
2. Derivar funciones de corrección con intervalos de validez declarados.
3. Estimar la incertidumbre expandida asociada a cada variable corregida.
4. Caracterizar la deriva temporal de los sensores bajo condiciones urbanas reales.

El objetivo **no** es demostrar que el equipo funciona. Es determinar, con
evidencia, bajo qué condiciones y con qué margen de error sus datos son
utilizables, y bajo cuáles no lo son.

## 2. Alcance y exclusiones

| Variable | Referencia | Trazabilidad alcanzable |
|---|---|---|
| Temperatura del aire | Estación de referencia co-ubicada | Relativa a la referencia |
| Humedad relativa | Estación de referencia co-ubicada | Relativa a la referencia |
| Presión barométrica | Barómetro de referencia a igual altura | Relativa a la referencia |
| Nivel sonoro | Sonómetro IEC 61672 clase 1 o 2 | **Ninguna en v0.2** (ver §9) |

**Fuera de alcance:** calibración absoluta contra patrones primarios,
certificación metrológica, y cualquier declaración de cumplimiento normativo.

## 3. Requisitos previos

### 3.1 Unidades bajo ensayo

Mínimo **tres unidades idénticas**, identificadas por su `device_id`. Con una
sola unidad es imposible separar el error del sensor del error de fabricación,
y cualquier coeficiente obtenido carece de intervalo de confianza entre unidades.

### 3.2 Configuración del firmware

- `VERSION_CAL = "sin-calibrar"` durante toda la campaña.
- Coeficientes en identidad: `CAL_TEMP = {1.0, 0.0}`, ídem HR y presión.
- `INTERVALO_S = 300`, sin modificar durante la campaña.
- Registrar el commit hash exacto del firmware en la bitácora.

**Regla dura:** ningún coeficiente de corrección se aplica en el firmware durante
la campaña. Todas las correcciones se derivan y se validan sobre datos crudos.

### 3.3 Metadatos obligatorios por unidad

Registrar en `data/reference/unidades.csv`.

## 4. Fase 0 — Precisión entre unidades (laboratorio, 7 días)

**Objetivo:** cuantificar la dispersión entre unidades idénticas antes de
exponerlas a condiciones de campo.

**Ventaja operativa:** esta fase no requiere permisos, sitio externo ni
micrófono calibrado. Puede ejecutarse tan pronto haya tres unidades armadas.

### Montaje

Las tres unidades en el mismo ambiente interior, separadas menos de 30 cm, sin
corriente de aire directa, sin sol, sin fuentes de calor. Alimentación estable.

### Duración

168 horas continuas, lo que produce ~2016 intervalos por unidad.

### Métricas

Para cada instante *t* y variable *x*, con *m* la media entre unidades:

- **Desviación entre unidades:** `s(t) = sd(x_i(t))` sobre las *i* unidades.
- **Sesgo relativo por unidad:** `b_i = media_t(x_i(t) − m(t))`.
- **Repetibilidad:** desviación estándar de las diferencias.

### Criterios de aceptación

| Variable | Dispersión entre unidades (sd mediana) |
|---|---|
| Temperatura | ≤ 0.4 °C |
| Humedad relativa | ≤ 3.0 % |
| Presión | ≤ 0.6 hPa |

Si una unidad excede el criterio, se investiga antes de llevarla a campo. No se
corrige: se diagnostica. Una unidad discrepante suele indicar defecto de
soldadura, sensor fuera de lote o ruido de alimentación, no un problema de
calibración.

### Subensayo: autocalentamiento

En paralelo, una unidad adicional con el sensor de temperatura y humedad montado
en cable de 20 cm, misma ubicación. La diferencia sistemática entre ambas
configuraciones estima el autocalentamiento del PCB, y determina si el sensor
debe ir en placa hija.

**Resultado esperado:** `Δ_autocalentamiento` en °C, con su intervalo de
confianza. Se documenta aunque el diseño no cambie.

## 5. Fase 1 — Co-ubicación con referencia (campo, 28 días mínimo)

### 5.1 Selección del sitio

Criterios, en orden de prioridad:

1. Estación de referencia que reporte temperatura, humedad relativa y presión.
2. Acceso físico autorizado para instalar a menos de 10 m de los sensores de
   referencia.
3. Diferencia de altura respecto a los sensores de referencia menor a 1 m.
4. Disponibilidad de energía y conectividad, o autonomía suficiente.

> **Verificar antes de comprometer el sitio:** no todas las estaciones de una red
> miden el conjunto completo de variables meteorológicas. Consultar el inventario
> vigente y la resolución temporal de publicación.

La gestión del permiso puede tomar varias semanas. **Iniciarla antes de terminar
el prototipo**: es la ruta crítica del cronograma.

### 5.2 Instalación

- Escudo de radiación multiplato ventilado, obligatorio para todas las unidades.
- Altura de sensores entre 1.25 m y 2 m sobre el suelo.
- Sensores a la misma altura que los de la estación de referencia.
- Sin obstrucción del flujo de aire en un radio de 1 m.
- Fotografía del montaje, con fecha, archivada en `docs/figuras/`.

### 5.3 Duración

**28 días como mínimo.** En Bogotá la variabilidad térmica es predominantemente
diurna, no estacional; cuatro semanas capturan ~28 ciclos diurnos completos y
suficiente variedad de nubosidad y precipitación.

Condición adicional: el rango de temperatura cubierto debe abarcar al menos el
percentil 5 al 95 de la serie histórica del sitio. Si no se cumple, extender la
campaña. **La función de corrección solo es válida dentro del rango observado.**

### 5.4 Control de calidad previo al pareo

Descartar intervalos donde:

- `temp_c.n < 120` (menos del 80 % de las muestras esperadas).
- `diag.aht == false` o `diag.bmp == false`.
- `t_fin` es nulo (intervalo sin sincronización horaria).
- El intervalo contiene un reinicio (`boot` distinto al anterior).
- El valor está fuera de rango físico plausible.

Documentar el porcentaje descartado por causa. Un descarte superior al 10 % es un
hallazgo en sí mismo y debe reportarse.

### 5.5 Pareo temporal

Si la referencia publica a resolución horaria, agregar la estación a promedios
horarios alineados a la hora en punto, **exigiendo al menos 10 de los 12
intervalos** de cada hora.

Para nivel sonoro no se promedia aritméticamente: se compone en energía.

Todos los timestamps se manejan en UTC hasta la capa de presentación.

## 6. Derivación de las funciones de corrección

### 6.1 Modelo base

Para cada unidad *i* y variable *x*:

```
x_ref = a_i · x_cruda + b_i + ε
```

Ajuste por mínimos cuadrados ordinarios. Como la incertidumbre de la referencia
es sustancialmente menor que la del sensor bajo ensayo, OLS es admisible. Si esa
condición no se sostiene, usar regresión de Deming con λ igual a la razón de
varianzas de error, documentando el valor empleado.

### 6.2 Modelo extendido para temperatura

El sesgo de los sensores de bajo costo suele depender de la humedad y de la hora
del día, por efecto de radiación residual. Evaluar:

```
x_ref = a·x_cruda + c·HR + d·sin(2π·h/24) + e·cos(2π·h/24) + b
```

Se adopta el modelo extendido **solo si** reduce el RMSE de validación en más de
un 15 % respecto al modelo base. Ganancias menores no justifican la complejidad
ni el riesgo de sobreajuste.

### 6.3 Validación: partición temporal, no aleatoria

**Crítico.** Las series ambientales tienen autocorrelación fuerte. Una partición
aleatoria coloca observaciones casi idénticas a ambos lados y produce métricas
optimistas que colapsan en operación real.

Procedimiento:

- Entrenamiento: días 1 a 21.
- Validación: días 22 a 28, **sin tocarlos** durante el ajuste.
- Backtesting de origen móvil con ventana expansiva y horizonte de 7 días,
  reportando la distribución del RMSE entre ventanas.

Reportar además el desempeño **estratificado** por:

- Franja horaria (madrugada, mañana, tarde, noche).
- Cuartil de humedad relativa.
- Condición de precipitación, si la referencia la reporta.

Un R² global alto con desempeño deficiente en alguna franja es un resultado
negativo, y debe presentarse como tal.

### 6.4 Métricas a reportar

Para cada variable, unidad y estrato:

| Métrica | Definición |
|---|---|
| MBE | Error medio (sesgo, con signo) |
| MAE | Error absoluto medio |
| RMSE | Raíz del error cuadrático medio |
| R² | Coeficiente de determinación |
| a, b | Pendiente e intercepto con IC 95 % |
| U | Incertidumbre expandida, k = 2 |

La incertidumbre expandida combina la incertidumbre residual del ajuste, la
incertidumbre declarada de la referencia y la dispersión entre unidades de Fase 0.

### 6.5 Criterios de aceptación (post-corrección, datos de validación)

| Variable | MBE | RMSE horario |
|---|---|---|
| Temperatura | \|MBE\| ≤ 0.5 °C | ≤ 1.0 °C |
| Humedad relativa | \|MBE\| ≤ 3 % | ≤ 5 % |
| Presión | \|MBE\| ≤ 0.3 hPa | ≤ 0.6 hPa |

Estos umbrales son **objetivos de proyecto**, no requisitos normativos, y son
menos exigentes que las recomendaciones WMO para estaciones de referencia.
Declararlo explícitamente en toda publicación.

## 7. Caracterización de deriva

Esta es la componente de investigación del protocolo y el vínculo con la línea de
trabajo sobre estimación de parámetros lentamente variables a partir de
residuales.

### 7.1 Deriva intra-campaña

Dividir los 28 días en bloques semanales y ajustar el modelo base en cada bloque.
Evaluar si los coeficientes `a_i(k)` y `b_i(k)` presentan tendencia significativa
sobre *k*, mediante prueba de Mann-Kendall y regresión sobre el índice de bloque.

### 7.2 Deriva inter-campaña

Re-co-ubicar las mismas unidades a los 6 y 12 meses, 14 días cada vez. La
diferencia de coeficientes entre campañas estima la deriva anualizada, expresada
en °C/año, %HR/año y hPa/año.

### 7.3 Estimación de deriva sin referencia (línea de investigación)

**Hipótesis:** en una red de nodos co-ubicados o cercanos, la deriva individual
puede estimarse a partir de la evolución temporal de los residuales entre pares
de nodos, sin acceso a una estación de referencia.

Formulación: sea `r_ij(t) = x_i(t) − x_j(t)`. Bajo el supuesto de que los nodos
observan el mismo proceso ambiental más un sesgo lento propio, la componente de
baja frecuencia de `r_ij` estima la diferencia de derivas. Con tres o más nodos y
una restricción de suma cero (o un nodo anclado a referencia), el sistema es
identificable.

**Riesgo metodológico principal:** el gradiente espacial urbano y la deriva del
sensor producen señales de baja frecuencia indistinguibles. El diseño
experimental debe incluir un subconjunto de nodos co-ubicados a menos de 5 m
durante toda la campaña, donde el gradiente es despreciable y el residual es casi
puro sesgo instrumental.

**Prueba de falsación:** aplicar el método sobre los datos de las Fases 0 y 1, y
contrastar la deriva estimada contra la deriva medida en §7.2. Si las
estimaciones no concuerdan dentro de la incertidumbre, la hipótesis se rechaza y
se reporta como resultado negativo.

Este es el aporte publicable del proyecto. Su valor no depende de que la
hipótesis resulte cierta.

## 8. Fase 2 — Verificación posterior (7 días)

Cargar los coeficientes derivados al firmware, fijar `VERSION_CAL` con el
identificador de campaña (formato `AAAA-MM-<sitio>`), y re-co-ubicar 7 días.

**Criterio de cierre:** las métricas en operación corregida deben estar dentro
del intervalo de confianza de las métricas de validación de §6.3. Si no lo están,
hay sobreajuste o un cambio no controlado en el montaje.

## 9. Calibración de nivel sonoro

Ver `06-limitaciones-conocidas.md`. En v0.2 el transductor analógico no permite
trazabilidad y **no debe someterse a este protocolo como si la tuviera**.

Procedimiento provisional para determinar `K_SONIDO`:

1. Sonómetro IEC 61672 clase 1 o 2, en ponderación Z (o C si Z no está
   disponible), respuesta Fast, micrófono a menos de 15 cm del sensor bajo ensayo.
2. Ruido rosa estable, 120 s por nivel, en tres niveles: ~55, ~70 y ~85 dB.
3. `K_nuevo = K_actual + (Leq_referencia − Leq_estación)` a 70 dB.
4. Con los tres puntos, verificar linealidad. Si la pendiente se desvía más de
   10 % de la unidad, el rango útil está comprometido y debe declararse acotado.
5. Determinar el piso de ruido propio y el nivel de saturación (`son.clip > 0`).

Los valores resultantes se reportan como **nivel sonoro sin ponderación
frecuencial**, nunca como dB(A), y nunca comparados contra estándares normativos.

La calibración trazable queda supeditada a la v0.3 con micrófono I2S y
ponderación A en firmware.

## 10. Entregables

```
data/gold/calibracion_<AAAA-MM>_<sitio>/
├── pares_horarios.parquet       # datos pareados, post-QC
├── coeficientes.csv             # a, b, IC95, por unidad y variable
├── metricas.csv                 # global y estratificadas
├── metricas_deriva.csv          # coeficientes por bloque semanal
├── qc_resumen.md                # % descartado por causa
└── bitacora.md                  # eventos de campo, incidencias
```

Figuras obligatorias, exportadas a `docs/figuras/`:

1. Series temporales superpuestas, estación y referencia.
2. Dispersión con recta ajustada e intervalo de predicción.
3. Bland-Altman (diferencia contra media) con límites de concordancia.
4. Residual contra humedad relativa y contra hora del día.
5. Evolución de coeficientes por bloque semanal, con barras de error.
6. Boxplot de RMSE estratificado.

## 11. Bitácora

Toda intervención física sobre una unidad durante la campaña se registra en
`bitacora.md` con fecha, hora UTC, `device_id`, acción y responsable. Una limpieza
del escudo, un reinicio manual o un cambio de cable pueden explicar una
discontinuidad; sin bitácora, esa discontinuidad es un dato perdido.

---

## Referencias a consultar antes de ejecutar

- WMO-No. 8, *Guide to Instruments and Methods of Observation*, Volumen I.
- Documentación y datos históricos de la red de referencia empleada.
- Resolución 627 de 2006, MAVDT (contexto normativo únicamente, ver §9).
- IEC 61672-1, especificación de sonómetros.
