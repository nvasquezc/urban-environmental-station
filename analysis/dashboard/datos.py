"""Capa de acceso a datos del tablero.

Estrategia de resiliencia: se intenta la lectura remota y, ante cualquier
fallo, se recurre a la última copia local. Una demostración no puede depender
de la disponibilidad de la red.

Cada lectura remota exitosa actualiza la copia local, de modo que el respaldo
se mantiene vigente sin intervención.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

RAIZ = Path(__file__).resolve().parents[2]
CACHE = Path(__file__).resolve().parent / "cache" / "ultimo.parquet"

DEVICE_ID = os.environ.get("UES_DEVICE_ID", "ues-b1c9fe")
DB_URL = os.environ.get("FIREBASE_DB_URL", "")
SECRETO = os.environ.get("FIREBASE_SECRET", "")

ESQUEMA_SOPORTADO = 1


def _normalizar(payload: dict) -> pd.DataFrame:
    df = pd.json_normalize(list(payload.values()))
    if df.empty:
        return df
    df["t_fin"] = pd.to_datetime(df["t_fin"], unit="s", utc=True)
    return df.sort_values("t_fin").reset_index(drop=True)


def leer_remoto(limite: int = 5000, timeout: int = 20) -> pd.DataFrame:
    """Descarga los últimos registros desde Firebase RTDB."""
    if not DB_URL or not SECRETO:
        raise RuntimeError("Faltan FIREBASE_DB_URL o FIREBASE_SECRET en el entorno.")

    r = requests.get(
        f"{DB_URL}/estaciones/{DEVICE_ID}/datos.json",
        params={"auth": SECRETO, "orderBy": '"$key"', "limitToLast": limite},
        timeout=timeout,
    )
    r.raise_for_status()
    return _normalizar(r.json() or {})


def guardar_cache(df: pd.DataFrame) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE, index=False)


def leer_cache() -> pd.DataFrame:
    if not CACHE.exists():
        return pd.DataFrame()
    return pd.read_parquet(CACHE)


def cargar(limite: int = 5000) -> tuple[pd.DataFrame, str]:
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
    valores nulos sin conversiones implícitas, y evita el formato de fecha
    deprecado de `to_json`.
    """
    import base64
    import io

    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def deserializar(blob: str) -> pd.DataFrame:
    """Reconstruye el DataFrame codificado por `serializar`."""
    import base64
    import io

    if not blob:
        return pd.DataFrame()
    return pd.read_parquet(io.BytesIO(base64.b64decode(blob)))
