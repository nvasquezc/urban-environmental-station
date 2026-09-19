"""Pruebas de la descomposición de series."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uestation.decompose import (
    ajustar_ciclo_diurno,
    autocorrelacion,
    incertidumbre_expandida,
    matriz_hora_dia,
    tiempo_decorrelacion,
)


@pytest.fixture
def serie_ciclica():
    """Ciclo diurno puro de amplitud 4 °C más ruido blanco de sigma 0.2."""
    rng = np.random.default_rng(7)
    t = pd.date_range("2026-09-15", periods=288 * 3, freq="5min", tz="UTC")
    local = t.tz_convert("America/Bogota")
    h = local.hour + local.minute / 60.0
    y = 19.0 + 4.0 * np.sin(2 * np.pi * (h - 9) / 24.0) + rng.normal(0, 0.2, len(t))
    return pd.DataFrame({"t_fin": t, "temp_c.prom": y})


class TestCicloDiurno:
    def test_explica_casi_toda_la_varianza(self, serie_ciclica):
        """Una señal sinusoidal con poco ruido debe quedar casi totalmente explicada."""
        d = ajustar_ciclo_diurno(serie_ciclica, "temp_c.prom")
        assert d.varianza_explicada > 0.95

    def test_sigma_residual_recupera_el_ruido(self, serie_ciclica):
        d = ajustar_ciclo_diurno(serie_ciclica, "temp_c.prom")
        assert abs(d.sigma_residual - 0.2) < 0.05

    def test_residual_centrado(self, serie_ciclica):
        d = ajustar_ciclo_diurno(serie_ciclica, "temp_c.prom")
        assert abs(d.residual.mean()) < 1e-6

    def test_bandas_simetricas(self, serie_ciclica):
        d = ajustar_ciclo_diurno(serie_ciclica, "temp_c.prom")
        ancho_sup = (d.banda_superior - d.ciclo).iloc[0]
        ancho_inf = (d.ciclo - d.banda_inferior).iloc[0]
        assert abs(ancho_sup - ancho_inf) < 1e-9

    def test_detecta_anomalia_inyectada(self, serie_ciclica):
        df = serie_ciclica.copy()
        df.loc[400, "temp_c.prom"] += 3.0
        d = ajustar_ciclo_diurno(df, "temp_c.prom")
        assert d.anomalias(k=2.0).iloc[400]

    def test_serie_corta_falla(self):
        df = pd.DataFrame({
            "t_fin": pd.date_range("2026-09-15", periods=5, freq="5min", tz="UTC"),
            "temp_c.prom": [19.0] * 5,
        })
        with pytest.raises(ValueError):
            ajustar_ciclo_diurno(df, "temp_c.prom")


class TestAutocorrelacion:
    def test_rezago_cero_es_uno(self, serie_ciclica):
        a = autocorrelacion(serie_ciclica["temp_c.prom"])
        assert abs(a.iloc[0]["acf"] - 1.0) < 1e-9

    def test_ruido_blanco_decorrelaciona_de_inmediato(self):
        rng = np.random.default_rng(1)
        s = pd.Series(rng.normal(0, 1, 2000))
        a = autocorrelacion(s, max_rezago=50)
        assert abs(a.iloc[1]["acf"]) < 0.1

    def test_serie_ciclica_conserva_correlacion(self, serie_ciclica):
        a = autocorrelacion(serie_ciclica["temp_c.prom"], max_rezago=100)
        assert a.iloc[12]["acf"] > 0.5

    def test_tiempo_decorrelacion_en_minutos(self, serie_ciclica):
        a = autocorrelacion(serie_ciclica["temp_c.prom"], max_rezago=288)
        td = tiempo_decorrelacion(a)
        assert td["minutos"] > 0


class TestMatrizHoraDia:
    def test_dimensiones(self, serie_ciclica):
        m = matriz_hora_dia(serie_ciclica, "temp_c.prom")
        assert m.shape[0] == 24


class TestIncertidumbre:
    def test_calcula_u_expandida(self):
        df = pd.DataFrame({
            "temp_c.min": [18.7] * 100,
            "temp_c.max": [19.3] * 100,
            "temp_c.n": [149] * 100,
        })
        u = incertidumbre_expandida(df)
        assert u["k"] == 2.0
        assert u["U_expandida_k2"] > 0
        assert "calibración" in u["nota"]

    def test_devuelve_vacio_sin_columnas(self):
        assert incertidumbre_expandida(pd.DataFrame({"a": [1]})) == {}
