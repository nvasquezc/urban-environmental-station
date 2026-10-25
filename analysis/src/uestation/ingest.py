"""Descarga registros desde Firebase RTDB a la capa bronze.

Este módulo es el único punto de acceso a la base de datos: la consola
(`dashboard/datos.py`) y la línea de comandos usan la misma función
`descargar`, de modo que el límite de lectura y la validación de esquema
no pueden divergir entre ambos caminos.
"""

from __future__ import annotations

import argparse
import os
import warnings
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

ESQUEMA_SOPORTADO = {1}
RAIZ = Path(__file__).resolve().parents[3]

# Equivale a unos 200 días de operación continua a 288 registros diarios.
# Un límite insuficiente recorta en silencio el inicio de la serie: con el
# valor anterior (5000) se perdía todo lo previo a los últimos ~17 días.
LIMITE_DEFECTO = 60_000


class SerieRecortadaWarning(UserWarning):
    """La descarga alcanzó el límite: la serie puede estar incompleta."""


def normalizar(payload: dict, esquemas: set[int] | None = None) -> pd.DataFrame:
    """Convierte la respuesta de RTDB en un DataFrame ordenado por `t_fin`.

    Rechaza versiones de esquema desconocidas en lugar de interpretar su
    semántica.
    """
    esquemas = ESQUEMA_SOPORTADO if esquemas is None else esquemas
    df = pd.json_normalize(list((payload or {}).values()))
    if df.empty:
        return df

    if "esquema" in df.columns:
        vistos = {int(v) for v in df["esquema"].dropna().unique()}
        desconocidos = vistos - esquemas
        if desconocidos:
            raise ValueError(f"Versiones de esquema no soportadas: {sorted(desconocidos)}")

    df["t_fin"] = pd.to_datetime(df["t_fin"], unit="s", utc=True)
    return df.sort_values("t_fin").reset_index(drop=True)


def descargar(
    db_url: str,
    device_id: str,
    secreto: str,
    limite: int = LIMITE_DEFECTO,
    timeout: int = 60,
) -> pd.DataFrame:
    """Descarga los registros de un nodo.

    Emite `SerieRecortadaWarning` si el número recibido alcanza el límite.
    """
    if not db_url or not secreto:
        raise RuntimeError(
            "Faltan FIREBASE_DB_URL o FIREBASE_SECRET. Defínalas en analysis/.env o en el entorno."
        )
    r = requests.get(
        f"{db_url}/estaciones/{device_id}/datos.json",
        params={"auth": secreto, "orderBy": '"$key"', "limitToLast": limite},
        timeout=timeout,
    )
    r.raise_for_status()
    df = normalizar(r.json() or {})

    if len(df) >= limite:
        warnings.warn(
            f"Se recibieron {len(df)} registros, igual al límite solicitado. "
            "La serie puede estar recortada; aumente el límite.",
            SerieRecortadaWarning,
            stacklevel=2,
        )
    return df


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(RAIZ / "analysis" / ".env")

    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default=os.environ.get("UES_DEVICE_ID"))
    ap.add_argument("--limite", type=int, default=LIMITE_DEFECTO)
    args = ap.parse_args()
    if not args.device:
        ap.error("Indique --device o defina UES_DEVICE_ID en analysis/.env")

    df = descargar(
        os.environ.get("FIREBASE_DB_URL", ""),
        args.device,
        os.environ.get("FIREBASE_SECRET", ""),
        args.limite,
    )
    if df.empty:
        print("Sin registros.")
        return

    destino = RAIZ / "data/bronze" / args.device
    destino.mkdir(parents=True, exist_ok=True)
    sello = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    ruta = destino / f"{sello}.parquet"
    df.to_parquet(ruta, index=False)
    print(
        f"{len(df)} registros ({df['t_fin'].min():%Y-%m-%d} a "
        f"{df['t_fin'].max():%Y-%m-%d %H:%M} UTC) -> {ruta}"
    )


if __name__ == "__main__":
    main()
