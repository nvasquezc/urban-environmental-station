"""Descarga registros desde Firebase RTDB a la capa bronze."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

ESQUEMA_SOPORTADO = {1}
RAIZ = Path(__file__).resolve().parents[3]


def descargar(db_url: str, device_id: str, secreto: str, limite: int = 5000) -> pd.DataFrame:
    r = requests.get(
        f"{db_url}/estaciones/{device_id}/datos.json",
        params={"auth": secreto, "orderBy": '"$key"', "limitToLast": limite},
        timeout=60,
    )
    r.raise_for_status()
    payload = r.json() or {}
    df = pd.json_normalize(list(payload.values()))
    if df.empty:
        return df

    vistos = set(df.get("esquema", pd.Series(dtype="Int64")).dropna().unique())
    desconocidos = vistos - ESQUEMA_SOPORTADO
    if desconocidos:
        raise ValueError(f"Versiones de esquema no soportadas: {sorted(desconocidos)}")

    df["t_fin"] = pd.to_datetime(df["t_fin"], unit="s", utc=True)
    return df.sort_values("t_fin").reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", required=True)
    ap.add_argument("--limite", type=int, default=5000)
    args = ap.parse_args()

    df = descargar(
        os.environ["FIREBASE_DB_URL"],
        args.device,
        os.environ["FIREBASE_SECRET"],
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
    print(f"{len(df)} registros -> {ruta}")


if __name__ == "__main__":
    main()
