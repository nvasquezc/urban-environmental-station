"""Generadores de datos sintéticos para las pruebas de control de calidad.

Los fixtures construyen series con defectos conocidos y controlados. Esto
permite verificar que el filtrado detecta exactamente lo que debe detectar,
sin depender de datos de campo ni de hardware.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

T0 = pd.Timestamp("2026-09-15 00:00:00", tz="UTC")
INTERVALO_S = 300


def _registro_base(i: int, t: pd.Timestamp) -> dict:
    """Un registro nominal, sin defectos."""
    return {
        "esquema": 1,
        "v": "0.2.0",
        "cal": "sin-calibrar",
        "plat": "esp8266",
        "id": "ues-test01",
        "boot": 1,
        "seq": i + 1,
        "uptime_s": (i + 1) * INTERVALO_S,
        "intervalo_s": INTERVALO_S,
        "t_fin": t,
        "temp_c.prom": 19.0 + 3.0 * np.sin(2 * np.pi * i / 288),
        "temp_c.min": 18.8,
        "temp_c.max": 19.4,
        "temp_c.n": 149,
        "hr_pct.prom": 62.0,
        "hr_pct.min": 61.0,
        "hr_pct.max": 63.0,
        "hr_pct.n": 149,
        "p_hpa.prom": 752.4,
        "p_hpa.min": 752.2,
        "p_hpa.max": 752.6,
        "p_hpa.n": 149,
        "son.trazable": False,
        "diag.rssi": -67.0,
        "diag.heap": 6656,
        "diag.frag": 11,
        "diag.reset": "External System",
        "diag.aht": True,
        "diag.bmp": True,
    }


@pytest.fixture
def df_nominal() -> pd.DataFrame:
    """24 horas de registros sin defecto alguno. 288 intervalos."""
    filas = [_registro_base(i, T0 + pd.Timedelta(seconds=i * INTERVALO_S)) for i in range(288)]
    return pd.DataFrame(filas)


@pytest.fixture
def df_con_defectos() -> pd.DataFrame:
    """Serie con un defecto de cada tipo, en posiciones conocidas.

    Índices afectados:
      2   muestras insuficientes (n = 90)
      5   sensor AHT caído
      8   temperatura fuera de rango físico
      11  esquema desconocido
      14  timestamp nulo
      17  primer intervalo tras reinicio (boot = 2, seq = 1)
    Total esperado de descartes: 6 sobre 40.
    """
    filas = [_registro_base(i, T0 + pd.Timedelta(seconds=i * INTERVALO_S)) for i in range(40)]

    filas[2]["temp_c.n"] = 90
    filas[5]["diag.aht"] = False
    filas[8]["temp_c.prom"] = 87.3
    filas[11]["esquema"] = 2
    filas[14]["t_fin"] = pd.NaT

    for i in range(17, 40):
        filas[i]["boot"] = 2
        filas[i]["seq"] = i - 16
    filas[17]["seq"] = 1

    return pd.DataFrame(filas)


@pytest.fixture
def df_con_hueco() -> pd.DataFrame:
    """Serie con una interrupción de 1 hora (11 intervalos ausentes)."""
    filas = []
    for i in range(20):
        filas.append(_registro_base(i, T0 + pd.Timedelta(seconds=i * INTERVALO_S)))
    for i in range(20, 40):
        t = T0 + pd.Timedelta(seconds=i * INTERVALO_S + 3600)
        filas.append(_registro_base(i, t))
    return pd.DataFrame(filas)


@pytest.fixture
def df_con_fuga() -> pd.DataFrame:
    """Serie con degradación monótona de memoria: 60 bytes por intervalo."""
    filas = []
    for i in range(288):
        r = _registro_base(i, T0 + pd.Timedelta(seconds=i * INTERVALO_S))
        r["diag.heap"] = 28000 - 60 * i
        filas.append(r)
    return pd.DataFrame(filas)
