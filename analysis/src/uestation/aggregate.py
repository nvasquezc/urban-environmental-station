
"""Agregación temporal de intervalos a resoluciones mayores.

Implementa el pareo temporal de docs/02-protocolo-calibracion.md §5.5 y la
estratificación exigida en §6.3.

Tres principios gobiernan este módulo:

1. **El nivel sonoro se compone en energía, no se promedia en decibelios.**
   El decibel es una escala logarítmica; su media aritmética subestima
   sistemáticamente la contribución de los eventos intensos, que son
   precisamente los que determinan el nivel equivalente.

2. **La dispersión se propaga, no se recalcula.** Cada intervalo de cinco
   minutos resume 150 muestras. La varianza del promedio horario combina la
   varianza intra-intervalo (dentro de cada bloque) con la inter-intervalo
   (entre bloques), mediante la ley de varianza total. Ignorar el primer
   término subestima la incertidumbre.

3. **Una agregación incompleta se rechaza, no se completa.** Si faltan
   intervalos, el promedio horario representa un subconjunto sesgado del
   período y no es comparable con una referencia que sí cubrió la hora entera.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Intervalos de 5 min esperados en una hora
INTERVALOS_POR_HORA = 12
# §5.5: se exige cobertura mínima para que el promedio horario sea comparable
MINIMO_INTERVALOS_HORA = 10

TZ_LOCAL = "America/Bogota"

VARIABLES_CLIMA = ("temp_c", "hr_pct", "p_hpa")

# Franjas horarias para estratificación (§6.3). Los cortes corresponden al
# ciclo de radiación solar: el sesgo por calentamiento del sensor no se
# distribuye de manera uniforme a lo largo del día.
FRANJAS = [
    (0, 6, "madrugada"),
    (6, 12, "mañana"),
    (12, 18, "tarde"),
    (18, 24, "noche"),
]


def _varianza_total(prom: np.ndarray, var_intra: np.ndarray, n: np.ndarray) -> float:
    """Ley de varianza total sobre grupos de tamaño desigual.

    Var(X) = E[Var(X|G)] + Var(E[X|G])

    El primer término es la varianza promedio dentro de los grupos, ponderada
    por su tamaño; el segundo, la varianza entre las medias de grupo. Devuelve
    NaN si no hay información suficiente.
    """
    n_tot = n.sum()
    if n_tot == 0:
        return np.nan

    media_global = np.average(prom, weights=n)
    intra = np.average(var_intra, weights=n) if np.isfinite(var_intra).any() else 0.0
    inter = np.average((prom - media_global) ** 2, weights=n)
    return float(intra + inter)


def _var_desde_rango(mn: np.ndarray, mx: np.ndarray) -> np.ndarray:
    """Estimación conservadora de la varianza intra-intervalo desde el rango.

    El firmware reporta promedio, mínimo y máximo por intervalo, no la
    desviación estándar. Para n≈150 muestras de un proceso aproximadamente
    normal, el rango esperado es ~5.3 sigma; se usa esa relación como
    estimador. La aproximación es gruesa y sesga hacia arriba ante valores
    atípicos, de modo que el resultado es conservador: nunca subestima la
    incertidumbre.
    """
    d2_n150 = 5.3
    return ((mx - mn) / d2_n150) ** 2


def agregar_horario(
    df: pd.DataFrame,
    minimo_intervalos: int = MINIMO_INTERVALOS_HORA,
) -> pd.DataFrame:
    """Agrega intervalos de 5 min a promedios horarios alineados a la hora en punto.

    Cada hora resultante se etiqueta con el instante de **inicio** del período,
    en UTC. Las horas que no alcanzan `minimo_intervalos` se excluyen.

    Para cada variable climática devuelve:
      `<var>_prom`  media ponderada por número de muestras
      `<var>_sd`    desviación estándar combinada (ley de varianza total)
      `<var>_min`   mínimo de los mínimos
      `<var>_max`   máximo de los máximos
      `<var>_n`     muestras totales acumuladas

    Para sonido, cuando existen registros trazables:
      `son_leq`     nivel equivalente compuesto en energía
      `son_lmax`    máximo de los máximos
    """
    if df.empty:
        return pd.DataFrame()

    d = df.copy()
    d["hora"] = d["t_fin"].dt.floor("h")

    filas = []
    for hora, g in d.groupby("hora", sort=True):
        if len(g) < minimo_intervalos:
            continue

        fila: dict[str, object] = {
            "hora_utc": hora,
            "n_intervalos": len(g),
            "cobertura": len(g) / INTERVALOS_POR_HORA,
        }

        for var in VARIABLES_CLIMA:
            c_prom, c_min = f"{var}.prom", f"{var}.min"
            c_max, c_n = f"{var}.max", f"{var}.n"
            if c_prom not in g.columns:
                continue

            v = g[[c_prom, c_min, c_max, c_n]].dropna()
            if v.empty:
                continue

            prom = v[c_prom].to_numpy(dtype=float)
            mn = v[c_min].to_numpy(dtype=float)
            mx = v[c_max].to_numpy(dtype=float)
            n = v[c_n].to_numpy(dtype=float)

            var_tot = _varianza_total(prom, _var_desde_rango(mn, mx), n)

            fila[f"{var}_prom"] = float(np.average(prom, weights=n))
            fila[f"{var}_sd"] = (
                float(np.sqrt(var_tot)) if np.isfinite(var_tot) else np.nan
            )
            fila[f"{var}_min"] = float(mn.min())
            fila[f"{var}_max"] = float(mx.max())
            fila[f"{var}_n"] = int(n.sum())

        # Sonido: solo si la serie declara base metrológica.
        if "son.trazable" in g.columns and bool(g["son.trazable"].all()):
            leq = g["son.leq"].dropna().to_numpy(dtype=float)
            if leq.size:
                fila["son_leq"] = float(
                    10.0 * np.log10(np.mean(10.0 ** (leq / 10.0)))
                )
                fila["son_lmax"] = float(g["son.lmax"].max())

        filas.append(fila)

    if not filas:
        return pd.DataFrame()

    out = pd.DataFrame(filas)
    out["hora_local"] = out["hora_utc"].dt.tz_convert(TZ_LOCAL)
    return out.sort_values("hora_utc").reset_index(drop=True)


def componer_leq(
    niveles: np.ndarray | pd.Series,
    pesos: np.ndarray | None = None,
) -> float:
    """Compone niveles sonoros en energía.

    Leq = 10·log10( Σ wᵢ·10^(Lᵢ/10) / Σ wᵢ )

    Se expone como función pública porque la composición energética es un
    error frecuente en la literatura de sensores de bajo costo y conviene
    tenerla explícita, documentada y verificable por pruebas.
    """
    L = np.asarray(niveles, dtype=float)
    L = L[np.isfinite(L)]
    if L.size == 0:
        return np.nan
    if pesos is None:
        return float(10.0 * np.log10(np.mean(10.0 ** (L / 10.0))))

    w = np.asarray(pesos, dtype=float)[: L.size]
    return float(10.0 * np.log10(np.average(10.0 ** (L / 10.0), weights=w)))


def agregar_diario(df_horario: pd.DataFrame) -> pd.DataFrame:
    """Agrega promedios horarios a resumen diario en hora local.

    Exige 20 de 24 horas. El día se define en zona local porque las variables
    ambientales urbanas siguen el ciclo solar local, no el meridiano de Greenwich.
    """
    if df_horario.empty:
        return pd.DataFrame()

    d = df_horario.copy()
    d["fecha"] = d["hora_local"].dt.date

    filas = []
    for fecha, g in d.groupby("fecha", sort=True):
        if len(g) < 20:
            continue
        fila: dict[str, object] = {"fecha": fecha, "n_horas": len(g)}
        for var in VARIABLES_CLIMA:
            c = f"{var}_prom"
            if c in g.columns and g[c].notna().any():
                fila[f"{var}_prom"] = float(g[c].mean())
                fila[f"{var}_min"] = float(g[f"{var}_min"].min())
                fila[f"{var}_max"] = float(g[f"{var}_max"].max())
                fila[f"{var}_amplitud"] = fila[f"{var}_max"] - fila[f"{var}_min"]
        filas.append(fila)

    return pd.DataFrame(filas)


def asignar_franja(serie_local: pd.Series) -> pd.Series:
    """Etiqueta cada instante con su franja horaria (§6.3)."""
    h = serie_local.dt.hour
    etiquetas = pd.Series("indefinida", index=serie_local.index, dtype="object")
    for lo, hi, nombre in FRANJAS:
        etiquetas[(h >= lo) & (h < hi)] = nombre
    return pd.Categorical(etiquetas, categories=[f[2] for f in FRANJAS], ordered=True)


def asignar_cuartil_hr(hr: pd.Series) -> pd.Series:
    """Etiqueta cada registro con su cuartil de humedad relativa (§6.3).

    Los cortes se calculan sobre la propia campaña: el interés es comparar
    desempeño entre condiciones observadas, no contra valores absolutos.
    """
    validos = hr.dropna()
    if validos.nunique() < 4:
        return pd.Series("indefinido", index=hr.index, dtype="object")
    return pd.qcut(hr, q=4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")


def estratificar(df: pd.DataFrame, col_hr: str = "hr_pct.prom") -> pd.DataFrame:
    """Agrega las columnas de estratificación exigidas por el protocolo §6.3.

    Un desempeño global aceptable puede ocultar fallas sistemáticas en franjas
    específicas. La estratificación es obligatoria en el reporte, no opcional.
    """
    d = df.copy()
    if "t_fin" in d.columns:
        local = d["t_fin"].dt.tz_convert(TZ_LOCAL)
    elif "hora_local" in d.columns:
        local = d["hora_local"]
    else:
        raise KeyError("Se requiere 't_fin' o 'hora_local' para estratificar.")

    d["franja"] = asignar_franja(local)
    d["hora_dia"] = local.dt.hour

    if col_hr in d.columns:
        d["cuartil_hr"] = asignar_cuartil_hr(d[col_hr])

    return d


def resumen_por_estrato(
    df: pd.DataFrame,
    columna: str,
    estrato: str = "franja",
) -> pd.DataFrame:
    """Estadísticos descriptivos de una variable, desagregados por estrato."""
    if estrato not in df.columns:
        raise KeyError(f"Falta la columna de estratificación '{estrato}'.")

    g = df.groupby(estrato, observed=True)[columna]
    return pd.DataFrame(
        {
            "n": g.count(),
            "media": g.mean(),
            "sd": g.std(ddof=1),
            "min": g.min(),
            "p25": g.quantile(0.25),
            "mediana": g.median(),
            "p75": g.quantile(0.75),
            "max": g.max(),
        }
    ).reset_index()
