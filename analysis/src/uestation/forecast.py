
"""Predicción del ciclo diurno y prescripción operativa.

El modelo armónico ajustado en `decompose` es, por construcción, un predictor:
evaluado en instantes futuros devuelve el valor esperado de la variable. Este
módulo formaliza ese uso y, sobre todo, lo somete a validación fuera de
muestra.

Dos advertencias gobiernan el diseño:

1. **El horizonte útil está acotado por la física del proceso.** Más allá del
   tiempo de decorrelación, el residual no aporta información y la predicción
   converge al ciclo climatológico. Anunciar precisión más allá de ese
   horizonte sería una afirmación sin respaldo.

2. **La validación debe ser temporal, nunca aleatoria.** Con observaciones
   fuertemente autocorreladas, una partición al azar sitúa puntos casi
   idénticos a ambos lados y produce métricas optimistas que no se sostienen
   en operación.

La capa prescriptiva deriva recomendaciones operativas sobre el propio
instrumento —cadencia de transmisión, necesidad de intervención— y no sobre
el fenómeno observado: prescribir sobre el ambiente excede lo que un nodo sin
calibrar puede sustentar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from uestation.decompose import (
    ajustar_ciclo_diurno,
    autocorrelacion,
    detectar_tendencia,
    tiempo_decorrelacion,
)

TZ_LOCAL = "America/Bogota"
INTERVALO_MIN_DEFECTO = 5


# ============================================================================
#  Predicción
# ============================================================================
@dataclass
class Validacion:
    """Desempeño del modelo sobre un período no empleado en el ajuste."""

    n: int
    mae: float
    rmse: float
    sesgo: float
    cobertura: float          # fracción dentro del intervalo de predicción
    cobertura_nominal: float
    horizonte_h: float
    mae_climatologia: float   # referencia: predecir con la media del período
    destreza: float           # 1 − MAE_modelo / MAE_referencia

    @property
    def supera_referencia(self) -> bool:
        """El modelo aporta sobre predecir simplemente la media."""
        return self.destreza > 0


@dataclass
class Prediccion:
    """Pronóstico con banda de incertidumbre y su validación asociada."""

    tiempo: pd.Series
    esperado: np.ndarray
    inferior: np.ndarray
    superior: np.ndarray
    sigma: float
    con_tendencia: bool
    horizonte_h: float
    tau_min: float
    validacion: Validacion | None = None
    advertencias: list[str] = field(default_factory=list)


def _matriz_diseno(
    tiempos: pd.Series,
    t_origen: pd.Timestamp,
    n_armonicos: int,
    con_tendencia: bool,
) -> np.ndarray:
    """Construye la matriz de diseño para instantes arbitrarios.

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
    """Estima los coeficientes del modelo y la dispersión residual."""
    d = df[[col_tiempo, columna]].dropna().sort_values(col_tiempo).reset_index(drop=True)
    X = _matriz_diseno(d[col_tiempo], d[col_tiempo].iloc[0], n_armonicos, con_tendencia)
    y = d[columna].to_numpy(dtype=float)

    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    gl = max(len(y) - X.shape[1], 1)
    sigma = float(np.sqrt(np.sum(resid**2) / gl))

    return coef, d[col_tiempo].iloc[0], sigma


