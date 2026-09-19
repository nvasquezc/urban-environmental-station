"""Exporta las figuras del análisis a PNG de resolución de publicación.

Ejecuta la cadena completa (descarga, control de calidad, descomposición) y
escribe las figuras en docs/figuras/, junto con un resumen de los estadísticos
en formato Markdown.

Las figuras exportadas quedan versionadas en el repositorio: a diferencia de un
servicio desplegado, no dependen de disponibilidad externa ni caducan.

Uso:
    cd analysis
    uv run python tools/exportar_figuras.py
    uv run python tools/exportar_figuras.py --tema claro --escala 3
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "analysis"))

from dashboard import figuras as F  # noqa: E402
from dashboard.datos import DEVICE_ID, cargar  # noqa: E402
from uestation.decompose import (  # noqa: E402
    ajustar_ciclo_diurno,
    autocorrelacion,
    incertidumbre_expandida,
    matriz_hora_dia,
    tiempo_decorrelacion,
)
from uestation.qc import (  # noqa: E402
    aplicar_qc,
    completitud,
    detectar_huecos,
    diagnostico_estabilidad,
)

DESTINO = RAIZ / "docs" / "figuras"
INTERVALO_MIN = 5

# Dimensiones en píxeles antes de aplicar la escala.
ANCHO_COMPLETO = 1200
ANCHO_MEDIO = 620


def _aclarar(fig):
    """Convierte una figura del tema oscuro a fondo claro para impresión."""
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="white",
        plot_bgcolor="white",
        font={"color": "#1A1A1A"},
    )
    fig.update_xaxes(color="#4D4D4D", gridcolor="#E8E8E8")
    fig.update_yaxes(color="#4D4D4D", gridcolor="#E8E8E8")
    for anot in fig.layout.annotations:
        if anot.font and anot.font.color in ("#EAF0FB", "#93A3C4", "#64749A"):
            anot.font.color = "#1A1A1A"
    return fig


def exportar(fig, nombre: str, ancho: int, escala: int, tema: str) -> Path:
    if tema == "claro":
        fig = _aclarar(fig)
    ruta = DESTINO / f"{nombre}.png"
    fig.write_image(str(ruta), width=ancho, height=fig.layout.height, scale=escala)
    print(f"  {ruta.relative_to(RAIZ)}  ({ancho}×{fig.layout.height} @{escala}x)")
    return ruta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema", choices=["oscuro", "claro"], default="oscuro",
                    help="oscuro para el README; claro para impresión")
    ap.add_argument("--escala", type=int, default=2,
                    help="factor de resolución (2 = retina, 3 = publicación)")
    args = ap.parse_args()

    DESTINO.mkdir(parents=True, exist_ok=True)

    print(f"Descargando datos del nodo {DEVICE_ID}...")
    df, origen = cargar()
    if df.empty:
        print("Sin datos disponibles. Verifique las variables de entorno.")
        return
    print(f"  {len(df)} registros · {origen}\n")

    limpio, resumen = aplicar_qc(df)
    if limpio.empty:
        print("Ningún registro supera el control de calidad.")
        return

    c = completitud(limpio)
    u = incertidumbre_expandida(limpio)
    diag = diagnostico_estabilidad(df)
    huecos = detectar_huecos(limpio)

    try:
        d = ajustar_ciclo_diurno(limpio, "temp_c.prom")
    except (ValueError, np.linalg.LinAlgError) as e:
        print(f"No fue posible ajustar el ciclo diurno: {e}")
        return

    acf = autocorrelacion(d.residual, max_rezago=min(288, len(limpio) // 2))
    td = tiempo_decorrelacion(acf)

    print(f"Exportando figuras (tema {args.tema}, escala {args.escala}x)...")
    exportar(F.fig_descomposicion(d), "01-descomposicion",
             ANCHO_COMPLETO, args.escala, args.tema)
    exportar(F.fig_acf(acf, td, INTERVALO_MIN), "02-autocorrelacion",
             ANCHO_MEDIO, args.escala, args.tema)
    exportar(F.fig_histograma_residual(d), "03-residual",
             ANCHO_MEDIO, args.escala, args.tema)
    exportar(F.fig_matriz(matriz_hora_dia(limpio, "temp_c.prom")), "04-matriz",
             ANCHO_MEDIO, args.escala, args.tema)
    exportar(F.fig_salud(df), "05-estabilidad",
             ANCHO_COMPLETO, args.escala, args.tema)
    exportar(F.fig_donut_calidad(resumen), "06-calidad",
             ANCHO_MEDIO, args.escala, args.tema)

    # --- Resumen de resultados ---
    t0 = limpio["t_fin"].min().tz_convert("America/Bogota")
    t1 = limpio["t_fin"].max().tz_convert("America/Bogota")
    tau = td.get("minutos", np.nan)

    lineas = [
        "# Resultados de la campaña",
        "",
        f"<!-- Generado por analysis/tools/exportar_figuras.py el "
        f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC. No editar a mano. -->",
        "",
        f"**Nodo:** `{DEVICE_ID}`  ",
        f"**Período:** {t0:%Y-%m-%d %H:%M} a {t1:%Y-%m-%d %H:%M} (hora local)  ",
        f"**Estado de calibración:** sin calibrar",
        "",
        "## Indicadores",
        "",
        "| Magnitud | Valor | Observación |",
        "|---|---|---|",
        f"| Registros válidos | {len(limpio)} | de {resumen.n_entrada} evaluados |",
        f"| Completitud | {c['completitud']:.1%} | {c['presentes']} de "
        f"{c['esperados']} intervalos esperados |",
        f"| Varianza explicada | {d.varianza_explicada:.3f} | ciclo diurno, "
        f"{d.n_armonicos} armónicos |",
        f"| Dispersión residual | {d.sigma_residual:.3f} °C | no explicada por el ciclo |",
        f"| Incertidumbre U (k=2) | {u.get('U_expandida_k2', float('nan')):.4f} °C | "
        "cota inferior, excluye calibración |",
        f"| Tiempo de decorrelación | {tau:.0f} min | "
        f"sobremuestreo de factor {tau / INTERVALO_MIN:.0f} |"
        if np.isfinite(tau) else "| Tiempo de decorrelación | — | no estimable |",
        f"| Arranques | {diag.get('n_arranques', 0)} | "
        f"{diag.get('reinicios_espontaneos', 0)} espontáneos |",
        f"| Deriva de memoria | {diag.get('heap_pendiente_bytes_hora', 0):+.1f} B/h | "
        "regresión sobre el período |",
        f"| Interrupciones | {len(huecos)} | discontinuidades en la serie |",
        "",
        "## Figuras",
        "",
        "### Descomposición de la señal",
        "",
        "![Descomposición](figuras/01-descomposicion.png)",
        "",
        f"El ciclo diurno ajustado mediante {d.n_armonicos} armónicos de Fourier "
        f"explica el {d.varianza_explicada:.1%} de la varianza observada. El residual "
        f"presenta una dispersión de {d.sigma_residual:.3f} °C, comparable a la "
        "incertidumbre de fábrica del sensor AHT20 (±0.3 °C).",
        "",
        "### Estructura temporal",
        "",
        "![Autocorrelación](figuras/02-autocorrelacion.png)",
        "",
    ]

    if np.isfinite(tau):
        lineas += [
            f"La autocorrelación del residual decae por debajo de 1/e a los "
            f"{tau:.0f} minutos, frente a un intervalo de muestreo de "
            f"{INTERVALO_MIN} minutos. El sistema opera con un sobremuestreo de "
            f"factor {tau / INTERVALO_MIN:.0f}, lo que acota empíricamente el "
            "intervalo de transmisión mínimo necesario y abre margen para reducir "
            "el consumo energético sin pérdida de contenido informativo.",
            "",
        ]

    lineas += [
        "![Matriz hora-día](figuras/04-matriz.png)",
        "",
        "### Distribución del residual",
        "",
        "![Residual](figuras/03-residual.png)",
        "",
        "### Estabilidad del instrumento",
        "",
        "![Estabilidad](figuras/05-estabilidad.png)",
        "",
        "![Calidad](figuras/06-calidad.png)",
        "",
        "---",
        "",
        "**Alcance.** Lecturas sin corrección por calibración. La incertidumbre "
        "reportada recoge únicamente la dispersión intra-intervalo y constituye una "
        "cota inferior: la componente de calibración permanece indeterminada hasta "
        "completar la co-ubicación con una referencia trazable. Estos valores no "
        "deben emplearse con fines normativos.",
    ]

    ruta_md = RAIZ / "docs" / "07-resultados-campania.md"
    ruta_md.write_text("\n".join(lineas), encoding="utf-8")
    print(f"\n  {ruta_md.relative_to(RAIZ)}")
    print("\nListo.")


if __name__ == "__main__":
    main()
