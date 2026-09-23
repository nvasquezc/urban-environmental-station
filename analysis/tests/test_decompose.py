"""Pruebas de la descomposición de series."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uestation.decompose import (
    ajustar_ciclo_diurno,
    autocorrelacion,
    detectar_tendencia,
    incertidumbre_expandida,
    matriz_hora_dia,
    tiempo_decorrelacion,
    variabilidad_diaria,
)


def _serie(dias=3, amplitud=4.0, ruido=0.2, pendiente=0.0, semilla=7):
    """Ciclo diurno sintético con tendencia y ruido controlados."""
    rng = np.random.default_rng(semilla)
    n = 288 * dias
    t = pd.date_range("2026-09-15", periods=n, freq="5min", tz="UTC")
    local = t.tz_convert("America/Bogota")
    h = local.hour + local.minute / 60.0
    d = np.arange(n) * 5 / 1440.0  # días transcurridos
    y = (19.0
         + pendiente * d
         + amplitud * np.sin(2 * np.pi * (h - 9) / 24.0)
         + rng.normal(0, ruido, n))
    return pd.DataFrame({"t_fin": t, "temp_c.prom": y})


@pytest.fixture
def serie_ciclica():
    return _serie()


@pytest.fixture
def serie_con_deriva():
    """Ciclo diurno con calentamiento sostenido de 0.35 °C por día."""
    return _serie(dias=8, pendiente=0.35)


class TestCicloDiurno:
    def test_explica_casi_toda_la_varianza(self, serie_ciclica):
        d = ajustar_ciclo_diurno(serie_ciclica, "temp_c.prom")
        assert d.varianza_explicada > 0.95

    def test_sigma_residual_recupera_el_ruido(self, serie_ciclica):
        d = ajustar_ciclo_diurno(serie_ciclica, "temp_c.prom")
        assert abs(d.sigma_residual - 0.2) < 0.05

    def test_amplitud_diurna_recuperada(self, serie_ciclica):
        """La amplitud pico a pico del primer armónico duplica la del seno."""
        d = ajustar_ciclo_diurno(serie_ciclica, "temp_c.prom")
        assert abs(d.amplitud_diurna - 8.0) < 0.3

    def test_residual_centrado(self, serie_ciclica):
        d = ajustar_ciclo_diurno(serie_ciclica, "temp_c.prom")
        assert abs(d.residual.mean()) < 1e-6

    def test_identidad_de_descomposicion(self, serie_ciclica):
        """observado = ciclo + residual, por construcción."""
        d = ajustar_ciclo_diurno(serie_ciclica, "temp_c.prom")
        assert np.allclose(d.observado, d.ciclo + d.residual)

    def test_bandas_simetricas(self, serie_ciclica):
        d = ajustar_ciclo_diurno(serie_ciclica, "temp_c.prom")
        assert abs((d.banda_superior - d.ciclo).iloc[0]
                   - (d.ciclo - d.banda_inferior).iloc[0]) < 1e-9

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


class TestTendencia:
    def test_recupera_la_pendiente(self, serie_con_deriva):
        d = ajustar_ciclo_diurno(serie_con_deriva, "temp_c.prom", con_tendencia=True)
        assert abs(d.pendiente_dia - 0.35) < 0.02

    def test_sin_deriva_la_pendiente_es_nula(self, serie_ciclica):
        d = ajustar_ciclo_diurno(serie_ciclica, "temp_c.prom", con_tendencia=True)
        assert abs(d.pendiente_dia) < 0.02

    def test_ignorar_la_deriva_infla_el_residual(self, serie_con_deriva):
        """Sin término de tendencia, la deriva se traslada al residual."""
        sin_t = ajustar_ciclo_diurno(serie_con_deriva, "temp_c.prom",
                                     con_tendencia=False)
        con_t = ajustar_ciclo_diurno(serie_con_deriva, "temp_c.prom",
                                     con_tendencia=True)
        assert sin_t.sigma_residual > 3 * con_t.sigma_residual

    def test_con_tendencia_recupera_el_ruido(self, serie_con_deriva):
        d = ajustar_ciclo_diurno(serie_con_deriva, "temp_c.prom", con_tendencia=True)
        assert abs(d.sigma_residual - 0.2) < 0.05

    def test_identidad_con_tendencia(self, serie_con_deriva):
        d = ajustar_ciclo_diurno(serie_con_deriva, "temp_c.prom", con_tendencia=True)
        assert np.allclose(d.observado, d.ciclo + d.residual)

    def test_serie_de_tendencia_disponible(self, serie_con_deriva):
        d = ajustar_ciclo_diurno(serie_con_deriva, "temp_c.prom", con_tendencia=True)
        assert d.tendencia is not None
        assert len(d.tendencia) == len(d.observado)

    def test_sin_tendencia_no_genera_la_serie(self, serie_ciclica):
        d = ajustar_ciclo_diurno(serie_ciclica, "temp_c.prom", con_tendencia=False)
        assert d.tendencia is None
        assert d.pendiente_dia == 0.0


class TestDeteccionRobusta:
    def test_confirma_deriva_real(self, serie_con_deriva):
        """Una deriva sostenida satisface los tres criterios."""
        r = detectar_tendencia(serie_con_deriva)
        assert r["recomendada"]
        assert r["supera_umbral"]
        assert r["significativa_corregida"]
        assert r["consistente"]
        assert r["homogenea"]
        assert abs(r["pendiente_dia"] - 0.35) < 0.03

    def test_rechaza_serie_sin_deriva(self, serie_ciclica):
        assert not detectar_tendencia(serie_ciclica)["recomendada"]

    def test_corrige_el_error_estandar(self, serie_con_deriva):
        """La corrección por autocorrelación amplía el error estándar."""
        r = detectar_tendencia(serie_con_deriva)
        assert r["pendiente_ee_corregido"] >= r["pendiente_ee_nominal"]
        assert r["n_efectivo"] <= r["n_observaciones"]

    def test_rechaza_pendiente_por_extremos(self):
        """Dos desplazamientos de nivel en los extremos no son una deriva.

        La serie es estacionaria salvo por un descenso en la primera jornada y
        un ascenso en la última. El ajuste global detecta pendiente positiva;
        el criterio de homogeneidad la rechaza, porque las pendientes locales
        de los bloques extremos exceden con mucho a la global.
        """
        df = _serie(dias=8, pendiente=0.0, semilla=11)
        n = len(df)
        df.loc[:288, "temp_c.prom"] -= 1.5
        df.loc[n - 288:, "temp_c.prom"] += 1.5

        r = detectar_tendencia(df)
        assert not r["recomendada"]
        assert not r["homogenea"]

    def test_informa_las_pendientes_por_bloque(self, serie_con_deriva):
        r = detectar_tendencia(serie_con_deriva)
        assert len(r["bloques_pendientes"]) >= 3
        assert all(p > 0 for p in r["bloques_pendientes"])

    def test_declara_el_motivo(self, serie_ciclica):
        r = detectar_tendencia(serie_ciclica)
        assert isinstance(r["motivo"], str) and r["motivo"]

    def test_serie_insuficiente_no_falla(self):
        df = pd.DataFrame({
            "t_fin": pd.date_range("2026-09-15", periods=6, freq="5min", tz="UTC"),
            "temp_c.prom": [19.0] * 6,
        })
        r = detectar_tendencia(df)
        assert not r["recomendada"]
        assert r["motivo"] == "serie insuficiente"


class TestVariabilidadDiaria:
    def test_una_fila_por_jornada(self, serie_con_deriva):
        v = variabilidad_diaria(serie_con_deriva)
        assert len(v) >= 6
        assert {"fecha", "n", "sesgo", "dispersion", "amplitud"} <= set(v.columns)

    def test_detecta_jornada_atipica(self, serie_ciclica):
        """Un día desplazado se refleja en el sesgo del residual."""
        df = serie_ciclica.copy()
        df.loc[288:575, "temp_c.prom"] -= 1.2
        v = variabilidad_diaria(df)
        assert v["sesgo"].min() < -0.5

    def test_detecta_cambio_de_amplitud(self, serie_ciclica):
        """Amplificar el ciclo de una jornada eleva su dispersión residual.

        El umbral es moderado porque el ajuste global se contamina en parte
        con la jornada amplificada, lo que eleva también la dispersión de las
        restantes.
        """
        df = serie_ciclica.copy()
        seg = df.loc[288:575, "temp_c.prom"]
        df.loc[288:575, "temp_c.prom"] = seg.mean() + (seg - seg.mean()) * 2.2
        v = variabilidad_diaria(df)
        assert v["dispersion"].max() > 1.5 * v["dispersion"].min()

    def test_descarta_jornadas_incompletas(self, serie_ciclica):
        v = variabilidad_diaria(serie_ciclica)
        assert (v["n"] >= 200).all()


class TestAutocorrelacion:
    def test_rezago_cero_es_uno(self, serie_ciclica):
        a = autocorrelacion(serie_ciclica["temp_c.prom"])
        assert abs(a.iloc[0]["acf"] - 1.0) < 1e-9

    def test_ruido_blanco_decorrelaciona_de_inmediato(self):
        rng = np.random.default_rng(1)
        a = autocorrelacion(pd.Series(rng.normal(0, 1, 2000)), max_rezago=50)
        assert abs(a.iloc[1]["acf"]) < 0.1

    def test_serie_ciclica_conserva_correlacion(self, serie_ciclica):
        a = autocorrelacion(serie_ciclica["temp_c.prom"], max_rezago=100)
        assert a.iloc[12]["acf"] > 0.5

    def test_tiempo_decorrelacion_en_minutos(self, serie_ciclica):
        a = autocorrelacion(serie_ciclica["temp_c.prom"], max_rezago=288)
        assert tiempo_decorrelacion(a)["minutos"] > 0

    def test_la_tendencia_distorsiona_tau(self, serie_con_deriva):
        """Sobre un residual con deriva, tau mide la tendencia, no la persistencia."""
        sin_t = ajustar_ciclo_diurno(serie_con_deriva, "temp_c.prom",
                                     con_tendencia=False)
        con_t = ajustar_ciclo_diurno(serie_con_deriva, "temp_c.prom",
                                     con_tendencia=True)
        tau_sin = tiempo_decorrelacion(
            autocorrelacion(sin_t.residual, max_rezago=500))["minutos"]
        tau_con = tiempo_decorrelacion(
            autocorrelacion(con_t.residual, max_rezago=500))["minutos"]
        assert tau_sin > tau_con


class TestMatrizHoraDia:
    def test_dimensiones(self, serie_ciclica):
        assert matriz_hora_dia(serie_ciclica, "temp_c.prom").shape[0] == 24


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