def validar_fuera_de_muestra(
    df: pd.DataFrame,
    columna: str = "temp_c.prom",
    col_tiempo: str = "t_fin",
    horas_prueba: float = 24.0,
    n_armonicos: int = 3,
    con_tendencia: bool = False,
    confianza: float = 0.95,
) -> Validacion | None:
    """Evalúa el modelo sobre el tramo final, excluido del ajuste.

    La partición es estrictamente temporal: se ajusta con todo lo anterior a
    las últimas `horas_prueba` y se predice ese tramo. Cualquier otra forma de
    partición sobrestimaría el desempeño por la autocorrelación de la serie.

    Se reporta además la **destreza** respecto a una referencia climatológica
    trivial: predecir siempre la media del período de ajuste. Un modelo que no
    supera esa referencia no justifica su complejidad.
    """
    d = df[[col_tiempo, columna]].dropna().sort_values(col_tiempo).reset_index(drop=True)
    if len(d) < 200:
        return None

    corte = d[col_tiempo].iloc[-1] - pd.Timedelta(hours=horas_prueba)
    ajuste = d[d[col_tiempo] <= corte]
    prueba = d[d[col_tiempo] > corte]

    n_param = 1 + 2 * n_armonicos + (1 if con_tendencia else 0)
    if len(ajuste) < n_param + 50 or len(prueba) < 10:
        return None

    coef, t0, sigma = _coeficientes(ajuste, columna, col_tiempo,
                                    n_armonicos, con_tendencia)

    X = _matriz_diseno(prueba[col_tiempo], t0, n_armonicos, con_tendencia)
    pred = X @ coef
    obs = prueba[columna].to_numpy(dtype=float)
    err = obs - pred

    z = float(stats.norm.ppf(0.5 + confianza / 2))
    dentro = np.abs(err) <= z * sigma

    # Referencia climatológica: la media del período de ajuste.
    media_ajuste = float(ajuste[columna].mean())
    mae_ref = float(np.mean(np.abs(obs - media_ajuste)))
    mae = float(np.mean(np.abs(err)))

    return Validacion(
        n=len(prueba),
        mae=mae,
        rmse=float(np.sqrt(np.mean(err**2))),
        sesgo=float(np.mean(err)),
        cobertura=float(np.mean(dentro)),
        cobertura_nominal=confianza,
        horizonte_h=horas_prueba,
        mae_climatologia=mae_ref,
        destreza=float(1.0 - mae / mae_ref) if mae_ref > 0 else 0.0,
    )


