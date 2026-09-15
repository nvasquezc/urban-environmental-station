"""Pruebas de la agregación temporal.

El énfasis está en las propiedades que distinguen una agregación correcta de
una plausible: composición energética del sonido, propagación de varianza y
rechazo de períodos incompletos.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from uestation.aggregate import (
    MINIMO_INTERVALOS_HORA,
    agregar_diario,
    agregar_horario,
    asignar_franja,
    componer_leq,
    estratificar,
    resumen_por_estrato,
)


class TestComposicionEnergetica:
    def test_niveles_iguales_devuelven_el_mismo_nivel(self):
        assert componer_leq([70.0] * 12) == 70.0

    def test_supera_la_media_aritmetica(self):
        """Propiedad fundamental: la composición energética nunca es menor.

        Con niveles dispares, el promedio aritmético subestima. Aquí la
        diferencia supera los 6 dB, magnitud que en un informe normativo
        sería la diferencia entre cumplir y no cumplir.
        """
        niveles = [50.0, 50.0, 50.0, 80.0]
        assert componer_leq(niveles) > np.mean(niveles) + 6.0

    def test_duplicar_energia_suma_3_db(self):
        """Dos fuentes de igual nivel producen +3 dB, no +3 unidades lineales."""
        uno = componer_leq([60.0])
        dos = 10 * np.log10(2 * 10 ** (60.0 / 10.0))
        assert abs(dos - uno - 3.0103) < 1e-3

    def test_ignora_no_finitos(self):
        assert componer_leq([70.0, np.nan, 70.0]) == 70.0

    def test_serie_vacia_devuelve_nan(self):
        assert np.isnan(componer_leq([]))


def _serie(n_intervalos: int, t0="2026-09-15 00:00:00", temp=19.0, amplitud=0.6):
    """Construye intervalos sintéticos con dispersión intra-intervalo conocida."""
    t = pd.date_range(t0, periods=n_intervalos, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "t_fin": t,
            "temp_c.prom": temp,
            "temp_c.min": temp - amplitud / 2,
            "temp_c.max": temp + amplitud / 2,
            "temp_c.n": 149,
            "hr_pct.prom": 62.0,
            "hr_pct.min": 61.0,
            "hr_pct.max": 63.0,
            "hr_pct.n": 149,
            "p_hpa.prom": 752.4,
            "p_hpa.min": 752.3,
            "p_hpa.max": 752.5,
            "p_hpa.n": 149,
            "son.trazable": False,
        }
    )


class TestAgregacionHoraria:
    def test_hora_completa_se_agrega(self):
        out = agregar_horario(_serie(12))
        assert len(out) == 1
        assert out.iloc[0]["n_intervalos"] == 12
        assert out.iloc[0]["cobertura"] == 1.0

    def test_hora_incompleta_se_rechaza(self):
        assert agregar_horario(_serie(9)).empty

    def test_umbral_exacto_se_acepta(self):
        out = agregar_horario(_serie(MINIMO_INTERVALOS_HORA))
        assert len(out) == 1

    def test_promedio_ponderado_por_muestras(self):
        df = _serie(12)
        df.loc[0, "temp_c.prom"] = 25.0
        df.loc[0, "temp_c.n"] = 20  # intervalo parcial: pesa menos
        out = agregar_horario(df)
        # Con ponderación uniforme daría 19.5; la ponderación lo acerca a 19.
        assert out.iloc[0]["temp_c_prom"] < 19.35

    def test_dispersion_intra_intervalo_se_propaga(self):
        """Doce intervalos de promedio idéntico pero con rango interno no nulo.

        Un cálculo ingenuo sobre los promedios daría sd = 0, lo que declararía
        una precisión inexistente. La ley de varianza total recupera la
        dispersión real de las muestras subyacentes.
        """
        out = agregar_horario(_serie(12, amplitud=3.0))
        assert out.iloc[0]["temp_c_sd"] > 0.4

    def test_extremos_son_de_las_muestras_no_de_los_promedios(self):
        out = agregar_horario(_serie(12, temp=19.0, amplitud=2.0))
        assert out.iloc[0]["temp_c_min"] == 18.0
        assert out.iloc[0]["temp_c_max"] == 20.0

    def test_muestras_se_acumulan(self):
        out = agregar_horario(_serie(12))
        assert out.iloc[0]["temp_c_n"] == 12 * 149

    def test_varias_horas(self):
        out = agregar_horario(_serie(36))
        assert len(out) == 3

    def test_hora_de_inicio_alineada(self):
        out = agregar_horario(_serie(12, t0="2026-09-15 03:00:00"))
        assert out.iloc[0]["hora_utc"] == pd.Timestamp("2026-09-15 03:00:00", tz="UTC")

    def test_zona_local_aplicada(self):
        out = agregar_horario(_serie(12, t0="2026-09-15 12:00:00"))
        assert out.iloc[0]["hora_local"].hour == 7

    def test_serie_vacia(self):
        assert agregar_horario(pd.DataFrame()).empty


class TestSonidoNoTrazable:
    def test_no_se_agrega_sonido_sin_trazabilidad(self):
        df = _serie(12)
        df["son.leq"] = 58.0
        df["son.lmax"] = 71.0
        df["son.trazable"] = False
        out = agregar_horario(df)
        assert "son_leq" not in out.columns

    def test_se_agrega_cuando_es_trazable(self):
        df = _serie(12)
        df["son.leq"] = 58.0
        df["son.lmax"] = 71.0
        df["son.trazable"] = True
        out = agregar_horario(df)
        assert abs(out.iloc[0]["son_leq"] - 58.0) < 1e-6


class TestEstratificacion:
    def test_franjas_cubren_el_dia(self):
        t = pd.Series(pd.date_range("2026-09-15", periods=24, freq="h", tz="America/Bogota"))
        f = asignar_franja(t)
        assert "indefinida" not in list(f)
        assert set(f) == {"madrugada", "mañana", "tarde", "noche"}

    def test_columnas_de_estrato_presentes(self):
        d = estratificar(_serie(288))
        assert {"franja", "hora_dia", "cuartil_hr"} <= set(d.columns)

    def test_hora_local_no_utc(self):
        """UTC-5: medianoche UTC corresponde a las 19:00 del día anterior."""
        d = estratificar(_serie(12, t0="2026-09-15 00:00:00"))
        assert d.iloc[0]["hora_dia"] == 19
        assert d.iloc[0]["franja"] == "noche"

    def test_resumen_por_estrato(self):
        d = estratificar(_serie(288))
        r = resumen_por_estrato(d, "temp_c.prom", "franja")
        assert r["n"].sum() == 288


class TestAgregacionDiaria:
    def test_dia_completo(self):
        """Se necesitan 48 h de datos para que exista un día local completo.

        La serie arranca a medianoche UTC, que en zona local (UTC-5) es el
        día anterior a las 19:00. Un día civil local queda cubierto solo
        cuando la serie abarca ambos extremos.
        """
        h = agregar_horario(_serie(576))  # 48 horas
        d = agregar_diario(h)
        assert len(d) >= 1

    def test_dia_incompleto_se_rechaza(self):
        h = agregar_horario(_serie(60))  # 5 horas
        assert agregar_diario(h).empty

    def test_amplitud_termica(self):
        df = _serie(576)
        df["temp_c.max"] = df["temp_c.prom"] + 1.0
        df["temp_c.min"] = df["temp_c.prom"] - 1.0
        d = agregar_diario(agregar_horario(df))
        assert not d.empty
        assert abs(d.iloc[0]["temp_c_amplitud"] - 2.0) < 1e-6
