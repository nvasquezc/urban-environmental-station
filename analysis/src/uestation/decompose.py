"""Descomposición de series ambientales en componente previsible y residual.

Una serie de temperatura urbana está dominada por el ciclo diurno. Presentarla
sin descomponer comunica sobre todo lo que el lector ya sabe: que hace más
calor de día. La información está en el residual.

Este módulo separa ambas componentes y caracteriza la estructura temporal de
lo que queda, con dos propósitos:

1. Detectar anomalías sobre una línea base estadísticamente fundada, no sobre
   umbrales arbitrarios.
2. Determinar el tiempo de decorrelación, que condiciona el intervalo de
   muestreo mínimo necesario para que cada observación aporte información nueva.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TZ_LOCAL = "America/Bogota"


@dataclass
class Descomposicion:
    """Resultado de separar una serie en ciclo diurno y residual."""

    tiempo: pd.Series
    observado: pd.Series
    ciclo: pd.Series
    residual: pd.Series
    sigma_residual: float
    varianza_explicada: float
    n_armonicos: int

    @property
    def banda_superior(self) -> pd.Series:
        return self.ciclo + 2.0 * self.sigma_residual

    @property
    def banda_inferior(self) -> pd.Series:
        return self.ciclo - 2.0 * self.sigma_residual

    def anomalias(self, k: float = 2.0) -> pd.Series:
        """Marca observaciones fuera de ±k·sigma del ciclo esperado."""
        return (self.residual.abs() > k * self.sigma_residual)


def ajustar_ciclo_diurno(
    df: pd.DataFrame,
    columna: str,
    col_tiempo: str = "t_fin",
    n_armonicos: int = 3,
) -> Descomposicion:
    """Ajusta un modelo armónico del ciclo diurno por mínimos cuadrados.

    El modelo es una serie de Fourier truncada sobre la hora local:

        y(t) = a₀ + Σₖ [aₖ·cos(2πkt/24) + bₖ·sen(2πkt/24)] + ε

    Se prefiere un ajuste armónico a un promedio por hora porque impone
    continuidad y periodicidad exacta, y estima menos parámetros: con tres
    armónicos son siete coeficientes frente a los veinticuatro de un promedio
    horario. Menos parámetros implica menor riesgo de absorber ruido en la
    componente supuestamente determinista.

    El residual resultante es la serie de interés: lo que el ciclo diurno no
    explica.
    """
    d = df[[col_tiempo, columna]].dropna().sort_values(col_tiempo).reset_index(drop=True)
    if len(d) < 4 * n_armonicos + 2:
        raise ValueError("Serie demasiado corta para el número de armónicos solicitado.")

    t = d[col_tiempo]
    local = t.dt.tz_convert(TZ_LOCAL) if t.dt.tz is not None else t
    # Hora decimal del día: variable independiente del modelo.
    h = local.dt.hour + local.dt.minute / 60.0 + local.dt.second / 3600.0

    y = d[columna].to_numpy(dtype=float)

    # Matriz de diseño: término constante más pares seno/coseno.
    cols = [np.ones_like(h.to_numpy(dtype=float))]
    for k in range(1, n_armonicos + 1):
        cols.append(np.cos(2 * np.pi * k * h / 24.0))
        cols.append(np.sin(2 * np.pi * k * h / 24.0))
    X = np.column_stack(cols)

    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    ciclo = X @ coef
    residual = y - ciclo

    var_total = float(np.var(y, ddof=1))
    var_explicada = 1.0 - float(np.var(residual, ddof=1)) / var_total if var_total > 0 else 0.0

    return Descomposicion(
        tiempo=t,
        observado=pd.Series(y, index=d.index),
        ciclo=pd.Series(ciclo, index=d.index),
        residual=pd.Series(residual, index=d.index),
        sigma_residual=float(np.std(residual, ddof=len(coef))),
        varianza_explicada=var_explicada,
        n_armonicos=n_armonicos,
    )


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

    return pd.DataFrame(
        {"rezago": rezagos, "acf": acf, "banda": 1.96 / np.sqrt(n)}
    )


def tiempo_decorrelacion(acf: pd.DataFrame, intervalo_s: int = 300) -> dict[str, float]:
    """Primer rezago en que la autocorrelación cae por debajo de 1/e.

    Interpretación operativa: muestrear a intervalos menores que este tiempo
    produce observaciones redundantes; muestrear a intervalos mayores pierde
    dinámica. Es un criterio de diseño, no un descriptivo.
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

    return d.pivot_table(
        index="hora", columns="fecha", values=columna, aggfunc=agregacion
    )


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

    u_a = sigma / np.sqrt(n)          # tipo A: error estándar de la media

    return {
        "sigma_intra_mediana": float(sigma.median()),
        "u_estandar_mediana": float(u_a.median()),
        "U_expandida_k2": float(k * u_a.median()),
        "k": k,
        "nota": "Excluye incertidumbre de calibración (pendiente de co-ubicación).",
    }
