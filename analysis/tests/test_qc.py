"""Pruebas del control de calidad.

Cada prueba verifica una propiedad del filtrado sobre datos sintéticos con
defectos conocidos. El objetivo no es cobertura sino falsabilidad: si el
filtrado dejara de detectar un defecto, alguna de estas pruebas debe fallar.
"""

from __future__ import annotations

import pandas as pd

from uestation.qc import (
    MUESTRAS_MINIMAS_CLIMA,
    aplicar_qc,
    completitud,
    detectar_huecos,
    diagnostico_estabilidad,
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
