"""Control de calidad de registros de la estación ambiental urbana.

Implementa los criterios de rechazo definidos en
docs/02-protocolo-calibracion.md §5.4.

Principio rector: el control de calidad NO corrige valores. Marca y descarta.
Toda corrección pertenece a la etapa de calibración y opera sobre datos crudos
ya filtrados. Un registro descartado se contabiliza por causa, nunca se elimina
en silencio.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# --- Umbrales de aceptación -------------------------------------------------
# Muestras esperadas por intervalo: INTERVALO_S / (PERIODO_CLIMA_MS / 1000)
MUESTRAS_ESPERADAS_CLIMA = 150
FRACCION_MINIMA = 0.80
MUESTRAS_MINIMAS_CLIMA = int(MUESTRAS_ESPERADAS_CLIMA * FRACCION_MINIMA)  # 120

# Rangos de plausibilidad física. No son especificaciones del sensor:
# son límites fuera de los cuales el dato es evidencia de falla, no de clima.
RANGOS = {
    "temp_c.prom": (-20.0, 60.0),
    "hr_pct.prom": (0.0, 100.0),
    "p_hpa.prom": (500.0, 1100.0),
}

CAUSAS = [
    "esquema_desconocido",
    "sin_timestamp",
    "sensor_caido",
    "muestras_insuficientes",
    "fuera_de_rango",
    "intervalo_con_reinicio",
    "duplicado",
]


@dataclass
class ResumenQC:
    """Contabilidad del filtrado. Se reporta íntegra, nunca se resume a un total."""

    n_entrada: int = 0
    n_salida: int = 0
    descartes: dict[str, int] = field(default_factory=lambda: dict.fromkeys(CAUSAS, 0))

    @property
    def n_descartado(self) -> int:
        return self.n_entrada - self.n_salida

    @property
    def fraccion_descartada(self) -> float:
        return self.n_descartado / self.n_entrada if self.n_entrada else 0.0

    def a_markdown(self) -> str:
        """Tabla para qc_resumen.md, entregable de §10 del protocolo."""
        lineas = [
            "# Resumen de control de calidad",
            "",
            f"- Registros de entrada: **{self.n_entrada}**",
            f"- Registros aceptados: **{self.n_salida}**",
            f"- Registros descartados: **{self.n_descartado}** "
            f"({self.fraccion_descartada:.1%})",
            "",
            "| Causa | Registros |",
            "|---|---|",
        ]
        for causa, n in self.descartes.items():
            lineas.append(f"| `{causa}` | {n} |")
        lineas += [
            "",
            "> Un descarte superior al 10 % constituye un hallazgo y debe",
            "> reportarse explícitamente (protocolo §5.4).",
        ]
        return "\n".join(lineas)


def _marcar(
    mascara: pd.Series,
    resumen: ResumenQC,
    causa: str,
    ya_descartado: pd.Series,
) -> pd.Series:
    """Registra descartes nuevos, sin contar dos veces un registro ya rechazado.

    El orden de evaluación define la causa atribuida: se asigna la primera
    causa que aplica, de modo que la suma de causas iguala el total descartado.
    """
    nuevos = mascara & ~ya_descartado
    resumen.descartes[causa] += int(nuevos.sum())
    return ya_descartado | nuevos


def aplicar_qc(
    df: pd.DataFrame,
    esquema_soportado: int = 1,
    devolver_marcas: bool = False,
) -> tuple[pd.DataFrame, ResumenQC]:
    """Aplica los criterios de rechazo y devuelve los registros aceptados.

    Parameters
    ----------
    df
        Registros crudos, tal como los entrega `ingest.descargar`.
    esquema_soportado
        Versión de esquema admitida. Cualquier otra se rechaza sin interpretar.
    devolver_marcas
        Si es True, agrega la columna booleana `qc_ok` en lugar de filtrar.

    Returns
    -------
    (DataFrame, ResumenQC)
    """
    resumen = ResumenQC(n_entrada=len(df))
    if df.empty:
        return df.copy(), resumen

    d = df.copy().sort_values("t_fin", kind="stable").reset_index(drop=True)
    malo = pd.Series(False, index=d.index)

    # 1. Esquema. Se rechaza lo desconocido en vez de adivinar su semántica.
    if "esquema" in d.columns:
        malo = _marcar(
            d["esquema"] != esquema_soportado, resumen, "esquema_desconocido", malo
        )
    else:
        malo = _marcar(
            pd.Series(True, index=d.index), resumen, "esquema_desconocido", malo
        )

    # 2. Timestamp. Sin hora sincronizada el intervalo no es ubicable en el tiempo.
    malo = _marcar(d["t_fin"].isna(), resumen, "sin_timestamp", malo)

    # 3. Estado de sensores declarado por el propio firmware.
    caido = pd.Series(False, index=d.index)
    for col in ("diag.aht", "diag.bmp"):
        if col in d.columns:
            caido |= d[col] != True  # noqa: E712 — comparación explícita, hay NaN
    malo = _marcar(caido, resumen, "sensor_caido", malo)

    # 4. Completitud del muestreo.
    if "temp_c.n" in d.columns:
        malo = _marcar(
            d["temp_c.n"].fillna(0) < MUESTRAS_MINIMAS_CLIMA,
            resumen,
            "muestras_insuficientes",
            malo,
        )

    # 5. Plausibilidad física.
    fuera = pd.Series(False, index=d.index)
    for col, (lo, hi) in RANGOS.items():
        if col in d.columns:
            v = d[col]
            fuera |= v.isna() | (v < lo) | (v > hi)
    malo = _marcar(fuera, resumen, "fuera_de_rango", malo)

    # 6. Intervalos que contienen un reinicio. El primer intervalo tras un
    #    arranque es parcial por construcción: el acumulador partió a mitad.
    #    No se aplica al primer registro de la serie, porque no hay evidencia
    #    de que la serie empiece en un arranque; si además fuera parcial, el
    #    criterio de muestras insuficientes lo captura.
    if "boot" in d.columns and "seq" in d.columns:
        primer_tras_reinicio = (d["boot"] != d["boot"].shift(1)) & (d["seq"] == 1)
        primer_tras_reinicio.iloc[0] = False
        malo = _marcar(primer_tras_reinicio, resumen, "intervalo_con_reinicio", malo)

    # 7. Duplicados por timestamp. Se conserva el primero.
    malo = _marcar(d["t_fin"].duplicated(keep="first"), resumen, "duplicado", malo)

    if devolver_marcas:
        d["qc_ok"] = ~malo
        resumen.n_salida = int((~malo).sum())
        return d, resumen

    limpio = d.loc[~malo].reset_index(drop=True)
    resumen.n_salida = len(limpio)
    return limpio, resumen


def detectar_huecos(df: pd.DataFrame, intervalo_s: int = 300) -> pd.DataFrame:
    """Identifica discontinuidades en la serie de intervalos.

    Un hueco no es un registro descartado: es un registro que nunca existió.
    Ambos afectan la completitud y deben reportarse por separado.
    """
    if len(df) < 2:
        return pd.DataFrame(
            columns=["inicio", "fin", "duracion_s", "intervalos_faltantes"]
        )

    t = df["t_fin"].sort_values().reset_index(drop=True)
    delta = t.diff().dt.total_seconds()
    idx = delta[delta > intervalo_s * 1.5].index

    return pd.DataFrame(
        {
            "inicio": t[idx - 1].to_numpy(),
            "fin": t[idx].to_numpy(),
            "duracion_s": delta[idx].to_numpy(),
            "intervalos_faltantes": (delta[idx] / intervalo_s - 1)
            .round()
            .astype(int)
            .to_numpy(),
        }
    )


def completitud(df: pd.DataFrame, intervalo_s: int = 300) -> dict[str, float]:
    """Fracción de intervalos efectivamente presentes sobre los esperados."""
    if df.empty:
        return {"esperados": 0, "presentes": 0, "completitud": 0.0}

    t0, t1 = df["t_fin"].min(), df["t_fin"].max()
    esperados = int((t1 - t0).total_seconds() / intervalo_s) + 1
    return {
        "esperados": esperados,
        "presentes": len(df),
        "completitud": len(df) / esperados if esperados else 0.0,
    }


def diagnostico_estabilidad(df: pd.DataFrame) -> dict[str, object]:
    """Métricas de salud del nodo para la prueba de estabilidad.

    No evalúa la calidad de la medición sino la del instrumento: si el sistema
    se degrada con el tiempo, cualquier caracterización posterior es inválida.
    """
    out: dict[str, object] = {}

    if "diag.heap" in df.columns and len(df) > 2:
        # Solo registros con timestamp y heap válidos: la regresión no admite NaN.
        v = df[["t_fin", "diag.heap"]].dropna()
        if len(v) > 2:
            h = v["diag.heap"].astype(float).to_numpy()
            out["heap_min"] = float(h.min())
            out["heap_max"] = float(h.max())
            # Pendiente por hora: una fuga produce deriva negativa sostenida.
            horas = (
                (v["t_fin"] - v["t_fin"].min()).dt.total_seconds() / 3600.0
            ).to_numpy()
            if horas[-1] > 0:
                out["heap_pendiente_bytes_hora"] = float(np.polyfit(horas, h, 1)[0])

    if "diag.frag" in df.columns:
        out["frag_max_pct"] = float(df["diag.frag"].max())

    if "boot" in df.columns:
        out["n_arranques"] = int(df["boot"].nunique())

    if "diag.reset" in df.columns:
        causas = df.groupby("boot")["diag.reset"].first().value_counts()
        out["causas_reset"] = causas.to_dict()
        # Cualquier causa distinta de un reinicio inducido es un incidente.
        inducidos = {"External System", "Power on", "1", "3", "5"}
        out["reinicios_espontaneos"] = int(
            sum(n for c, n in causas.items() if str(c) not in inducidos)
        )

    if "diag.rssi" in df.columns:
        r = df["diag.rssi"]
        out["rssi_mediana"] = float(r.median()) if r.notna().any() else None
        out["intervalos_sin_red"] = int(r.isna().sum())

    if "temp_c.n" in df.columns:
        out["muestras_moda"] = int(df["temp_c.n"].mode().iloc[0])
        out["muestras_min"] = int(df["temp_c.n"].min())

    return out
