"""Capa de acceso a datos del tablero.

Estrategia de resiliencia: se intenta la lectura remota y, ante cualquier
fallo, se recurre a la última copia local. Una demostración no puede depender
de la disponibilidad de la red.

Cada lectura remota exitosa actualiza la copia local, de modo que el respaldo
se mantiene vigente sin intervención.

El límite de lectura debe exceder holgadamente el número de registros de la
campaña: con 288 intervalos diarios, un límite insuficiente recorta en
silencio el inicio de la serie y sesga cualquier estadístico calculado sobre
ella.
"""

from __future__ import annotations

import base64
import io
import os
import warnings
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from uestation.ingest import LIMITE_DEFECTO, SerieRecortadaWarning, descargar

RAIZ = Path(__file__).resolve().parents[2]
CACHE = Path(__file__).resolve().parent / "cache" / "ultimo.parquet"

# Las credenciales se cargan desde analysis/.env antes de leer el entorno:
# las constantes siguientes se evalúan una sola vez, al importar el módulo.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DEVICE_ID = os.environ.get("UES_DEVICE_ID", "ues-b1c9fe")
DB_URL = os.environ.get("FIREBASE_DB_URL", "")
SECRETO = os.environ.get("FIREBASE_SECRET", "")


def leer_remoto(limite: int = LIMITE_DEFECTO, timeout: int = 60) -> pd.DataFrame:
    """Descarga los registros desde Firebase RTDB.

    Delega en `uestation.ingest.descargar`, único punto de acceso a la base.
    Si la serie alcanza el límite solicitado, la advertencia se informa en
    consola: la serie podría estar recortada.
    """
    with warnings.catch_warnings(record=True) as avisos:
        warnings.simplefilter("always", SerieRecortadaWarning)
        df = descargar(DB_URL, DEVICE_ID, SECRETO, limite, timeout)
    for aviso in avisos:
        print(f"[datos] ADVERTENCIA: {aviso.message}")
    return df


def guardar_cache(df: pd.DataFrame) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE, index=False)


def leer_cache() -> pd.DataFrame:
    if not CACHE.exists():
        return pd.DataFrame()
    return pd.read_parquet(CACHE)


def cargar(limite: int = LIMITE_DEFECTO) -> tuple[pd.DataFrame, str]:
    """Devuelve los datos y el origen efectivo de la lectura.

    El origen se informa en la interfaz: un tablero que muestra datos en
    caché sin declararlo induce a error sobre la vigencia de lo observado.
    """
    try:
        df = leer_remoto(limite)
        if not df.empty:
            guardar_cache(df)
            sello = datetime.now(UTC).strftime("%H:%M UTC")
            return df, f"en línea · {sello}"
    except Exception as exc:  # noqa: BLE001 — cualquier fallo degrada a caché
        print(f"[datos] Lectura remota fallida: {exc}")

    df = leer_cache()
    if df.empty:
        return df, "sin datos"

    ultimo = pd.to_datetime(df["t_fin"]).max()
    return df, f"copia local · último dato {ultimo:%d/%m %H:%M} UTC"


def serializar(df: pd.DataFrame) -> str:
    """Codifica el DataFrame para transporte entre callbacks.

    Se usa Parquet en base64 en lugar de JSON: preserva tipos, zona horaria y
    valores nulos sin conversiones implícitas.
    """
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def deserializar(blob: str) -> pd.DataFrame:
    """Reconstruye el DataFrame codificado por `serializar`."""
    if not blob:
        return pd.DataFrame()
    return pd.read_parquet(io.BytesIO(base64.b64decode(blob)))
