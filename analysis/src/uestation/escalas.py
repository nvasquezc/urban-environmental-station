"""Separación de escalas temporales en el residual del ciclo diurno.

El residual de un modelo de ciclo diurno no es homogéneo en escala. Contiene
dos componentes de naturaleza distinta:

1. **Sinóptica.** Regímenes de varios días —jornadas despejadas frente a
   nubladas, frentes, cambios de masa de aire— que desplazan el nivel medio
   de la temperatura durante días enteros.

2. **Intradiaria.** Desviaciones de horas respecto al comportamiento esperado
   de cada jornada: paso de nubes, ráfagas, eventos locales.

Sin separarlas, cualquier estadístico de persistencia queda dominado por la
componente sinóptica. El tiempo de decorrelación del residual completo crece
entonces con la longitud del registro, porque cada jornada adicional incorpora
más variabilidad de baja frecuencia: un indicio inequívoco de que no se está
midiendo una propiedad del proceso sino del período observado.

La separación se realiza mediante un filtro pasa altos: la componente
sinóptica es la media móvil centrada de 24 h y la intradiaria su complemento.
Una ventana de 24 h elimina por construcción cualquier remanente del ciclo
diurno en la componente sinóptica.

Las autocorrelaciones se calculan sobre una rejilla temporal regular con
huecos explícitos: calcular rezagos por posición sobre una serie con
interrupciones emparejaría observaciones separadas por horas como si fueran
consecutivas.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from uestation.decompose import Descomposicion, tiempo_decorrelacion

TZ_LOCAL = "America/Bogota"


@dataclass
class Escalas:
    """Resultado de separar el residual en componentes sinóptica e intradiaria."""

    residual: pd.Series
    intradiario: pd.Series
    sinoptico: pd.Series
    var_intradiaria: float
    var_sinoptica: float
    fraccion_sinoptica: float
    acf_total: pd.DataFrame
    acf_intradiaria: pd.DataFrame
    tau_total_min: float
    tau_intradiario_min: float
    rho_diario: float
    n_dias: int
    ventana_h: float


def a_rejilla(tiempo, valores, intervalo_min: int = 5) -> pd.Series:
    """Proyecta la serie sobre una rejilla regular con huecos explícitos.

    Los intervalos ausentes quedan como NaN en lugar de desaparecer, de modo
    que los rezagos se midan en tiempo y no en posición.
    """
    idx = pd.DatetimeIndex(pd.to_datetime(tiempo))
    s = pd.Series(np.asarray(valores, dtype=float), index=idx)
    s = s[~s.index.duplicated(keep="first")].sort_index()
    if s.empty:
        return s
    rejilla = pd.date_range(s.index[0], s.index[-1], freq=f"{intervalo_min}min")
    return s.reindex(rejilla)


def autocorrelacion_con_huecos(s: pd.Series, max_rezago: int) -> pd.DataFrame:
    """Autocorrelación sobre rejilla regular, ignorando pares incompletos.

    Para cada rezago se emplean solo los pares en que ambas observaciones
    existen. La banda de significancia se calcula con el número de
    observaciones válidas.
    """
    x = s.to_numpy(dtype=float)
    validos = np.isfinite(x)
    n = int(validos.sum())
    vacio = pd.DataFrame(columns=["rezago", "acf", "banda"])
    if n < 10:
        return vacio

    x = x - np.nanmean(x)
    var = float(np.nanmean(x**2))
    if var == 0:
        return vacio

    max_rezago = min(max_rezago, len(x) // 2)
    acf = np.full(max_rezago + 1, np.nan)
    acf[0] = 1.0
    for k in range(1, max_rezago + 1):
        a, b = x[:-k], x[k:]
        m = np.isfinite(a) & np.isfinite(b)
        if m.sum() > 10:
            acf[k] = float(np.mean(a[m] * b[m]) / var)

    return pd.DataFrame({
        "rezago": np.arange(max_rezago + 1),
        "acf": acf,
        "banda": 1.96 / np.sqrt(n),
    })


def separar_escalas(
    d: Descomposicion,
    intervalo_min: int = 5,
    ventana_h: float = 24.0,
    max_rezago_total_h: float = 96.0,
    max_rezago_intra_h: float = 24.0,
) -> Escalas:
    """Separa el residual en componentes sinóptica e intradiaria.

    Parameters
    ----------
    d
        Descomposición previa del ciclo diurno.
    ventana_h
        Anchura de la media móvil centrada que define la componente
        sinóptica. Con 24 h coincide con el período del ciclo diurno y no
        deja remanente de éste.

    Notes
    -----
    La fracción sinóptica se calcula como var_s / (var_s + var_i). No es una
    partición exacta de la varianza, porque ambas componentes no son
    estrictamente ortogonales, pero cuantifica de forma interpretable qué
    proporción de la dispersión residual corresponde a regímenes de varios
    días.

    Raises
    ------
    ValueError
        Si la serie no cubre al menos dos jornadas, mínimo para que la media
        móvil de 24 h sea representativa.
    """
    s = a_rejilla(d.tiempo, d.residual.to_numpy(), intervalo_min)
    por_dia = int(1440 / intervalo_min)
    if s.notna().sum() < 2 * por_dia:
        raise ValueError("Se requieren al menos dos jornadas completas de registro.")

    muestras_ventana = int(ventana_h * 60 / intervalo_min)
    sinoptico = s.rolling(f"{int(ventana_h * 60)}min", center=True,
                          min_periods=muestras_ventana // 2).mean()
    intradiario = s - sinoptico

    m = intradiario.notna() & sinoptico.notna()
    var_i = float(np.var(intradiario[m], ddof=1))
    var_s = float(np.var(sinoptico[m], ddof=1))
    fraccion = var_s / (var_s + var_i) if (var_s + var_i) > 0 else 0.0

    pasos_total = int(max_rezago_total_h * 60 / intervalo_min)
    pasos_intra = int(max_rezago_intra_h * 60 / intervalo_min)
    acf_t = autocorrelacion_con_huecos(s, pasos_total)
    acf_i = autocorrelacion_con_huecos(intradiario, pasos_intra)

    tau_t = float(tiempo_decorrelacion(acf_t, intervalo_min * 60)["minutos"])
    tau_i = float(tiempo_decorrelacion(acf_i, intervalo_min * 60)["minutos"])

    # Persistencia entre jornadas: correlación de las medias diarias
    # consecutivas, solo sobre días con cobertura suficiente.
    local = s.index.tz_convert(TZ_LOCAL) if s.index.tz is not None else s.index
    diaria = s.groupby(local.date).agg(["mean", "count"])
    diaria = diaria[diaria["count"] >= int(0.7 * por_dia)]

    rho = float("nan")
    if len(diaria) >= 4:
        fechas = pd.to_datetime(pd.Series(diaria.index))
        consecutivos = (fechas.diff().iloc[1:] == pd.Timedelta(days=1)).to_numpy()
        medias = diaria["mean"].to_numpy()
        a, b = medias[:-1][consecutivos], medias[1:][consecutivos]
        if len(a) >= 3 and np.std(a) > 0 and np.std(b) > 0:
            rho = float(np.corrcoef(a, b)[0, 1])

    return Escalas(
        residual=s,
        intradiario=intradiario,
        sinoptico=sinoptico,
        var_intradiaria=var_i,
        var_sinoptica=var_s,
        fraccion_sinoptica=fraccion,
        acf_total=acf_t,
        acf_intradiaria=acf_i,
        tau_total_min=tau_t,
        tau_intradiario_min=tau_i,
        rho_diario=rho,
        n_dias=len(diaria),
        ventana_h=ventana_h,
    )