def predecir(
    df: pd.DataFrame,
    columna: str = "temp_c.prom",
    col_tiempo: str = "t_fin",
    horas: float = 24.0,
    intervalo_min: int = INTERVALO_MIN_DEFECTO,
    n_armonicos: int = 3,
    confianza: float = 0.95,
    validar: bool = True,
) -> Prediccion | None:
    """Pronostica la variable con banda de incertidumbre.

    La especificación del modelo —con o sin término de tendencia— la decide
    `detectar_tendencia`, de modo que la predicción no incorpore una deriva
    que los datos no sostienen. Extrapolar una tendencia espuria es el modo de
    fallo más frecuente en el pronóstico de series ambientales cortas.
    """
    d = df[[col_tiempo, columna]].dropna().sort_values(col_tiempo).reset_index(drop=True)
    if len(d) < 200:
        return None

    contraste = detectar_tendencia(df, columna, col_tiempo)
    con_tendencia = bool(contraste["recomendada"])

    try:
        modelo = ajustar_ciclo_diurno(df, columna, col_tiempo,
                                      n_armonicos=n_armonicos,
                                      con_tendencia=con_tendencia)
    except (ValueError, np.linalg.LinAlgError):
        return None

    acf = autocorrelacion(modelo.residual, max_rezago=min(576, len(d) // 2))
    tau = float(tiempo_decorrelacion(acf, intervalo_min * 60).get("minutos", np.nan))

    coef, t0, sigma = _coeficientes(df, columna, col_tiempo,
                                    n_armonicos, con_tendencia)

    t_ultimo = d[col_tiempo].iloc[-1]
    futuro = pd.Series(pd.date_range(
        t_ultimo + pd.Timedelta(minutes=intervalo_min),
        periods=int(horas * 60 / intervalo_min),
        freq=f"{intervalo_min}min",
    ))

    X = _matriz_diseno(futuro, t0, n_armonicos, con_tendencia)
    esperado = X @ coef

    z = float(stats.norm.ppf(0.5 + confianza / 2))
    banda = z * sigma

    advertencias = []
    if np.isfinite(tau) and horas * 60 > tau:
        advertencias.append(
            f"El horizonte solicitado ({horas:.0f} h) excede el tiempo de "
            f"decorrelación ({tau:.0f} min). Más allá de ese punto la predicción "
            "converge al ciclo climatológico y no incorpora información del "
            "estado presente."
        )
    if con_tendencia:
        advertencias.append(
            f"La predicción extrapola una deriva de {modelo.pendiente_dia:+.3f} "
            "°C/día. La extrapolación lineal pierde validez con el horizonte."
        )
    if len(d) < 288 * 7:
        advertencias.append(
            f"El ajuste emplea {len(d) / 288:.1f} días de registro; la estimación "
            "del ciclo diurno gana estabilidad con series más extensas."
        )

    val = None
    if validar:
        val = validar_fuera_de_muestra(df, columna, col_tiempo,
                                       horas_prueba=min(horas, 24.0),
                                       n_armonicos=n_armonicos,
                                       con_tendencia=con_tendencia,
                                       confianza=confianza)

    return Prediccion(
        tiempo=futuro,
        esperado=esperado,
        inferior=esperado - banda,
        superior=esperado + banda,
        sigma=sigma,
        con_tendencia=con_tendencia,
        horizonte_h=horas,
        tau_min=tau,
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
    magnitud: str = ""      # beneficio o severidad, cuando es cuantificable


def _cadencia_sugerida(tau_min: float, intervalo_min: int) -> int:
    """Cadencia de transmisión compatible con la dinámica observada.

    Se adopta τ/3 como regla operativa: preserva holgadamente la dinámica del
    proceso —tres muestras por tiempo característico— sin incurrir en la
    redundancia de un muestreo mucho más denso. El valor se redondea a un
    múltiplo de cinco minutos por conveniencia de implementación.
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
    del instrumento, suficiencia de la serie y validez del modelo. No se emiten
    recomendaciones sobre el fenómeno ambiental, que exigirían una cadena de
    medición calibrada y trazable.

    Las recomendaciones se ordenan por prioridad para que la más consecuente
    encabece la lista.
    """
    recs: list[Recomendacion] = []

    # --- Energía: cadencia de transmisión ---
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
                    f"El residual se decorrelaciona en {tau:.0f} min, de modo que "
                    f"el muestreo actual cada {intervalo_min} min produce "
                    f"observaciones redundantes. Una cadencia de {sugerida} min "
                    "conserva tres muestras por tiempo característico del proceso."
                ),
                magnitud=f"−{ahorro:.0f} % de transmisiones",
            ))

    # --- Mantenimiento: integridad del instrumento ---
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
                f"El mínimo observado es de {diagnostico.get('heap_min', 0):.0f} B. "
                "El establecimiento de la conexión TLS opera cerca del límite "
                "disponible, lo que aconseja migrar a una plataforma con mayor "
                "memoria antes de ampliar la funcionalidad."
            ),
            magnitud=f"{diagnostico.get('heap_min', 0):.0f} B libres",
        ))

    # --- Calidad del registro ---
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
                f"esperadas. La deriva del temporizador respecto al reloj explica "
                f"la ausencia de {perdida} muestra(s) por intervalo, sin "
                "consecuencia apreciable sobre los estadísticos."
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
                    f"({v.mae_climatologia:.2f} °C). El ciclo diurno estimado no "
                    "está aportando capacidad predictiva sobre este tramo."
                ),
                magnitud=f"destreza {v.destreza:+.2f}",
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
                    f"intervalo, frente al {v.cobertura_nominal:.0%} nominal. La "
                    "dispersión residual no describe adecuadamente el error de "
                    "predicción, probablemente por heterogeneidad entre jornadas."
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
                f"Las pendientes por bloque presentan un coeficiente de "
                f"variación de {contraste.get('cv_bloques', 0):.2f}, señal de "
                "heterogeneidad meteorológica antes que de deriva. Incorporar "
                "una covariable de nubosidad o radiación permitiría explicarla."
            ),
            magnitud=f"CV = {contraste.get('cv_bloques', 0):.2f}",
        ))

    # Calibración: siempre pendiente mientras no exista co-ubicación.
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
