"""Predicción con persistencia de régimen y prescripción operativa.

El modelo descompone la evolución futura en tres componentes, cada una con
su propia escala temporal medida sobre el registro:

    ŷ(t+Δ) = c(t+Δ) + s_t · ρ^(Δ/24 h) + i_t · exp(−Δ/τ)

    c    ciclo diurno ajustado (más tendencia, si el contraste la confirma)
    s_t  nivel del régimen sinóptico vigente: media del residual en las
         últimas 24 h
    ρ    persistencia entre jornadas: correlación de medias diarias
         consecutivas
    i_t  anomalía intradiaria presente: último residual menos s_t
    τ    tiempo de decorrelación de la componente intradiaria

La varianza del error crece con el horizonte desde cero hasta la varianza
residual total, de modo que la banda de predicción se ensancha a medida que
el estado presente pierde capacidad informativa:

    σ²(Δ) = σ²_i · (1 − e^(−2Δ/τ)) + σ²_s · (1 − ρ^(2Δ/24 h))

Todos los parámetros se estiman exclusivamente con datos anteriores al origen
del pronóstico. La validación emplea origen móvil: se pronostican varias
ventanas sucesivas, cada una con parámetros reestimados sobre su propio
pasado, y el desempeño se compara contra dos referencias —la media
climatológica y el ciclo diurno sin persistencia— para aislar el aporte de
cada componente.

La capa prescriptiva deriva recomendaciones operativas sobre el propio
instrumento y no sobre el fenómeno observado: prescribir sobre el ambiente
excede lo que un nodo sin calibrar puede sustentar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from uestation.decompose import ajustar_ciclo_diurno, detectar_tendencia
from uestation.escalas import separar_escalas

TZ_LOCAL = "America/Bogota"
INTERVALO_MIN_DEFECTO = 5

# La persistencia se acota para que el régimen siempre se disipe con el
# horizonte. Valores negativos carecen de interpretación como amortiguamiento.
RHO_MAXIMO = 0.95


# ============================================================================
#  Estructuras
# ============================================================================
@dataclass
class Estado:
    """Parámetros y condición inicial, estimados solo con el pasado."""

    tau_intradiario_min: float
    rho_diario: float
    var_intradiaria: float
    var_sinoptica: float
    nivel_sinoptico: float
    anomalia_intradiaria: float


@dataclass
class Validacion:
    """Desempeño sobre ventanas excluidas del ajuste."""

    n: int
    n_origenes: int
    mae: float
    rmse: float
    sesgo: float
    cobertura: float
    cobertura_nominal: float
    horizonte_h: float
    mae_climatologia: float
    mae_ciclo: float
    destreza: float            # 1 − MAE / MAE_climatología
    destreza_vs_ciclo: float   # 1 − MAE / MAE_ciclo: aporte de la persistencia
    mae_por_horizonte: dict[str, float] = field(default_factory=dict)

    @property
    def supera_referencia(self) -> bool:
        """El modelo mejora a predecir la media del período."""
        return self.destreza > 0

    @property
    def persistencia_aporta(self) -> bool:
        """La persistencia de régimen mejora al ciclo diurno por sí solo."""
        return self.destreza_vs_ciclo > 0


@dataclass
class Prediccion:
    """Pronóstico con banda de incertidumbre dependiente del horizonte."""

    tiempo: pd.Series
    esperado: np.ndarray
    inferior: np.ndarray
    superior: np.ndarray
    sigma: float               # dispersión asintótica (horizonte infinito)
    con_tendencia: bool
    horizonte_h: float
    tau_min: float             # tiempo de decorrelación intradiario
    estado: Estado | None = None
    validacion: Validacion | None = None
    advertencias: list[str] = field(default_factory=list)


# ============================================================================
#  Núcleo del modelo
# ============================================================================
def _matriz_diseno(
    tiempos: pd.Series,
    t_origen: pd.Timestamp,
    n_armonicos: int,
    con_tendencia: bool,
) -> np.ndarray:
    """Matriz de diseño para instantes arbitrarios.

    Replica la especificación de `decompose.ajustar_ciclo_diurno`, de modo que
    los coeficientes estimados allí sean aplicables aquí sin reajuste.
    """
    local = (tiempos.dt.tz_convert(TZ_LOCAL)
             if tiempos.dt.tz is not None else tiempos)
    h = (local.dt.hour + local.dt.minute / 60.0
         + local.dt.second / 3600.0).to_numpy(dtype=float)
    dias = ((tiempos - t_origen).dt.total_seconds() / 86400.0).to_numpy(dtype=float)

    cols = [np.ones_like(h)]
    if con_tendencia:
        cols.append(dias)
    for k in range(1, n_armonicos + 1):
        cols.append(np.cos(2 * np.pi * k * h / 24.0))
        cols.append(np.sin(2 * np.pi * k * h / 24.0))
    return np.column_stack(cols)


def _coeficientes(
    df: pd.DataFrame,
    columna: str,
    col_tiempo: str,
    n_armonicos: int,
    con_tendencia: bool,
) -> tuple[np.ndarray, pd.Timestamp, float]:
    """Coeficientes del ciclo y dispersión residual."""
    d = df[[col_tiempo, columna]].dropna().sort_values(col_tiempo).reset_index(drop=True)
    X = _matriz_diseno(d[col_tiempo], d[col_tiempo].iloc[0], n_armonicos, con_tendencia)
    y = d[columna].to_numpy(dtype=float)

    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    gl = max(len(y) - X.shape[1], 1)
    sigma = float(np.sqrt(np.sum(resid**2) / gl))

    return coef, d[col_tiempo].iloc[0], sigma


def _estimar_estado(
    train: pd.DataFrame,
    columna: str,
    col_tiempo: str,
    n_armonicos: int,
    con_tendencia: bool,
    intervalo_min: int,
) -> tuple[np.ndarray, pd.Timestamp, Estado]:
    """Estima ciclo, escalas y condición inicial a partir del pasado.

    Si la serie no admite separación de escalas —menos de dos jornadas— el
    modelo degrada a ciclo diurno con anomalía de decaimiento inmediato, sin
    componente sinóptica.
    """
    coef, t0, sigma = _coeficientes(train, columna, col_tiempo,
                                    n_armonicos, con_tendencia)
    m = ajustar_ciclo_diurno(train, columna, col_tiempo,
                             n_armonicos=n_armonicos, con_tendencia=con_tendencia)

    try:
        # Solo se requiere el τ intradiario: el rezago máximo de la
        # autocorrelación total se reduce para no encarecer el cálculo.
        e = separar_escalas(m, intervalo_min=intervalo_min, max_rezago_total_h=24.0)
        tau_i = (e.tau_intradiario_min if np.isfinite(e.tau_intradiario_min)
                 else float(intervalo_min))
        rho = (float(np.clip(e.rho_diario, 0.0, RHO_MAXIMO))
               if np.isfinite(e.rho_diario) else 0.0)
        var_i, var_s = e.var_intradiaria, e.var_sinoptica
        r = e.residual
    except ValueError:
        tau_i, rho = float(intervalo_min), 0.0
        var_i, var_s = sigma**2, 0.0
        r = pd.Series(m.residual.to_numpy(dtype=float),
                      index=pd.DatetimeIndex(m.tiempo))

    validos = r.dropna()
    t_ultimo = validos.index[-1]
    reciente = r[r.index > t_ultimo - pd.Timedelta(hours=24)]
    nivel = float(np.nanmean(reciente.to_numpy())) if reciente.notna().any() else 0.0
    anomalia = float(validos.iloc[-1]) - nivel

    return coef, t0, Estado(
        tau_intradiario_min=tau_i,
        rho_diario=rho,
        var_intradiaria=var_i,
        var_sinoptica=var_s,
        nivel_sinoptico=nivel,
        anomalia_intradiaria=anomalia,
    )


def _proyectar(
    coef: np.ndarray,
    t0: pd.Timestamp,
    estado: Estado,
    tiempos: pd.Series,
    t_ultimo: pd.Timestamp,
    n_armonicos: int,
    con_tendencia: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Proyecta el modelo sobre instantes futuros.

    Returns
    -------
    (esperado, desviación estándar, ciclo sin persistencia)
    """
    ciclo = _matriz_diseno(tiempos, t0, n_armonicos, con_tendencia) @ coef
    delta = ((tiempos - t_ultimo).dt.total_seconds() / 60.0).to_numpy(dtype=float)

    fs = estado.rho_diario ** (delta / 1440.0)
    fi = np.exp(-delta / max(estado.tau_intradiario_min, 1e-6))

    esperado = (ciclo
                + estado.nivel_sinoptico * fs
                + estado.anomalia_intradiaria * fi)
    var = (estado.var_intradiaria * (1.0 - fi**2)
           + estado.var_sinoptica * (1.0 - fs**2))
    return esperado, np.sqrt(np.maximum(var, 1e-8)), ciclo


