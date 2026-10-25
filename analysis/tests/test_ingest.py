"""Pruebas del acceso a Firebase sin red: se sustituye `requests.get`."""

from __future__ import annotations

import pandas as pd
import pytest

from uestation import ingest


class _Respuesta:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._payload


def _payload(n: int, esquema: int = 1) -> dict:
    t0 = 1_789_500_000
    return {
        str(t0 + 300 * i): {"t_fin": t0 + 300 * i, "esquema": esquema, "temp_c": {"prom": 15.0}}
        for i in range(n)
    }


@pytest.fixture
def falso_get(monkeypatch):
    llamadas: list[dict] = []

    def instalar(payload):
        def get(url, params=None, timeout=None):
            llamadas.append({"url": url, "params": params})
            return _Respuesta(payload)

        monkeypatch.setattr(ingest.requests, "get", get)
        return llamadas

    return instalar


def test_limite_por_defecto_cubre_campanias_largas():
    # 288 intervalos diarios: el límite debe cubrir varios meses de operación.
    assert ingest.LIMITE_DEFECTO >= 288 * 180


def test_descargar_usa_limite_por_defecto(falso_get):
    llamadas = falso_get(_payload(3))
    ingest.descargar("https://x", "nodo", "s")
    assert llamadas[0]["params"]["limitToLast"] == ingest.LIMITE_DEFECTO


def test_descargar_ordena_y_convierte_tiempo(falso_get):
    p = _payload(5)
    falso_get(dict(reversed(list(p.items()))))
    df = ingest.descargar("https://x", "nodo", "s")
    assert len(df) == 5
    assert isinstance(df["t_fin"].dtype, pd.DatetimeTZDtype)
    assert df["t_fin"].is_monotonic_increasing


def test_advierte_si_alcanza_el_limite(falso_get):
    falso_get(_payload(10))
    with pytest.warns(ingest.SerieRecortadaWarning):
        ingest.descargar("https://x", "nodo", "s", limite=10)


def test_rechaza_esquema_desconocido(falso_get):
    falso_get(_payload(3, esquema=2))
    with pytest.raises(ValueError, match="esquema"):
        ingest.descargar("https://x", "nodo", "s")


def test_sin_credenciales_falla_explicitamente():
    with pytest.raises(RuntimeError, match="FIREBASE"):
        ingest.descargar("", "nodo", "")


def test_respuesta_vacia(falso_get):
    falso_get(None)
    assert ingest.descargar("https://x", "nodo", "s").empty
