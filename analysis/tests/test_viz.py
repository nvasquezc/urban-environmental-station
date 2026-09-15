"""Pruebas de las figuras de publicación.

No se verifica la apariencia sino las propiedades verificables: que los
estadísticos anotados sean correctos, que los elementos obligatorios estén
presentes y que la paleta sea la declarada.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from uestation.viz import (
    OKABE_ITO,
    SECUENCIA,
    fig_bland_altman,
    fig_boxplot_estratificado,
    fig_diagnostico_nodo,
    fig_dispersion_ajuste,
    fig_evolucion_coeficientes,
    fig_residual_vs_covariable,
    fig_serie_temporal,
)


@pytest.fixture
def pares():
    """Pares estación-referencia con sesgo conocido de +0.50 °C."""
    rng = np.random.default_rng(42)
    ref = np.linspace(12.0, 26.0, 300)
    est = ref + 0.50 + rng.normal(0, 0.12, 300)
    return pd.DataFrame({"referencia": ref, "estacion": est})


@pytest.fixture
def serie():
    t = pd.date_range("2026-09-15", periods=288, freq="5min", tz="UTC")
    prom = 19.0 + 3.0 * np.sin(np.linspace(0, 2 * np.pi, 288))
    return pd.DataFrame({
        "t_fin": t,
        "temp_c.prom": prom,
        "temp_c.min": prom - 0.3,
        "temp_c.max": prom + 0.3,
        "temp_c.n": 149,
        "hr_pct.prom": 62.0,
        "diag.heap": 6656,
        "diag.rssi": -67.0,
        "boot": 1,
    })


class TestPaleta:
    def test_okabe_ito_completa(self):
        assert len(OKABE_ITO) == 9
        assert all(c.startswith("#") and len(c) == 7 for c in OKABE_ITO.values())

    def test_secuencia_sin_repeticiones(self):
        assert len(set(SECUENCIA)) == len(SECUENCIA)


class TestSerieTemporal:
    def test_devuelve_figura(self, serie):
        assert isinstance(fig_serie_temporal(serie), go.Figure)

    def test_banda_presente(self, serie):
        f = fig_serie_temporal(serie, mostrar_banda=True)
        assert any(t.fill == "tonexty" for t in f.data)

    def test_banda_omitible(self, serie):
        f = fig_serie_temporal(serie, mostrar_banda=False)
        assert len(f.data) == 1

    def test_declara_sin_calibrar(self, serie):
        f = fig_serie_temporal(serie, cal="sin-calibrar")
        assert any("SIN CALIBRAR" in a.text for a in f.layout.annotations)

    def test_declara_campania(self, serie):
        f = fig_serie_temporal(serie, cal="2026-11-rmcab")
        assert any("2026-11-rmcab" in a.text for a in f.layout.annotations)


class TestDispersion:
    def test_incluye_linea_identidad(self, pares):
        f = fig_dispersion_ajuste(pares, "estacion", "referencia")
        assert any(t.name == "identidad (1:1)" for t in f.data)

    def test_anota_pendiente_correcta(self, pares):
        f = fig_dispersion_ajuste(pares, "estacion", "referencia")
        texto = f.layout.annotations[0].text
        assert "y = 0.9" in texto or "y = 1.0" in texto
        assert "R² = 0.99" in texto

    def test_ejes_a_igual_escala(self, pares):
        """Sin escala común, una desviación de la identidad se ve distorsionada."""
        f = fig_dispersion_ajuste(pares, "estacion", "referencia")
        assert f.layout.yaxis.scaleanchor == "x"

    def test_rechaza_muestra_insuficiente(self):
        d = pd.DataFrame({"a": [1.0, 2.0], "b": [1.0, 2.0]})
        with pytest.raises(ValueError):
            fig_dispersion_ajuste(d, "a", "b")


class TestBlandAltman:
    def test_sesgo_correcto(self, pares):
        f = fig_bland_altman(pares, "estacion", "referencia")
        textos = [s.text for s in f.layout.shapes if hasattr(s, "text")]
        anot = [a.text for a in f.layout.annotations]
        assert any("+0.4" in t or "+0.5" in t for t in anot + textos if t)

    def test_tres_lineas_de_referencia(self, pares):
        f = fig_bland_altman(pares, "estacion", "referencia")
        horizontales = [s for s in f.layout.shapes if s.type == "line"]
        assert len(horizontales) >= 3

    def test_incluye_tendencia(self, pares):
        f = fig_bland_altman(pares, "estacion", "referencia")
        assert any("tendencia" in (t.name or "") for t in f.data)

    def test_rechaza_muestra_insuficiente(self):
        d = pd.DataFrame({"a": [1.0], "b": [1.0]})
        with pytest.raises(ValueError):
            fig_bland_altman(d, "a", "b")


class TestResidual:
    def test_linea_en_cero(self, pares):
        d = pares.copy()
        d["residual"] = d["estacion"] - d["referencia"]
        d["hr"] = np.linspace(40, 90, len(d))
        f = fig_residual_vs_covariable(d, "residual", "hr")
        assert any(s.type == "line" and s.y0 == 0 for s in f.layout.shapes)

    def test_media_movil_presente(self, pares):
        d = pares.copy()
        d["residual"] = d["estacion"] - d["referencia"]
        d["hr"] = np.linspace(40, 90, len(d))
        f = fig_residual_vs_covariable(d, "residual", "hr")
        assert any("media móvil" in (t.name or "") for t in f.data)


class TestEvolucionCoeficientes:
    def test_barras_de_error(self):
        d = pd.DataFrame({
            "bloque": [1, 2, 3, 4],
            "pendiente": [1.002, 0.998, 0.995, 0.991],
            "ic_inf": [0.996, 0.992, 0.989, 0.985],
            "ic_sup": [1.008, 1.004, 1.001, 0.997],
            "unidad": ["ues-01"] * 4,
        })
        f = fig_evolucion_coeficientes(d)
        assert f.data[0].error_y.array is not None

    def test_varias_unidades_con_marcadores_distintos(self):
        d = pd.DataFrame({
            "bloque": [1, 2] * 3,
            "pendiente": [1.0, 0.99] * 3,
            "ic_inf": [0.99, 0.98] * 3,
            "ic_sup": [1.01, 1.00] * 3,
            "unidad": ["A", "A", "B", "B", "C", "C"],
        })
        f = fig_evolucion_coeficientes(d)
        simbolos = {t.marker.symbol for t in f.data}
        assert len(f.data) == 3
        assert len(simbolos) == 3


class TestBoxplotEstratificado:
    def test_una_caja_por_estrato(self):
        rng = np.random.default_rng(0)
        d = pd.DataFrame({
            "error": rng.normal(0.3, 0.1, 400),
            "franja": ["madrugada", "mañana", "tarde", "noche"] * 100,
        })
        f = fig_boxplot_estratificado(d, "error")
        assert len(f.data) == 4

    def test_umbral_visible(self):
        d = pd.DataFrame({"error": [0.1, 0.2, 0.3], "franja": ["a", "a", "b"]})
        f = fig_boxplot_estratificado(d, "error", umbral=0.5)
        assert any(s.type == "line" for s in f.layout.shapes)


class TestDiagnostico:
    def test_tres_paneles(self, serie):
        f = fig_diagnostico_nodo(serie)
        assert len(f.data) == 3

    def test_marca_reinicios(self, serie):
        d = serie.copy()
        d.loc[100:, "boot"] = 2
        f = fig_diagnostico_nodo(d)
        assert len(f.layout.shapes) >= 1
