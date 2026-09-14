"""Genera los coeficientes IIR de ponderacion A (IEC 61672) para el firmware.

Uso:  uv run python tools/gen_aweighting.py --fs 16000
Salida: firmware/lib/sound/aweighting_coeffs.h
"""

import argparse
from pathlib import Path

import numpy as np
from scipy.signal import bilinear_zpk, freqs_zpk, sosfreqz, zpk2sos

# Polos del prototipo analogico de ponderacion A (IEC 61672-1)
F1, F2, F3, F4 = 20.598997, 107.65265, 737.86223, 12194.217


def prototipo_analogico():
    z = np.zeros(4)
    p = -2 * np.pi * np.array([F1, F1, F2, F3, F4, F4])
    # Normalizacion: |H(1 kHz)| = 1
    w = np.array([2 * np.pi * 1000.0])
    _, h = freqs_zpk(z, p, 1.0, worN=w)
    return z, p, 1.0 / np.abs(h[0])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fs", type=int, default=16000)
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "firmware/lib/sound/aweighting_coeffs.h",
    )
    args = ap.parse_args()

    z, p, k = prototipo_analogico()
    zd, pd, kd = bilinear_zpk(z, p, k, args.fs)
    sos = zpk2sos(zd, pd, kd)

    # Verificacion contra bandas de tercio de octava
    f = np.array([31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000], dtype=float)
    f = f[f < args.fs / 2]
    w = 2 * np.pi * f / args.fs
    _, h = sosfreqz(sos, worN=w)
    db = 20 * np.log10(np.abs(h) + 1e-30)

    print(f"fs = {args.fs} Hz, {len(sos)} secciones\n")
    print(" f [Hz]   A(f) digital")
    for fi, di in zip(f, db, strict=True):
        print(f"{fi:8.1f}   {di:+7.2f} dB")

    lineas = [
        "// GENERADO AUTOMATICAMENTE por analysis/tools/gen_aweighting.py",
        "// NO EDITAR A MANO. Regenerar si cambia la frecuencia de muestreo.",
        f"// Ponderacion A (IEC 61672-1), fs = {args.fs} Hz",
        "#pragma once",
        "",
        f"static const int AW_NSOS = {len(sos)};",
        f"static const float AW_SOS[{len(sos)}][6] = {{",
    ]
    for s in sos:
        vals = ", ".join(f"{v:+.10e}f" for v in s)
        lineas.append(f"    {{{vals}}},")
    lineas += ["};", ""]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lineas), encoding="utf-8")
    print(f"\nEscrito: {args.out}")


if __name__ == "__main__":
    main()
