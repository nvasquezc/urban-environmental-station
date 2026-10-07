"""Ejecuta por separado cada componente de la vista de resumen.

Permite localizar qué figura o tabla falla sin depender de los mensajes
abreviados del navegador. Cada paso imprime OK o el traceback completo.

Uso:
    cd analysis
    uv run python tools/diagnostico_tablero.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "analysis"))

from dashboard import app as A  # noqa: E402
from dashboard import figuras as F  # noqa: E402
from dashboard.datos import cargar  # noqa: E402
from uestation.decompose import matriz_hora_dia  # noqa: E402
from uestation.qc import aplicar_qc, detectar_huecos, diagnostico_estabilidad  # noqa: E402


def paso(nombre, funcion):
    try:
        resultado = funcion()
        print(f"  OK     {nombre}")
        return resultado
    except Exception:  # noqa: BLE001
        print(f"  FALLA  {nombre}")
        print("-" * 68)
        traceback.print_exc()
        print("-" * 68)
        return None


def main() -> None:
    print("\nDIAGNÓSTICO DE LA VISTA DE RESUMEN")
    print("─" * 68)

    df, _ = cargar()
    limpio, _ = aplicar_qc(df)

    d = paso("modelo", lambda: A._modelo(limpio)[0])
    e = paso("escalas", lambda: A._escalas(d))

    paso("descomposición", lambda: F.fig_descomposicion(d))
    paso("histograma", lambda: F.fig_histograma_residual(d))
    paso("autocorrelación intradiaria",
         lambda: F.fig_acf(e.acf_intradiaria, {"minutos": e.tau_intradiario_min},
                           A.INTERVALO_MIN))

    lat, lon, _ = paso("ubicación", lambda: A._ubicacion(df)) or (0, 0, "")
    paso("mapa", lambda: F.fig_mapa(lat, lon, "Zona de operación"))
    paso("matriz hora × día",
         lambda: F.fig_matriz(matriz_hora_dia(limpio, "temp_c.prom")))
    paso("estabilidad del nodo", lambda: F.fig_salud(df))

    diag = paso("diagnóstico", lambda: diagnostico_estabilidad(df))
    huecos = paso("huecos", lambda: detectar_huecos(limpio))
    paso("eventos", lambda: A._eventos(d, df, huecos))
    paso("tabla", lambda: A._tabla(diag, huecos))
    print()


if __name__ == "__main__":
    main()