# ============================================================================
#  Validación
# ============================================================================
def validar_fuera_de_muestra(
    df: pd.DataFrame,
    columna: str = "temp_c.prom",
    col_tiempo: str = "t_fin",
    horas_prueba: float = 24.0,
    n_armonicos: int = 3,
    con_tendencia: bool = False,
    confianza: float = 0.95,
    n_origenes: int = 1,
    intervalo_min: int = INTERVALO_MIN_DEFECTO,
) -> Validacion | None:
    """Evalúa el modelo con origen móvil sobre ventanas sucesivas.

    Se pronostican `n_origenes` ventanas consecutivas de `horas_prueba`, la
    última de las cuales termina con el registro. Cada ventana se pronostica
    con parámetros estimados únicamente sobre los datos que la preceden.

    Un único origen es frágil: el desempeño queda determinado por el régimen
    meteorológico de esa jornada concreta. Varios orígenes promedian sobre
    regímenes distintos y producen una estimación más representativa.
    """
    d = df[[col_tiempo, columna]].dropna().sort_values(col_tiempo).reset_index(drop=True)
    if len(d) < 200:
        return None

    n_param = 1 + 2 * n_armonicos + (1 if con_tendencia else 0)
    z = float(stats.norm.ppf(0.5 + confianza / 2))
    t_fin_serie = d[col_tiempo].iloc[-1]

    errores, err_clim, err_ciclo, dentro, deltas = [], [], [], [], []
    usados = 0

    for k in range(n_origenes, 0, -1):
        fin_ventana = t_fin_serie - pd.Timedelta(hours=horas_prueba * (k - 1))
        corte = fin_ventana - pd.Timedelta(hours=horas_prueba)
        train = d[d[col_tiempo] <= corte]
        prueba = d[(d[col_tiempo] > corte) & (d[col_tiempo] <= fin_ventana)]

        if len(train) < n_param + 50 or len(prueba) < 10:
            continue

        try:
            coef, t0, est = _estimar_estado(train, columna, col_tiempo,
                                            n_armonicos, con_tendencia, intervalo_min)
        except (ValueError, np.linalg.LinAlgError):
            continue

        t_ultimo = train[col_tiempo].iloc[-1]
        tiempos = prueba[col_tiempo].reset_index(drop=True)
        esp, sd, ciclo = _proyectar(coef, t0, est, tiempos, t_ultimo,
                                    n_armonicos, con_tendencia)
        obs = prueba[columna].to_numpy(dtype=float)

        errores.append(obs - esp)
        err_ciclo.append(obs - ciclo)
        err_clim.append(obs - float(train[columna].mean()))
        dentro.append(np.abs(obs - esp) <= z * sd)
        deltas.append(((tiempos - t_ultimo).dt.total_seconds() / 60.0).to_numpy())
        usados += 1

    if usados == 0:
        return None

    e = np.concatenate(errores)
    dl = np.concatenate(deltas)
    mae = float(np.mean(np.abs(e)))
    mae_clim = float(np.mean(np.abs(np.concatenate(err_clim))))
    mae_ciclo = float(np.mean(np.abs(np.concatenate(err_ciclo))))

    por_horizonte = {}
    for etiqueta, limite in [("1 h", 60), ("6 h", 360), ("24 h", 1440)]:
        m = dl <= limite
        if m.any():
            por_horizonte[etiqueta] = float(np.mean(np.abs(e[m])))

    return Validacion(
        n=len(e),
        n_origenes=usados,
        mae=mae,
        rmse=float(np.sqrt(np.mean(e**2))),
        sesgo=float(np.mean(e)),
        cobertura=float(np.mean(np.concatenate(dentro))),
        cobertura_nominal=confianza,
        horizonte_h=horas_prueba,
        mae_climatologia=mae_clim,
        mae_ciclo=mae_ciclo,
        destreza=float(1.0 - mae / mae_clim) if mae_clim > 0 else 0.0,
        destreza_vs_ciclo=float(1.0 - mae / mae_ciclo) if mae_ciclo > 0 else 0.0,
        mae_por_horizonte=por_horizonte,
    )


