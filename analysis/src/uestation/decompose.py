"""Descomposición de series ambientales en componentes interpretables.

Una serie de temperatura urbana está dominada por el ciclo diurno. Presentarla
sin descomponer comunica sobre todo lo que el lector ya sabe: que hace más
calor de día. La información está en lo que el ciclo no explica.

El modelo admite además un término de tendencia lineal. Su inclusión no es
cosmética: una serie de campo rara vez es estacionaria, y si la deriva de
fondo no se modela explícitamente queda absorbida por el residual, inflando
la dispersión aparente y distorsionando la estimación del tiempo de
decorrelación, que pasa a medir la tendencia en lugar de la persistencia.

Ahora bien, incorporar una tendencia inexistente es un error simétrico y más
grave, porque produce una afirmación positiva infundada. Por ello la decisión
se delega a `detectar_tendencia`, que somete la pendiente a tres criterios
independientes antes de recomendarla.

Modelo:

    y(t) = a₀ + b·t + Σₖ [aₖ·cos(2πkh/24) + bₖ·sen(2πkh/24)] + ε

donde *h* es la hora local decimal y *t* el tiempo transcurrido en días.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

TZ_LOCAL = "America/Bogota"


@dataclass
class Descomposicion:
    """Resultado de separar una serie en tendencia, ciclo diurno y residual.

    El atributo `ciclo` contiene la componente determinista completa
    (tendencia más armónicos), de modo que `observado = ciclo + residual` se
    cumple por construcción, con y sin término de tendencia.
    """

    tiempo: pd.Series
    observado: pd.Series
    ciclo: pd.Series
    residual: pd.Series
    sigma_residual: float
    varianza_explicada: float
    n_armonicos: int
    con_tendencia: bool = False
    tendencia: pd.Series | None = None
    pendiente_dia: float = 0.0
    pendiente_ee: float = 0.0
    amplitud_diurna: float = 0.0

    @property
    def banda_superior(self) -> pd.Series:
        return self.ciclo + 2.0 * self.sigma_residual

    @property
    def banda_inferior(self) -> pd.Series:
        return self.ciclo - 2.0 * self.sigma_residual

    def anomalias(self, k: float = 2.0) -> pd.Series:
        """Marca observaciones fuera de ±k·sigma de la componente determinista."""
        return self.residual.abs() > k * self.sigma_residual

    @property
    def pendiente_significativa(self) -> bool:
        """Contraste nominal de pendiente nula al 95 % de confianza.

        Se compara la estimación con dos veces su error estándar. **Este
        criterio no corrige por autocorrelación** y, en series de muestreo
        denso, resulta excesivamente permisivo. Para decidir la inclusión de
        una tendencia debe emplearse `detectar_tendencia`.
        """
        if not self.con_tendencia or self.pendiente_ee == 0:
            return False
        return abs(self.pendiente_dia) > 2.0 * self.pendiente_ee


def ajustar_ciclo_diurno(
    df: pd.DataFrame,
    columna: str,
    col_tiempo: str = "t_fin",
    n_armonicos: int = 3,
    con_tendencia: bool = False,
) -> Descomposicion:
    """Ajusta por mínimos cuadrados un modelo armónico del ciclo diurno.

    Se prefiere un ajuste armónico a un promedio por hora porque impone
    continuidad y periodicidad exacta, y estima menos parámetros: con tres
    armónicos son siete coeficientes frente a los veinticuatro de un promedio
    horario. Menos parámetros implica menor riesgo de absorber ruido en la
    componente supuestamente determinista.

    Parameters
    ----------
    con_tendencia
        Incorpora un término lineal en el tiempo. Debe activarse únicamente
        cuando `detectar_tendencia` confirme la deriva; en caso contrario se
        introduce una componente espuria.

    Raises
    ------
    ValueError
        Si la serie no aporta observaciones suficientes para el número de
        parámetros solicitado.
    """
    d = df[[col_tiempo, columna]].dropna().sort_values(col_tiempo).reset_index(drop=True)

    n_param = 1 + 2 * n_armonicos + (1 if con_tendencia else 0)
    if len(d) < n_param + 4:
        raise ValueError(
            f"Se requieren al menos {n_param + 4} observaciones; se recibieron {len(d)}."
        )

    t = d[col_tiempo]
    local = t.dt.tz_convert(TZ_LOCAL) if t.dt.tz is not None else t

    # Hora decimal del día: variable del término periódico.
    h = (local.dt.hour + local.dt.minute / 60.0
         + local.dt.second / 3600.0).to_numpy(dtype=float)

    # Días transcurridos desde el inicio: variable del término de tendencia.
    dias = ((t - t.iloc[0]).dt.total_seconds() / 86400.0).to_numpy(dtype=float)

    y = d[columna].to_numpy(dtype=float)

    # Matriz de diseño
    cols = [np.ones_like(h)]
    idx_pendiente = None
    if con_tendencia:
        idx_pendiente = len(cols)
        cols.append(dias)
    for k in range(1, n_armonicos + 1):
        cols.append(np.cos(2 * np.pi * k * h / 24.0))
        cols.append(np.sin(2 * np.pi * k * h / 24.0))
    X = np.column_stack(cols)

    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    ajuste = X @ coef
    residual = y - ajuste

    gl = max(len(y) - X.shape[1], 1)
    var_resid = float(np.sum(residual**2) / gl)

    var_total = float(np.var(y, ddof=1))
    var_explicada = (1.0 - float(np.var(residual, ddof=1)) / var_total
                     if var_total > 0 else 0.0)

    # Amplitud pico a pico del primer armónico: magnitud característica del ciclo.
    i0 = 2 if con_tendencia else 1
    amplitud = float(2.0 * np.hypot(coef[i0], coef[i0 + 1]))

    pendiente = ee_pendiente = 0.0
    serie_tendencia = None
    if con_tendencia:
        pendiente = float(coef[idx_pendiente])
        # Error estándar del coeficiente: raíz del elemento diagonal
        # correspondiente en la matriz de covarianza var_resid·(XᵀX)⁻¹.
        try:
            cov = var_resid * np.linalg.inv(X.T @ X)
            ee_pendiente = float(np.sqrt(cov[idx_pendiente, idx_pendiente]))
        except np.linalg.LinAlgError:
            ee_pendiente = 0.0
        serie_tendencia = pd.Series(coef[0] + pendiente * dias, index=d.index)

    return Descomposicion(
        tiempo=t,
        observado=pd.Series(y, index=d.index),
        ciclo=pd.Series(ajuste, index=d.index),
        residual=pd.Series(residual, index=d.index),
        sigma_residual=float(np.sqrt(var_resid)),
        varianza_explicada=var_explicada,
        n_armonicos=n_armonicos,
        con_tendencia=con_tendencia,
        tendencia=serie_tendencia,
        pendiente_dia=pendiente,
        pendiente_ee=ee_pendiente,
        amplitud_diurna=amplitud,
    )


def _autocorrelacion_lag1(x: np.ndarray) -> float:
    """Autocorrelación de primer orden de una serie."""
    if len(x) < 3:
        return 0.0
    c = x - x.mean()
    den = float(np.dot(c, c))
    if den == 0:
        return 0.0
    return float(np.dot(c[:-1], c[1:]) / den)


def _n_efectivo(n: int, rho: float) -> float:
    """Tamaño de muestra efectivo ante autocorrelación de primer orden.

        n_ef ≈ n · (1 − ρ) / (1 + ρ)

    Aproximación estándar para procesos AR(1). Observaciones correlacionadas
    aportan menos información independiente de la que sugiere su número: sin
    esta corrección, el error estándar nominal subestima el real y casi
    cualquier pendiente resulta «significativa» en series largas.
    """
    rho = float(np.clip(rho, -0.99, 0.99))
    return max(n * (1.0 - rho) / (1.0 + rho), 3.0)


def detectar_tendencia(
    df: pd.DataFrame,
    columna: str = "temp_c.prom",
    col_tiempo: str = "t_fin",
    umbral_c_dia: float = 0.10,
    n_bloques: int = 4,
    fraccion_consistente: float = 0.75,
    cv_maximo: float = 0.60,
    razon_maxima: float = 2.0,
) -> dict:
    """Contrasta la presencia de una deriva sistemática en la serie.

    Se exige la satisfacción simultánea de tres criterios:

    1. **Relevancia práctica.** La pendiente supera `umbral_c_dia`. Una deriva
       por debajo de ese valor carece de consecuencia interpretativa aunque
       resulte estadísticamente detectable.

    2. **Significancia corregida por autocorrelación.** El error estándar
       nominal se infla por el factor √(n/n_ef), con n_ef el tamaño de muestra
       efectivo estimado desde la autocorrelación de primer orden del residual.
       El estadístico resultante se contrasta contra el valor crítico de t con
       los grados de libertad efectivos, no contra el 1.96 asintótico: con
       autocorrelación elevada n_ef es reducido y el umbral correcto es mayor.

    3. **Homogeneidad entre bloques.** La serie se divide en `n_bloques` tramos
       y se ajusta el modelo en cada uno. Se exige coincidencia de signo,
       coeficiente de variación de las pendientes locales inferior a
       `cv_maximo`, y que ninguna exceda `razon_maxima` veces la global.

       El signo por sí solo no discrimina una rampa sostenida de una serie que
       oscila en torno a cero: basta con que los extremos queden desplazados
       para que el ajuste global produzca pendiente aparente. El coeficiente
       de variación distingue ambos casos, porque en una deriva genuina los
       bloques reproducen la pendiente global y su dispersión es pequeña
       frente a la magnitud estimada.

    El tercer criterio responde al principio que motiva la estratificación
    obligatoria del protocolo §6.3: un estadístico global que no sobrevive a
    la partición de la muestra no constituye un hallazgo.

    Returns
    -------
    dict
        `recomendada` resume el contraste; `motivo` explicita la razón de la
        decisión. Los campos restantes documentan cada criterio por separado,
        de modo que el resultado sea auditable.
    """
    base = {
        "recomendada": False,
        "pendiente_dia": 0.0,
        "pendiente_ee_nominal": 0.0,
        "pendiente_ee_corregido": 0.0,
        "razon_senal_ruido": 0.0,
        "t_critico": 0.0,
        "gl_efectivos": 0.0,
        "rho_lag1": 0.0,
        "n_observaciones": 0,
        "n_efectivo": 0.0,
        "supera_umbral": False,
        "significativa_corregida": False,
        "bloques_pendientes": [],
        "bloques_consistentes": 0,
        "n_bloques_validos": 0,
        "consistente": False,
        "homogenea": False,
        "dispersion_bloques": 0.0,
        "cv_bloques": 0.0,
        "mejora_sigma": 0.0,
        "sigma_sin": np.nan,
        "sigma_con": np.nan,
        "r2_sin": np.nan,
        "r2_con": np.nan,
        "motivo": "serie insuficiente",
    }

    try:
        sin_t = ajustar_ciclo_diurno(df, columna, col_tiempo, con_tendencia=False)
        con_t = ajustar_ciclo_diurno(df, columna, col_tiempo, con_tendencia=True)
    except (ValueError, np.linalg.LinAlgError):
        return base

    # --- Criterio 2: significancia corregida por autocorrelación ---
    n = len(con_t.residual)
    rho = _autocorrelacion_lag1(con_t.residual.to_numpy(dtype=float))
    n_ef = _n_efectivo(n, rho)

    # El error estándar escala con la raíz del tamaño de muestra.
    ee_corr = con_t.pendiente_ee * np.sqrt(n / n_ef) if n_ef > 0 else np.inf
    rsr = abs(con_t.pendiente_dia) / ee_corr if ee_corr > 0 else 0.0

    gl_ef = max(n_ef - 2.0, 1.0)
    t_critico = float(stats.t.ppf(0.975, gl_ef))
    significativa = rsr > t_critico

    mejora = ((sin_t.sigma_residual - con_t.sigma_residual) / sin_t.sigma_residual
              if sin_t.sigma_residual > 0 else 0.0)

    # --- Criterio 3: homogeneidad entre bloques ---
    d = df[[col_tiempo, columna]].dropna().sort_values(col_tiempo).reset_index(drop=True)
    t0, t1 = d[col_tiempo].iloc[0], d[col_tiempo].iloc[-1]
    bordes = pd.date_range(t0, t1, periods=n_bloques + 1)

    pendientes = []
    for i in range(n_bloques):
        tramo = d[(d[col_tiempo] >= bordes[i]) & (d[col_tiempo] < bordes[i + 1])]
        try:
            m = ajustar_ciclo_diurno(tramo, columna, col_tiempo, con_tendencia=True)
            pendientes.append(round(float(m.pendiente_dia), 4))
        except (ValueError, np.linalg.LinAlgError):
            continue

    signo_global = np.sign(con_t.pendiente_dia)
    coincidentes = sum(1 for p in pendientes if np.sign(p) == signo_global)

    if len(pendientes) >= 2 and con_t.pendiente_dia != 0:
        arr = np.array(pendientes, dtype=float)
        dispersion_bloques = float(np.std(arr, ddof=1))
        cv_bloques = dispersion_bloques / abs(con_t.pendiente_dia)
        razon = np.abs(arr / con_t.pendiente_dia)
        homogenea = bool(cv_bloques < cv_maximo and razon.max() < razon_maxima)
    else:
        homogenea = False
        dispersion_bloques = 0.0
        cv_bloques = float("inf")

    mismo_signo = (len(pendientes) >= 2
                   and coincidentes / len(pendientes) >= fraccion_consistente)
    consistente = mismo_signo and homogenea

    supera = abs(con_t.pendiente_dia) > umbral_c_dia

    if not supera:
        motivo = f"pendiente por debajo del umbral de relevancia ({umbral_c_dia} °C/día)"
    elif not significativa:
        motivo = (f"no significativa al corregir por autocorrelación "
                  f"(t = {rsr:.2f} ≤ {t_critico:.2f} con {gl_ef:.0f} gl efectivos)")
    elif not mismo_signo:
        motivo = (f"signo inconsistente entre bloques "
                  f"({coincidentes} de {len(pendientes)})")
    elif not homogenea:
        motivo = (f"pendientes locales heterogéneas (CV = {cv_bloques:.2f}): "
                  "el comportamiento sugiere variabilidad meteorológica antes "
                  "que una deriva sostenida")
    else:
        motivo = "deriva sistemática confirmada por los tres criterios"

    base.update({
        "recomendada": bool(supera and significativa and consistente),
        "pendiente_dia": con_t.pendiente_dia,
        "pendiente_ee_nominal": con_t.pendiente_ee,
        "pendiente_ee_corregido": float(ee_corr),
        "razon_senal_ruido": float(rsr),
        "t_critico": t_critico,
        "gl_efectivos": float(gl_ef),
        "rho_lag1": rho,
        "n_observaciones": n,
        "n_efectivo": float(n_ef),
        "supera_umbral": bool(supera),
        "significativa_corregida": bool(significativa),
        "bloques_pendientes": pendientes,
        "bloques_consistentes": coincidentes,
        "n_bloques_validos": len(pendientes),
        "consistente": bool(consistente),
        "homogenea": homogenea,
        "dispersion_bloques": dispersion_bloques,
        "cv_bloques": float(cv_bloques),
        "mejora_sigma": mejora,
        "sigma_sin": sin_t.sigma_residual,
        "sigma_con": con_t.sigma_residual,
        "r2_sin": sin_t.varianza_explicada,
        "r2_con": con_t.varianza_explicada,
        "motivo": motivo,
    })
    return base


def variabilidad_diaria(
    df: pd.DataFrame,
    columna: str = "temp_c.prom",
    col_tiempo: str = "t_fin",
    n_armonicos: int = 3,
    cobertura_minima: int = 200,
) -> pd.DataFrame:
    """Caracteriza día a día el ajuste del ciclo diurno.

    Ajusta el modelo sobre la serie completa y resume el residual por jornada
    local. Una dispersión residual que varía entre días indica que la amplitud
    del ciclo no es constante: bajo cielo despejado la oscilación térmica
    diaria supera a la observada con cobertura nubosa.

    El sesgo diario, media del residual, identifica jornadas atípicas respecto
    al comportamiento medio del período. A diferencia de una tendencia, estas
    desviaciones no siguen una dirección sostenida.
    """
    m = ajustar_ciclo_diurno(df, columna, col_tiempo, n_armonicos=n_armonicos)

    d = df[[col_tiempo, columna]].dropna().sort_values(col_tiempo).reset_index(drop=True)
    local = (d[col_tiempo].dt.tz_convert(TZ_LOCAL)
             if d[col_tiempo].dt.tz is not None else d[col_tiempo])

    r = pd.DataFrame({
        "fecha": local.dt.date,
        "residual": m.residual.to_numpy(dtype=float),
        "observado": m.observado.to_numpy(dtype=float),
    })

    g = r.groupby("fecha")
    out = pd.DataFrame({
        "n": g["residual"].count(),
        "sesgo": g["residual"].mean(),
        "dispersion": g["residual"].std(ddof=1),
        "amplitud": g["observado"].max() - g["observado"].min(),
        "media": g["observado"].mean(),
    }).reset_index()

    # Solo jornadas con cobertura suficiente para que el resumen sea comparable.
    return out[out["n"] >= cobertura_minima].reset_index(drop=True)


def autocorrelacion(serie: pd.Series, max_rezago: int = 288) -> pd.DataFrame:
    """Función de autocorrelación con banda de significancia.

    La banda ±1.96/√n delimita el rango compatible con ruido blanco. Los
    rezagos que la superan indican estructura temporal remanente.
    """
    x = serie.dropna().to_numpy(dtype=float)
    n = len(x)
    if n < 10:
        return pd.DataFrame(columns=["rezago", "acf", "banda"])

    max_rezago = min(max_rezago, n // 2)
    x = x - x.mean()
    denom = np.dot(x, x)

    rezagos = np.arange(max_rezago + 1)
    acf = np.array([np.dot(x[: n - k], x[k:]) / denom for k in rezagos])

    return pd.DataFrame({"rezago": rezagos, "acf": acf, "banda": 1.96 / np.sqrt(n)})


def tiempo_decorrelacion(acf: pd.DataFrame, intervalo_s: int = 300) -> dict[str, float]:
    """Primer rezago en que la autocorrelación cae por debajo de 1/e.

    Interpretación operativa: muestrear a intervalos menores que este tiempo
    produce observaciones redundantes; muestrear a intervalos mayores pierde
    dinámica. Es un criterio de diseño, no un descriptivo.

    Advertencia: aplicado a un residual con tendencia no modelada, el valor
    obtenido refleja la deriva de fondo y no la persistencia del proceso.
    """
    if acf.empty:
        return {"rezago": np.nan, "minutos": np.nan}

    umbral = 1.0 / np.e
    debajo = acf.loc[acf["acf"] < umbral, "rezago"]
    if debajo.empty:
        return {"rezago": np.nan, "minutos": np.nan}

    k = int(debajo.iloc[0])
    return {"rezago": k, "minutos": k * intervalo_s / 60.0}


def matriz_hora_dia(
    df: pd.DataFrame,
    columna: str,
    col_tiempo: str = "t_fin",
    agregacion: str = "mean",
) -> pd.DataFrame:
    """Tabla hora del día × fecha, para inspección visual de patrones.

    Revela simultáneamente la regularidad del ciclo diurno y las
    discontinuidades de cobertura: una celda vacía es un intervalo ausente.
    """
    d = df[[col_tiempo, columna]].dropna().copy()
    local = (
        d[col_tiempo].dt.tz_convert(TZ_LOCAL)
        if d[col_tiempo].dt.tz is not None
        else d[col_tiempo]
    )
    d["fecha"] = local.dt.date
    d["hora"] = local.dt.hour

    return d.pivot_table(index="hora", columns="fecha", values=columna,
                         aggfunc=agregacion)


def incertidumbre_expandida(
    df: pd.DataFrame,
    variable: str = "temp_c",
    k: float = 2.0,
) -> dict[str, float]:
    """Incertidumbre expandida a partir de la dispersión intra-intervalo.

    Combina la dispersión observada dentro de cada intervalo con el error
    estándar de la media. **No incluye** la incertidumbre de calibración, que
    permanece indeterminada mientras no exista co-ubicación con referencia:
    el valor devuelto es por tanto una cota inferior de la incertidumbre real.
    """
    c_min, c_max = f"{variable}.min", f"{variable}.max"
    c_n = f"{variable}.n"

    if not {c_min, c_max, c_n} <= set(df.columns):
        return {}

    d = df[[c_min, c_max, c_n]].dropna()
    if d.empty:
        return {}

    # Estimación de sigma desde el rango, factor d2 para n ≈ 150.
    sigma = (d[c_max] - d[c_min]) / 5.3
    n = d[c_n]

    u_a = sigma / np.sqrt(n)  # tipo A: error estándar de la media

    return {
        "sigma_intra_mediana": float(sigma.median()),
        "u_estandar_mediana": float(u_a.median()),
        "U_expandida_k2": float(k * u_a.median()),
        "k": k,
        "nota": "Excluye incertidumbre de calibración (pendiente de co-ubicación).",
    }
