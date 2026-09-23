"""Descomposición de series ambientales en componentes interpretables.

Una serie de temperatura urbana está dominada por el ciclo diurno. Presentarla
sin descomponer comunica sobre todo lo que el lector ya sabe: que hace más
calor de día. La información está en lo que el ciclo no explica.

El modelo admite además un término de tendencia lineal. Su inclusión no es
cosmética: una serie de campo rara vez es estacionaria, y si la deriva de
fondo no se modela explícitamente queda absorbida por el residual, inflando
la dispersión aparente y distorsionando la estimación del tiempo de
decorrelación, que pasa a medir la tendencia en lugar de la persistencia.

Modelo:

    y(t) = a₀ + b·t + Σₖ [aₖ·cos(2πkh/24) + bₖ·sen(2πkh/24)] + ε

donde *h* es la hora local decimal y *t* el tiempo transcurrido en días.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

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
        """Contraste aproximado de pendiente nula al 95 % de confianza.

        Se compara la estimación con dos veces su error estándar. El criterio
        es orientativo: la autocorrelación del residual reduce los grados de
        libertad efectivos y el error estándar nominal subestima el real.
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
        Incorpora un término lineal en el tiempo. Debe activarse cuando la
        serie presenta deriva de fondo; en caso contrario, esa deriva se
        traslada íntegramente al residual.

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

    # Amplitud del primer armónico: magnitud característica del ciclo diurno.
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


def detectar_tendencia(
    df: pd.DataFrame,
    columna: str = "temp_c.prom",
    col_tiempo: str = "t_fin",
    umbral_c_dia: float = 0.10,
) -> dict[str, float | bool]:
    """Evalúa si la serie justifica incorporar un término de tendencia.

    Compara el ajuste con y sin deriva lineal. El criterio combina dos
    condiciones: que la pendiente supere un umbral de relevancia práctica y
    que la reducción de dispersión residual sea apreciable. Exigir ambas evita
    tanto modelar ruido como ignorar derivas reales.
    """
    try:
        sin_t = ajustar_ciclo_diurno(df, columna, col_tiempo, con_tendencia=False)
        con_t = ajustar_ciclo_diurno(df, columna, col_tiempo, con_tendencia=True)
    except (ValueError, np.linalg.LinAlgError):
        return {"recomendada": False, "pendiente_dia": 0.0,
                "mejora_sigma": 0.0, "significativa": False}

    mejora = ((sin_t.sigma_residual - con_t.sigma_residual) / sin_t.sigma_residual
              if sin_t.sigma_residual > 0 else 0.0)

    return {
        "recomendada": bool(
            abs(con_t.pendiente_dia) > umbral_c_dia
            and mejora > 0.05
            and con_t.pendiente_significativa
        ),
        "pendiente_dia": con_t.pendiente_dia,
        "pendiente_ee": con_t.pendiente_ee,
        "significativa": con_t.pendiente_significativa,
        "mejora_sigma": mejora,
        "sigma_sin": sin_t.sigma_residual,
        "sigma_con": con_t.sigma_residual,
        "r2_sin": sin_t.varianza_explicada,
        "r2_con": con_t.varianza_explicada,
    }


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