# ============================================================================
#  Pronóstico
# ============================================================================
def predecir(
    df: pd.DataFrame,
    columna: str = "temp_c.prom",
    col_tiempo: str = "t_fin",
    horas: float = 24.0,
    intervalo_min: int = INTERVALO_MIN_DEFECTO,
    n_armonicos: int = 3,
    confianza: float = 0.95,
    validar: bool = True,
    n_origenes: int = 5,
) -> Prediccion | None:
    """Pronostica la variable con banda de incertidumbre dependiente del horizonte.

    La especificación del ciclo —con o sin tendencia— la decide
    `detectar_tendencia`, de modo que no se extrapole una deriva que los
    datos no sostienen.
    """
    d = df[[col_tiempo, columna]].dropna().sort_values(col_tiempo).reset_index(drop=True)
    if len(d) < 200:
        return None

    contraste = detectar_tendencia(df, columna, col_tiempo)
    con_tendencia = bool(contraste["recomendada"])

    try:
        coef, t0, est = _estimar_estado(d, columna, col_tiempo,
                                        n_armonicos, con_tendencia, intervalo_min)
    except (ValueError, np.linalg.LinAlgError):
        return None

    t_ultimo = d[col_tiempo].iloc[-1]
    futuro = pd.Series(pd.date_range(
        t_ultimo + pd.Timedelta(minutes=intervalo_min),
        periods=int(horas * 60 / intervalo_min),
        freq=f"{intervalo_min}min",
    ))

    esperado, sd, _ = _proyectar(coef, t0, est, futuro, t_ultimo,
                                 n_armonicos, con_tendencia)
    z = float(stats.norm.ppf(0.5 + confianza / 2))

    advertencias = []
    if horas * 60 > est.tau_intradiario_min:
        advertencias.append(
            f"Más allá de {est.tau_intradiario_min:.0f} min —tiempo de decorrelación "
            "intradiario— la anomalía presente se disipa. El pronóstico se apoya "
            f"entonces en la persistencia del régimen sinóptico (ρ diario = "
            f"{est.rho_diario:.2f}) y converge al ciclo climatológico."
        )
    if con_tendencia:
        advertencias.append(
            f"La predicción extrapola una deriva de {contraste['pendiente_dia']:+.3f} "
            "°C/día. La extrapolación lineal pierde validez con el horizonte."
        )
    if len(d) < 288 * 7:
        advertencias.append(
            f"El ajuste emplea {len(d) / 288:.1f} días de registro; la estimación "
            "del ciclo y de la persistencia gana estabilidad con series más extensas."
        )

    val = None
    if validar:
        val = validar_fuera_de_muestra(df, columna, col_tiempo,
                                       horas_prueba=min(horas, 24.0),
                                       n_armonicos=n_armonicos,
                                       con_tendencia=con_tendencia,
                                       confianza=confianza,
                                       n_origenes=n_origenes,
                                       intervalo_min=intervalo_min)

    return Prediccion(
        tiempo=futuro,
        esperado=esperado,
        inferior=esperado - z * sd,
        superior=esperado + z * sd,
        sigma=float(np.sqrt(est.var_intradiaria + est.var_sinoptica)),
        con_tendencia=con_tendencia,
        horizonte_h=horas,
        tau_min=est.tau_intradiario_min,
        estado=est,
        validacion=val,
        advertencias=advertencias,
    )


