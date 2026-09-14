from uestation.ingest import ESQUEMA_SOPORTADO


def test_esquema_soportado_no_vacio():
    assert ESQUEMA_SOPORTADO


def test_esquema_actual_soportado():
    assert 1 in ESQUEMA_SOPORTADO
