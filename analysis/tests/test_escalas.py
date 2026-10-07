"""Pruebas de la separación de escalas temporales.

La serie sintética combina tres componentes de escala conocida: ciclo diurno,
régimen sinóptico de período plurianual en días y ruido persistente de horas.
Las pruebas verifican que la separación recupera la escala intradiaria sin
contaminarse con la sinóptica.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uestation.decompose import ajustar_ciclo_diurno
from uestation.escalas import a_rejilla, autocorrelacion_con_huecos, separar_escalas


def _serie_dos_escalas(dias=20, phi=0.9, amp_sinoptica=1.5,
                       periodo_sinoptico_d=8.0, semilla=4):
    """Ciclo diurno + régimen sinóptico + ruido AR(1).

    Con phi = 0.9 a pasos de 5 min, la autocorrelación del ruido cae por
    debajo de 1/e hacia los 50 minutos: esa es la escala intradiaria que la
    separación debe recuperar.
    """
    rng = np.random.default_rng(semilla)
    n = 288 * dias
    t = pd.date_range("2026-09-15", periods=n, freq="5min", tz="UTC")
    local = t.tz_convert("America/Bogota")
    h = local.hour + local.minute / 60.0
    dia = np.arange(n) * 5 / 1440.0

    e = rng.normal(0, 0.15, n)
    r = np.zeros(n)
    for i in range(1, n):
        r[i] = phi * r[i - 1] + e[i]

    y = (19.0
         + 4.0 * np.sin(2 * np.pi * (h - 9) / 24.0)
         + amp_sinoptica * np.sin(2 * np.pi * dia / periodo_sinoptico_d)
         + r)
    return pd.DataFrame({"t_fin": t, "temp_c.prom": y})


@pytest.fixture
def escalas():
    df = _serie_dos_escalas()
    return separar_escalas(ajustar_ciclo_diurno(df, "temp_c.prom"))


class TestSeparacion:
    def test_recupera_la_escala_intradiaria(self, escalas):
        """El τ intradiario se aproxima a la escala del ruido AR(1)."""
        assert 25 <= escalas.tau_intradiario_min <= 90

    def test_tau_total_dominado_por_lo_sinoptico(self, escalas):
        """Sin separar escalas, τ refleja el régimen de varios días."""
        assert escalas.tau_total_min > 5 * escalas.tau_intradiario_min

    def test_varianza_mayoritariamente_sinoptica(self, escalas):
        assert escalas.fraccion_sinoptica > 0.7

    def test_persistencia_entre_jornadas(self, escalas):
        """Un régimen de ocho días produce correlación positiva entre días."""
        assert escalas.rho_diario > 0.4

    def test_sin_componente_sinoptica(self):
        df = _serie_dos_escalas(amp_sinoptica=0.0)
        e = separar_escalas(ajustar_ciclo_diurno(df, "temp_c.prom"))
        assert e.fraccion_sinoptica < 0.3
        assert 25 <= e.tau_intradiario_min <= 90

    def test_cuenta_las_jornadas(self, escalas):
        assert escalas.n_dias >= 18


class TestHuecos:
    def test_rejilla_conserva_los_huecos(self):
        t = pd.date_range("2026-09-15", periods=100, freq="5min", tz="UTC")
        t = t.delete(range(40, 60))
        s = a_rejilla(pd.Series(t), np.ones(len(t)))
        assert len(s) == 100
        assert s.isna().sum() == 20

    def test_acf_tolera_huecos(self):
        rng = np.random.default_rng(1)
        x = rng.normal(0, 1, 2000)
        x[500:800] = np.nan
        a = autocorrelacion_con_huecos(pd.Series(x), max_rezago=50)
        assert a.iloc[0]["acf"] == 1.0
        assert abs(a.iloc[1]["acf"]) < 0.1

    def test_separacion_con_interrupcion_prolongada(self):
        """Un corte de 28 h, como el del 4 de octubre, no invalida el cálculo."""
        df = _serie_dos_escalas()
        df = df.drop(index=range(288 * 10, 288 * 10 + 336)).reset_index(drop=True)
        e = separar_escalas(ajustar_ciclo_diurno(df, "temp_c.prom"))
        assert np.isfinite(e.tau_intradiario_min)
        assert e.residual.isna().sum() >= 336

    def test_serie_corta_falla(self):
        df = _serie_dos_escalas(dias=1)
        with pytest.raises(ValueError):
            separar_escalas(ajustar_ciclo_diurno(df, "temp_c.prom"))