# ============================================================================
#  Prescripción
# ============================================================================
@dataclass
class Recomendacion:
    """Acción sugerida, con su justificación cuantitativa."""

    categoria: str          # energia | mantenimiento | calidad | metodologia
    prioridad: str          # alta | media | baja
    titulo: str
    detalle: str
    magnitud: str = ""


def _cadencia_sugerida(tau_min: float, intervalo_min: int) -> int:
    """Cadencia de transmisión compatible con la dinámica intradiaria.

    Se adopta τ/3 como regla operativa: tres muestras por tiempo
    característico preservan la dinámica sin incurrir en redundancia. El valor
    se redondea a múltiplos de cinco minutos y se acota a una hora.

    El τ empleado debe ser el intradiario. El del residual completo crece con
    la longitud del registro porque incorpora regímenes de varios días, y
    conduciría a cadencias que perderían la dinámica de horas.
    """
    if not np.isfinite(tau_min) or tau_min <= 0:
        return intervalo_min
    objetivo = max(intervalo_min, int(round(tau_min / 3.0 / 5.0) * 5))
    return min(objetivo, 60)


def prescribir(
    df: pd.DataFrame,
    limpio: pd.DataFrame,
    diagnostico: dict,
    resumen_qc,
    prediccion: Prediccion | None = None,
    contraste: dict | None = None,
    intervalo_min: int = INTERVALO_MIN_DEFECTO,
) -> list[Recomendacion]:
    """Deriva recomendaciones operativas del estado observado del sistema.

    El alcance es deliberadamente interno: cadencia de transmisión, integridad
    del instrumento, suficiencia de la serie y validez del modelo.
    """
    recs: list[Recomendacion] = []

    # --- Energía ---
    if prediccion is not None and np.isfinite(prediccion.tau_min):
        tau = prediccion.tau_min
        sugerida = _cadencia_sugerida(tau, intervalo_min)
        if sugerida > intervalo_min:
            ahorro = 100.0 * (1.0 - intervalo_min / sugerida)
            recs.append(Recomendacion(
                categoria="energia",
                prioridad="media",
                titulo=f"Ampliar la cadencia de transmisión a {sugerida} min",
                detalle=(
                    f"La componente intradiaria del residual se decorrelaciona en "
                    f"{tau:.0f} min, de modo que el muestreo cada {intervalo_min} min "
                    f"produce observaciones redundantes. Una cadencia de {sugerida} "
                    "min conserva tres muestras por tiempo característico."
                ),
                magnitud=f"−{ahorro:.0f} % de transmisiones",
            ))

    # --- Mantenimiento ---
    espontaneos = diagnostico.get("reinicios_espontaneos", 0)
    if espontaneos > 0:
        recs.append(Recomendacion(
            categoria="mantenimiento",
            prioridad="alta",
            titulo="Investigar los reinicios no inducidos",
            detalle=(
                f"Se registraron {espontaneos} arranques cuya causa no corresponde "
                "a una reprogramación. Conviene revisar la causa consignada en el "
                "campo de diagnóstico y la estabilidad de la alimentación."
            ),
            magnitud=f"{espontaneos} eventos",
        ))

    pendiente_heap = diagnostico.get("heap_pendiente_bytes_hora", 0.0)
    if pendiente_heap < -20:
        horas_restantes = (diagnostico.get("heap_min", 0) / abs(pendiente_heap)
                           if pendiente_heap else np.inf)
        recs.append(Recomendacion(
            categoria="mantenimiento",
            prioridad="alta",
            titulo="Degradación sostenida de memoria libre",
            detalle=(
                f"La memoria disponible decrece a razón de {pendiente_heap:+.1f} B/h. "
                "De mantenerse el ritmo, el sistema alcanzaría condiciones de "
                "agotamiento antes de completar una campaña prolongada."
            ),
            magnitud=f"≈ {horas_restantes / 24:.0f} días de margen",
        ))
    elif diagnostico.get("heap_min", 1e9) < 8000:
        recs.append(Recomendacion(
            categoria="mantenimiento",
            prioridad="media",
            titulo="Margen de memoria reducido",
            detalle=(
                f"El mínimo observado es de {diagnostico.get('heap_min', 0):.0f} B, "
                f"con fragmentación de hasta {diagnostico.get('frag_max_pct', 0):.0f} %. "
                "El establecimiento de la conexión TLS opera cerca del límite "
                "disponible, lo que aconseja migrar a una plataforma con mayor "
                "memoria antes de ampliar la funcionalidad."
            ),
            magnitud=f"{diagnostico.get('heap_min', 0):.0f} B libres",
        ))

    # --- Calidad ---
    if resumen_qc is not None and resumen_qc.fraccion_descartada > 0.10:
        recs.append(Recomendacion(
            categoria="calidad",
            prioridad="alta",
            titulo="Tasa de rechazo por encima del umbral del protocolo",
            detalle=(
                f"El {resumen_qc.fraccion_descartada:.1%} de los registros no supera "
                "el control de calidad, por encima del 10 % admitido en el "
                "protocolo §5.4. La causa predominante debe reportarse como hallazgo."
            ),
            magnitud=f"{resumen_qc.n_descartado} registros",
        ))

    muestras_moda = diagnostico.get("muestras_moda")
    if muestras_moda is not None and 0 < muestras_moda < 150:
        perdida = 150 - muestras_moda
        recs.append(Recomendacion(
            categoria="calidad",
            prioridad="baja",
            titulo="Pérdida sistemática de muestras por intervalo",
            detalle=(
                f"El valor modal es de {muestras_moda} muestras frente a las 150 "
                f"esperadas. La deriva del temporizador explica la ausencia de "
                f"{perdida} muestra(s) por intervalo, sin consecuencia apreciable "
                "sobre los estadísticos."
            ),
            magnitud=f"−{100 * perdida / 150:.1f} %",
        ))

    # --- Metodología ---
    if prediccion is not None and prediccion.validacion is not None:
        v = prediccion.validacion
        if not v.supera_referencia:
            recs.append(Recomendacion(
                categoria="metodologia",
                prioridad="alta",
                titulo="El modelo no supera la referencia climatológica",
                detalle=(
                    f"El error absoluto medio fuera de muestra ({v.mae:.2f} °C) no "
                    f"mejora al de predecir la media del período "
                    f"({v.mae_climatologia:.2f} °C) sobre {v.n_origenes} ventanas."
                ),
                magnitud=f"destreza {v.destreza:+.2f}",
            ))
        if not v.persistencia_aporta:
            recs.append(Recomendacion(
                categoria="metodologia",
                prioridad="baja",
                titulo="La persistencia de régimen no mejora al ciclo",
                detalle=(
                    f"Con persistencia el error es {v.mae:.2f} °C frente a "
                    f"{v.mae_ciclo:.2f} °C del ciclo por sí solo. El régimen "
                    "vigente no está aportando información predictiva en el "
                    "período evaluado."
                ),
                magnitud=f"{v.destreza_vs_ciclo:+.2f}",
            ))
        if abs(v.cobertura - v.cobertura_nominal) > 0.10:
            direccion = ("subestima" if v.cobertura < v.cobertura_nominal
                         else "sobreestima")
            recs.append(Recomendacion(
                categoria="metodologia",
                prioridad="media",
                titulo=f"La banda de predicción {direccion} la incertidumbre",
                detalle=(
                    f"El {v.cobertura:.0%} de las observaciones cae dentro del "
                    f"intervalo, frente al {v.cobertura_nominal:.0%} nominal, sobre "
                    f"{v.n_origenes} ventanas de validación."
                ),
                magnitud=f"{v.cobertura:.0%} vs {v.cobertura_nominal:.0%}",
            ))

    n_dias = len(limpio) / 288.0 if len(limpio) else 0
    if n_dias < 14:
        recs.append(Recomendacion(
            categoria="metodologia",
            prioridad="media",
            titulo="Extender el período de registro",
            detalle=(
                f"La serie abarca {n_dias:.1f} días. La caracterización de deriva "
                "requiere contrastar campañas separadas por meses, y la estimación "
                "del ciclo gana estabilidad con al menos cuatro semanas continuas."
            ),
            magnitud=f"{n_dias:.0f} de 28 días",
        ))

    if (contraste is not None
            and not contraste.get("recomendada", False)
            and contraste.get("supera_umbral")
            and not contraste.get("homogenea")):
        recs.append(Recomendacion(
            categoria="metodologia",
            prioridad="baja",
            titulo="Variabilidad entre jornadas no modelada",
            detalle=(
                f"Las pendientes por bloque presentan un coeficiente de variación "
                f"de {contraste.get('cv_bloques', 0):.2f}, señal de heterogeneidad "
                "meteorológica antes que de deriva. Una covariable de nubosidad o "
                "radiación permitiría explicarla."
            ),
            magnitud=f"CV = {contraste.get('cv_bloques', 0):.2f}",
        ))

    recs.append(Recomendacion(
        categoria="metodologia",
        prioridad="alta",
        titulo="Completar la co-ubicación con referencia trazable",
        detalle=(
            "La incertidumbre reportada excluye la componente de calibración, que "
            "permanece indeterminada. Sin co-ubicación, las lecturas no admiten "
            "comparación con otras fuentes ni uso normativo."
        ),
        magnitud="bloquea la trazabilidad",
    ))

    orden = {"alta": 0, "media": 1, "baja": 2}
    return sorted(recs, key=lambda r: orden.get(r.prioridad, 3))
