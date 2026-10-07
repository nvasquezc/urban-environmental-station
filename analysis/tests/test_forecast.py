"""Pruebas de la capa predictiva y prescriptiva."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uestation.forecast import (
    Recomendacion,
    _cadencia_sugerida,
    predecir,
    prescribir,
    validar_fuera_de_muestra,
)
from uestation.qc import ResumenQC


def _serie(dias=8, amplitud=4.0, ruido=0.2, pendiente=0.0, semilla=5):
    """Ciclo diurno sintético con residual independiente."""
    rng = np.random.default_rng(semilla)
    n = 288 * dias
    t = pd.date_range("2026-09-15", periods=n, freq="5min", tz="UTC")
    local = t.tz_convert("America/Bogota")
    h = local.hour + local.minute / 60.0
    d = np.arange(n) * 5 / 1440.0
    y = (19.0 + pendiente * d
         + amplitud * np.sin(2 * np.pi * (h - 9) / 24.0)
         + rng.normal(0, ruido, n))
    return pd.DataFrame({"t_fin": t, "temp_c.prom": y})


def _serie_persistente(dias=8, phi=0.97, semilla=9):
    """Ciclo diurno con residual autocorrelado AR(1)."""
    rng = np.random.default_rng(semilla)
    n = 288 * dias
    t = pd.date_range("2026-09-15", periods=n, freq="5min", tz="UTC")
    local = t.tz_convert("America/Bogota")
    h = local.hour + local.minute / 60.0

    e = rng.normal(0, 0.2, n)
    r = np.zeros(n)
    for i in range(1, n):
        r[i] = phi * r[i - 1] + e[i]

    return pd.DataFrame({
        "t_fin": t,
        "temp_c.prom": 19.0 + 4.0 * np.sin(2 * np.pi * (h - 9) / 24.0) + r,
    })


def _serie_con_regimen(dias=20, amp=1.5, periodo_d=8.0, semilla=6):
    """Ciclo diurno + régimen sinóptico + ruido AR(1): la condición de campo."""
    rng = np.random.default_rng(semilla)
    n = 288 * dias
    t = pd.date_range("2026-09-15", periods=n, freq="5min", tz="UTC")
    local = t.tz_convert("America/Bogota")
    h = local.hour + local.minute / 60.0
    dia = np.arange(n) * 5 / 1440.0

    e = rng.normal(0, 0.15, n)
    r = np.zeros(n)
    for i in range(1, n):
        r[i] = 0.95 * r[i - 1] + e[i]

    y = (19.0 + 4.0 * np.sin(2 * np.pi * (h - 9) / 24.0)
         + amp * np.sin(2 * np.pi * dia / periodo_d) + r)
    return pd.DataFrame({"t_fin": t, "temp_c.prom": y})


def _resumen(n=2000, descartados=0):
    return ResumenQC(n_entrada=n, n_salida=n - descartados)


@pytest.fixture
def serie():
    return _serie()


class TestValidacion:
    def test_particion_temporal(self, serie):
        """Con un origen, la ventana de prueba son las últimas 24 h."""
        v = validar_fuera_de_muestra(serie, horas_prueba=24.0)
        assert v is not None
        assert v.n == pytest.approx(288, abs=2)
        assert v.n_origenes == 1

    def test_origen_movil(self, serie):
        v = validar_fuera_de_muestra(serie, n_origenes=4)
        assert v.n_origenes == 4
        assert v.n == pytest.approx(4 * 288, abs=8)

    def test_recupera_el_error_del_ruido(self, serie):
        v = validar_fuera_de_muestra(serie)
        assert v.mae < 0.35

    def test_cobertura_proxima_a_la_nominal(self, serie):
        v = validar_fuera_de_muestra(serie, n_origenes=3)
        assert abs(v.cobertura - 0.95) < 0.10

    def test_supera_la_climatologia(self, serie):
        v = validar_fuera_de_muestra(serie)
        assert v.supera_referencia
        assert v.destreza > 0.5

    def test_sin_ciclo_no_hay_destreza(self):
        rng = np.random.default_rng(3)
        t = pd.date_range("2026-09-15", periods=288 * 8, freq="5min", tz="UTC")
        df = pd.DataFrame({"t_fin": t,
                           "temp_c.prom": 19.0 + rng.normal(0, 1, len(t))})
        v = validar_fuera_de_muestra(df)
        assert v.destreza < 0.15

    def test_reporta_error_por_horizonte(self, serie):
        v = validar_fuera_de_muestra(serie)
        assert {"1 h", "6 h", "24 h"} <= set(v.mae_por_horizonte)

    def test_serie_corta_devuelve_none(self):
        t = pd.date_range("2026-09-15", periods=50, freq="5min", tz="UTC")
        df = pd.DataFrame({"t_fin": t, "temp_c.prom": 19.0})
        assert validar_fuera_de_muestra(df) is None


class TestPersistencia:
    def test_la_persistencia_mejora_al_ciclo(self):
        """Con régimen sinóptico, la persistencia supera al ciclo por sí solo."""
        v = validar_fuera_de_muestra(_serie_con_regimen(), n_origenes=5)
        assert v.persistencia_aporta
        assert v.mae < v.mae_ciclo

    def test_el_error_crece_con_el_horizonte(self):
        """La anomalía presente informa más a corto que a largo plazo."""
        v = validar_fuera_de_muestra(_serie_con_regimen(), n_origenes=5)
        assert v.mae_por_horizonte["1 h"] < v.mae_por_horizonte["24 h"]

    def test_la_banda_se_ensancha_con_el_horizonte(self):
        p = predecir(_serie_persistente())
        ancho = p.superior - p.esperado
        assert ancho[-1] > ancho[0]

    def test_estado_acotado(self):
        p = predecir(_serie_con_regimen())
        assert p.estado is not None
        assert 0.0 <= p.estado.rho_diario <= 0.95
        assert p.estado.tau_intradiario_min > 0


class TestPrediccion:
    def test_longitud_del_horizonte(self, serie):
        p = predecir(serie, horas=24.0, intervalo_min=5)
        assert p is not None
        assert len(p.esperado) == 288

    def test_comienza_tras_el_ultimo_dato(self, serie):
        assert predecir(serie).tiempo.iloc[0] > serie["t_fin"].iloc[-1]

    def test_banda_simetrica_y_positiva(self, serie):
        p = predecir(serie)
        assert np.all(p.superior > p.esperado)
        assert np.all(p.inferior < p.esperado)
        assert np.allclose(p.superior - p.esperado, p.esperado - p.inferior)

    def test_reproduce_la_amplitud_del_ciclo(self, serie):
        p = predecir(serie)
        assert 7.0 < (p.esperado.max() - p.esperado.min()) < 9.0

    def test_no_extrapola_deriva_no_confirmada(self, serie):
        assert not predecir(serie).con_tendencia

    def test_extrapola_deriva_confirmada(self):
        p = predecir(_serie(dias=8, pendiente=0.35))
        assert p.con_tendencia
        assert any("deriva" in a for a in p.advertencias)

    def test_advierte_sobre_el_horizonte(self, serie):
        p = predecir(serie, horas=48.0)
        assert any("decorrelación" in a for a in p.advertencias)

    def test_incluye_validacion(self, serie):
        assert predecir(serie, validar=True).validacion is not None

    def test_validacion_omitible(self, serie):
        assert predecir(serie, validar=False).validacion is None

    def test_serie_corta_devuelve_none(self):
        t = pd.date_range("2026-09-15", periods=50, freq="5min", tz="UTC")
        df = pd.DataFrame({"t_fin": t, "temp_c.prom": 19.0})
        assert predecir(df) is None


class TestCadencia:
    def test_regla_de_un_tercio(self):
        assert _cadencia_sugerida(75.0, 5) == 25

    def test_no_reduce_por_debajo_del_actual(self):
        assert _cadencia_sugerida(6.0, 5) == 5

    def test_acotada_a_una_hora(self):
        assert _cadencia_sugerida(600.0, 5) == 60

    def test_tau_indefinido_conserva_la_cadencia(self):
        assert _cadencia_sugerida(np.nan, 5) == 5


class TestPrescripcion:
    def test_ordena_por_prioridad(self, serie):
        p = predecir(serie)
        recs = prescribir(serie, serie, {"reinicios_espontaneos": 2}, _resumen(), p)
        prioridades = [r.prioridad for r in recs]
        assert prioridades == sorted(
            prioridades, key=lambda x: {"alta": 0, "media": 1, "baja": 2}[x])

    def test_sugiere_ampliar_la_cadencia_si_hay_redundancia(self):
        df = _serie_persistente()
        recs = prescribir(df, df, {}, _resumen(), predecir(df))
        assert any(r.categoria == "energia" for r in recs)

    def test_sin_redundancia_no_sugiere_cadencia(self, serie):
        recs = prescribir(serie, serie, {}, _resumen(), predecir(serie))
        assert not any(r.categoria == "energia" for r in recs)

    def test_senala_reinicios_espontaneos(self, serie):
        recs = prescribir(serie, serie, {"reinicios_espontaneos": 3}, _resumen(), None)
        r = next(r for r in recs if "reinicios" in r.titulo.lower())
        assert r.prioridad == "alta"

    def test_senala_degradacion_de_memoria(self, serie):
        recs = prescribir(serie, serie,
                          {"heap_pendiente_bytes_hora": -120.0, "heap_min": 6000},
                          _resumen(), None)
        assert any("memoria" in r.titulo.lower() for r in recs)

    def test_senala_rechazo_excesivo(self, serie):
        recs = prescribir(serie, serie, {}, _resumen(n=1000, descartados=200), None)
        r = next(r for r in recs if "rechazo" in r.titulo.lower())
        assert r.prioridad == "alta"

    def test_siempre_recuerda_la_calibracion(self, serie):
        recs = prescribir(serie, serie, {}, _resumen(), None)
        assert any("co-ubicación" in r.titulo for r in recs)

    def test_recomienda_extender_el_periodo(self, serie):
        recs = prescribir(serie, serie, {}, _resumen(), None)
        assert any("Extender" in r.titulo for r in recs)

    def test_toda_recomendacion_tiene_justificacion(self, serie):
        recs = prescribir(serie, serie, {"reinicios_espontaneos": 1},
                          _resumen(), predecir(serie))
        assert all(isinstance(r, Recomendacion) and len(r.detalle) > 40
                   for r in recs)
