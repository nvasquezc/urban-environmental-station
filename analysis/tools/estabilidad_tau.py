"""Prueba de estabilidad del tiempo de decorrelación intradiario.

Un parámetro que describe el proceso debe ser aproximadamente invariante ante
la partición del registro. Se estima τ sobre mitades y tercios de la campaña
y se compara la dispersión entre particiones con el valor global.

Criterio: si el coeficiente de variación entre particiones supera 0.35, τ no
se considera una propiedad estable del proceso y no debe reportarse como tal.

Uso:
    cd analysis
    uv run python tools/estabilidad_tau.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "analysis"))

from dashboard.datos import cargar  # noqa: E402
from uestation.decompose import ajustar_ciclo_diurno  # noqa: E402
from uestation.escalas import separar_escalas  # noqa: E402
from uestation.qc import aplicar_qc  # noqa: E402

CV_MAXIMO = 0.35


def tau_tramo(df: pd.DataFrame) -> tuple[float, float]:
    """τ intradiario y τ total de un tramo; NaN si no es estimable."""
    try:
        m = ajustar_ciclo_diurno(df, "temp_c.prom")
        e = separar_escalas(m)
        return e.tau_intradiario_min, e.tau_total_min
    except (ValueError, np.linalg.LinAlgError):
        return float("nan"), float("nan")


def main() -> None:
    df, _ = cargar()
    limpio, _ = aplicar_qc(df)
    limpio = limpio.sort_values("t_fin").reset_index(drop=True)

    t0, t1 = limpio["t_fin"].iloc[0], limpio["t_fin"].iloc[-1]

    print("\nESTABILIDAD DEL TIEMPO DE DECORRELACIÓN")
    print("─" * 68)
    print(f"  {'partición':<22} {'días':>6} {'τ intradiario':>15} {'τ total':>12}")

    global_i, global_t = tau_tramo(limpio)
    dias_total = (t1 - t0).total_seconds() / 86400
    print(f"  {'serie completa':<22} {dias_total:>6.1f} "
          f"{global_i:>12.0f} min {global_t:>9.0f} min")

    resultados = {}
    for n_partes, etiqueta in [(2, "mitad"), (3, "tercio")]:
        bordes = pd.date_range(t0, t1, periods=n_partes + 1)
        taus_i, taus_t = [], []
        for k in range(n_partes):
            tramo = limpio[(limpio["t_fin"] >= bordes[k]) &
                           (limpio["t_fin"] <= bordes[k + 1])]
            ti, tt = tau_tramo(tramo)
            taus_i.append(ti)
            taus_t.append(tt)
            dias = (bordes[k + 1] - bordes[k]).total_seconds() / 86400
            print(f"  {f'{etiqueta} {k + 1}':<22} {dias:>6.1f} "
                  f"{ti:>12.0f} min {tt:>9.0f} min")
        resultados[etiqueta] = (np.array(taus_i), np.array(taus_t))

    print("\nDISPERSIÓN ENTRE PARTICIONES")
    print("─" * 68)
    estable = True
    for etiqueta, (ti, tt) in resultados.items():
        ti, tt = ti[np.isfinite(ti)], tt[np.isfinite(tt)]
        cv_i = np.std(ti, ddof=1) / np.mean(ti) if len(ti) > 1 else np.nan
        cv_t = np.std(tt, ddof=1) / np.mean(tt) if len(tt) > 1 else np.nan
        print(f"  {etiqueta:<10} CV intradiario {cv_i:5.2f}   CV total {cv_t:5.2f}")
        if not np.isfinite(cv_i) or cv_i > CV_MAXIMO:
            estable = False

    print("\nVEREDICTO")
    print("─" * 68)
    if estable:
        print(f"  τ intradiario estable (CV ≤ {CV_MAXIMO}): reportable como propiedad")
        print("  del proceso en las condiciones de la campaña.")
    else:
        print(f"  τ intradiario inestable (CV > {CV_MAXIMO}): no debe reportarse como")
        print("  propiedad del proceso. Depende del tramo observado.")
    print()


if __name__ == "__main__":
    main()
