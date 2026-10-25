"""Pruebas del control de calidad.

Cada prueba verifica una propiedad del filtrado sobre datos sintéticos con
defectos conocidos. El objetivo no es cobertura sino falsabilidad: si el
filtrado dejara de detectar un defecto, alguna de estas pruebas debe fallar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from uestation.qc import (
    FRACCION_MAXIMA_CLIP,
    MUESTRAS_MINIMAS_CLIMA,
    aplicar_qc,
    completitud,
    detectar_huecos,
    diagnostico_estabilidad,
    sonido_saturado,
)


class TestSerieNominal:
    def test_no_descarta_nada(self, df_nominal):
        limpio, resumen = aplicar_qc(df_nominal)
        assert resumen.n_entrada == 288
        assert resumen.n_salida == 288
        assert resumen.fraccion_descartada == 0.0

    def test_completitud_total(self, df_nominal):
        c = completitud(df_nominal)
        assert c["completitud"] == 1.0

    def test_sin_huecos(self, df_nominal):
        assert detectar_huecos(df_nominal).empty


class TestDeteccionDeDefectos:
    def test_cuenta_total(self, df_con_defectos):
        _, resumen = aplicar_qc(df_con_defectos)
        assert resumen.n_descartado == 6

    def test_atribucion_por_causa(self, df_con_defectos):
        _, r = aplicar_qc(df_con_defectos)
        assert r.descartes["muestras_insuficientes"] == 1
        assert r.descartes["sensor_caido"] == 1
        assert r.descartes["fuera_de_rango"] == 1
        assert r.descartes["esquema_desconocido"] == 1
        assert r.descartes["sin_timestamp"] == 1
        assert r.descartes["intervalo_con_reinicio"] == 1

    def test_causas_suman_el_total(self, df_con_defectos):
        """Ningún registro se descarta sin causa atribuida, ni se cuenta dos veces."""
        _, r = aplicar_qc(df_con_defectos)
        assert sum(r.descartes.values()) == r.n_descartado

    def test_umbral_de_muestras(self):
        assert MUESTRAS_MINIMAS_CLIMA == 120

    def test_marcas_no_filtran(self, df_con_defectos):
        d, r = aplicar_qc(df_con_defectos, devolver_marcas=True)
        assert len(d) == 40
        assert (~d["qc_ok"]).sum() == 6

    def test_primer_registro_no_se_descarta_por_reinicio(self, df_nominal):
        """Una serie que empieza en seq=1 no implica intervalo parcial."""
        _, r = aplicar_qc(df_nominal)
        assert r.descartes["intervalo_con_reinicio"] == 0


class TestEsquema:
    def test_rechaza_esquema_futuro(self, df_nominal):
        df = df_nominal.copy()
        df.loc[0:9, "esquema"] = 2
        _, r = aplicar_qc(df, esquema_soportado=1)
        assert r.descartes["esquema_desconocido"] == 10

    def test_rechaza_ausencia_de_esquema(self, df_nominal):
        df = df_nominal.drop(columns=["esquema"])
        _, r = aplicar_qc(df)
        assert r.descartes["esquema_desconocido"] == 288


class TestHuecos:
    def test_detecta_interrupcion(self, df_con_hueco):
        h = detectar_huecos(df_con_hueco)
        assert len(h) == 1
        assert h.iloc[0]["intervalos_faltantes"] == 12

    def test_completitud_refleja_el_hueco(self, df_con_hueco):
        c = completitud(df_con_hueco)
        assert c["presentes"] == 40
        assert c["completitud"] < 1.0


class TestDiagnosticoEstabilidad:
    def test_detecta_fuga_de_memoria(self, df_con_fuga):
        d = diagnostico_estabilidad(df_con_fuga)
        assert d["heap_pendiente_bytes_hora"] < -500

    def test_heap_estable_no_da_falso_positivo(self, df_nominal):
        d = diagnostico_estabilidad(df_nominal)
        assert abs(d["heap_pendiente_bytes_hora"]) < 1.0

    def test_cuenta_arranques(self, df_con_defectos):
        d = diagnostico_estabilidad(df_con_defectos)
        assert d["n_arranques"] == 2

    def test_reinicios_inducidos_no_son_incidentes(self, df_nominal):
        d = diagnostico_estabilidad(df_nominal)
        assert d["reinicios_espontaneos"] == 0

    def test_reinicio_espontaneo_se_contabiliza(self, df_nominal):
        df = df_nominal.copy()
        df.loc[100:, "boot"] = 2
        df.loc[100:, "diag.reset"] = "Software Watchdog"
        d = diagnostico_estabilidad(df)
        assert d["reinicios_espontaneos"] == 1


class TestSerieVacia:
    def test_no_falla(self):
        vacio = pd.DataFrame(columns=["t_fin", "esquema"])
        limpio, r = aplicar_qc(vacio)
        assert limpio.empty
        assert r.n_entrada == 0


class TestSonidoSaturado:
    def _con_sonido(self, df, clip):
        d = df.copy()
        d["son.n"] = 2400
        d["son.clip"] = clip
        d["son.leq"] = 40.0
        return d

    def test_marca_sin_descartar(self, df_nominal):
        clip = np.zeros(len(df_nominal), dtype=int)
        clip[:10] = 2400   # saturación total
        clip[10:20] = 5    # 0.2 %: tolerado
        d = self._con_sonido(df_nominal, clip)
        limpio, r = aplicar_qc(d)
        assert len(limpio) == len(df_nominal)  # el clima no se pierde
        assert r.marcas["son_saturado"] == 10
        assert (~limpio["son.qc_ok"]).sum() == 10
        assert "son_saturado" in r.a_markdown()

    def test_umbral(self, df_nominal):
        d = self._con_sonido(df_nominal, 0)
        d.loc[0, "son.clip"] = int(2400 * FRACCION_MAXIMA_CLIP)      # en el umbral
        d.loc[1, "son.clip"] = int(2400 * FRACCION_MAXIMA_CLIP) + 1  # lo excede
        sat = sonido_saturado(d)
        assert not sat.iloc[0] and sat.iloc[1]

    def test_sin_bloques_es_saturado(self, df_nominal):
        d = self._con_sonido(df_nominal, 0)
        d.loc[0, "son.n"] = 0
        assert sonido_saturado(d).iloc[0]

    def test_sin_columnas_de_sonido_no_marca(self, df_nominal):
        limpio, r = aplicar_qc(df_nominal)
        assert "son.qc_ok" not in limpio.columns
        assert r.marcas == {}


class TestRssiCentinela:
    def test_rssi_positivo_se_excluye(self, df_nominal):
        d = df_nominal.copy()
        d.loc[:4, "diag.rssi"] = 31.0
        d.loc[5:9, "diag.rssi"] = np.nan
        diag = diagnostico_estabilidad(d)
        assert diag["rssi_centinela"] == 5
        assert diag["intervalos_sin_red"] == 10
        assert diag["rssi_mediana"] == -67.0
        assert diag["rssi_min"] <= 0
