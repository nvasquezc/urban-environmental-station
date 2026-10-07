
"""Exporta las figuras de la consola a PNG y genera el informe de resultados.

Reproduce, a partir de los datos y con el mismo código que alimenta la consola,
las figuras que documentan la campaña en el repositorio. A diferencia de una
captura de pantalla, el resultado es reproducible: cualquier persona con acceso a
los datos regenera exactamente las mismas figuras y cifras con un comando.

El informe `docs/07-resultados-campania.md` se genera en la misma ejecución, de
modo que texto y figuras corresponden siempre al mismo estado de los datos.

Todas las figuras se renderizan en una única sesión del navegador sin interfaz que
emplea Kaleido. Abrir y cerrar una instancia por figura resulta lento y, en
Windows, propenso a fallos al terminar el proceso.

El mapa de emplazamiento se excluye deliberadamente: el repositorio es público y
la posición del instrumento no se publica.

Uso:
    cd analysis
    uv run python tools/exportar_figuras.py                 # tema de la consola
    uv run python tools/exportar_figuras.py --tema claro    # fondo blanco, impresión
    uv run python tools/exportar_figuras.py --escala 3      # resolución de publicación
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import plotly.io as pio

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "analysis"))

from dashboard import figuras as F  # noqa: E402
from dashboard.datos import DEVICE_ID, cargar  # noqa: E402
from uestation.decompose import (  # noqa: E402
    ajustar_ciclo_diurno,
    detectar_tendencia,
    matriz_hora_dia,
)
from uestation.escalas import separar_escalas  # noqa: E402
from uestation.forecast import _cadencia_sugerida, predecir  # noqa: E402
from uestation.qc import (  # noqa: E402
    aplicar_qc,
    completitud,
    detectar_huecos,
    diagnostico_estabilidad,
)

TZ = "America/Bogota"
INTERVALO_MIN = 5
HORAS_PRONOSTICO = 24.0

DESTINO = RAIZ / "docs" / "figuras"
INFORME = RAIZ / "docs" / "07-resultados-campania.md"

ANCHO_COMPLETO = 1400
ANCHO_MEDIO = 760
ALTO_ENCABEZADO = 70
FONDO_PANEL = "#1A2542"

# Figuras generadas por versiones anteriores de este script. Se eliminan para
# que el repositorio no conserve figuras que ya no corresponden a los datos.
OBSOLETAS = [
    "02-autocorrelacion.png",
    "03-residual.png",
    "04-matriz.png",
    "05-estabilidad.png",
    "06-calidad.png",
]


# ============================================================================
#  Presentación
# ============================================================================
def _aclarar(fig):
    """Convierte una figura del tema de la consola a fondo blanco."""
    fig.update_layout(template="plotly_white", paper_bgcolor="white",
                      plot_bgcolor="white", font={"color": "#1A1A1A"})
    fig.update_xaxes(color="#4D4D4D", gridcolor="#E8E8E8")
    fig.update_yaxes(color="#4D4D4D", gridcolor="#E8E8E8")
    claros = {F.TEXTO, F.TEXTO_MED, F.TEXTO_BAJO}
    for anotacion in fig.layout.annotations:
        if anotacion.font is not None and anotacion.font.color in claros:
            anotacion.font.color = "#1A1A1A"
    return fig


def _encabezar(fig, titulo: str, subtitulo: str, tema: str):
    """Añade título y subtítulo, y fija un fondo sólido.

    En la consola, el título lo aporta la tarjeta que contiene la figura. Fuera
    de ella, la figura debe identificarse por sí misma. El fondo sólido evita que
    una figura de tema oscuro resulte ilegible sobre una página de fondo claro.
    """
    if tema == "oscuro":
        fig.update_layout(paper_bgcolor=FONDO_PANEL, plot_bgcolor=FONDO_PANEL)
        color_t, color_s = F.TEXTO, F.TEXTO_BAJO
    else:
        _aclarar(fig)
        color_t, color_s = "#1A1A1A", "#5A5A5A"

    margen = fig.layout.margin
    superior = margen.t if margen.t is not None else 20
    alto = int(fig.layout.height or 300)

    fig.update_layout(
        title={
            "text": f"<b>{titulo}</b>",
            "subtitle": {"text": subtitulo, "font": {"size": 12, "color": color_s}},
            "x": 0.015, "xanchor": "left",
            "yref": "container", "y": 0.97, "yanchor": "top",
            "font": {"size": 17, "color": color_t},
        },
        margin={"t": superior + ALTO_ENCABEZADO},
        height=alto + ALTO_ENCABEZADO,
    )
    return fig


def _exportar_lote(lote: list[tuple], escala: int) -> None:
    """Renderiza todas las figuras en una única sesión del navegador.

    `plotly.io.write_images`, disponible desde plotly 6.1, reutiliza la misma
    instancia de Kaleido para el lote completo. En versiones anteriores se
    recurre a la exportación individual.
    """
    figuras = [fig for fig, _, _ in lote]
    rutas = [str(DESTINO / f"{nombre}.png") for _, nombre, _ in lote]
    anchos = [ancho for _, _, ancho in lote]
    altos = [int(fig.layout.height) for fig in figuras]

    if hasattr(pio, "write_images"):
        pio.write_images(fig=figuras, file=rutas, width=anchos, height=altos,
                         scale=escala)
    else:
        for fig, ruta, ancho, alto in zip(figuras, rutas, anchos, altos, strict=True):
            fig.write_image(ruta, width=ancho, height=alto, scale=escala)

    for ruta in rutas:
        print(f"  {Path(ruta).relative_to(RAIZ)}")


def _num(valor, formato: str, defecto: str = "—") -> str:
    """Formatea un número; devuelve un guion si no es finito."""
    try:
        return format(valor, formato) if np.isfinite(valor) else defecto
    except (TypeError, ValueError):
        return defecto


# ============================================================================
#  Informe
# ============================================================================
def _informe(c: dict) -> str:
    """Construye el informe de resultados a partir de las cifras calculadas."""
    v = c["validacion"]
    e = c["escalas"]
    m = c["modelo"]
    r = c["contraste"]
    d = c["diagnostico"]

    lineas = [
        "# Resultados de la campaña",
        "",
        f"<!-- Generado por analysis/tools/exportar_figuras.py el "
        f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC. No editar a mano. -->",
        "",
        f"**Nodo:** `{DEVICE_ID}`  ",
        f"**Período:** {c['t0']:%Y-%m-%d %H:%M} a {c['t1']:%Y-%m-%d %H:%M} "
        f"(hora local) · {c['dias']:.1f} días  ",
        "**Estado de calibración:** sin calibrar",
        "",
        "## Operación",
        "",
        "| Indicador | Valor |",
        "|---|---|",
        f"| Registros válidos | {c['n_validos']} de {c['n_entrada']} "
        f"({100 * c['n_validos'] / c['n_entrada']:.1f} %) |",
        f"| Completitud | {c['completitud']:.1%} |",
        f"| Interrupciones | {c['n_huecos']} · {c['faltantes']} intervalos · "
        f"{c['horas_perdidas']:.1f} h |",
        f"| Arranques | {d.get('n_arranques', '—')} · "
        f"{d.get('reinicios_espontaneos', '—')} espontáneos |",
        f"| Intervalos recuperados por la cola persistente | "
        f"{d.get('intervalos_sin_red', '—')} |",
        f"| Memoria libre mínima | {_num(d.get('heap_min'), '.0f')} B · deriva "
        f"{_num(d.get('heap_pendiente_bytes_hora'), '+.1f')} B/h |",
        "",
        "![Estabilidad del nodo](figuras/07-estabilidad-nodo.png)",
        "",
        "## Señal",
        "",
        "| Magnitud | Valor |",
        "|---|---|",
        f"| Varianza explicada por el ciclo diurno | {m.varianza_explicada:.3f} |",
        f"| Dispersión residual | {m.sigma_residual:.3f} °C |",
        f"| Amplitud diurna | {m.amplitud_diurna:.2f} °C |",
        f"| Pendiente global | {r['pendiente_dia']:+.4f} °C/día |",
        f"| Tendencia incorporada | {'sí' if r['recomendada'] else 'no'} — "
        f"{r['motivo']} |",
        f"| Autocorrelación de primer orden | {r['rho_lag1']:.4f} |",
        f"| Tamaño efectivo de muestra | {r['n_efectivo']:.0f} de "
        f"{r['n_observaciones']} |",
        "",
        "![Descomposición de la señal](figuras/01-descomposicion.png)",
        "",
        "![Patrón hora por día](figuras/05-patron-hora-dia.png)",
        "",
        "![Distribución del residual](figuras/06-distribucion-residual.png)",
        "",
    ]

    if e is not None:
        lineas += [
            "## Escalas temporales del residual",
            "",
            "| Magnitud | Valor |",
            "|---|---|",
            f"| Tiempo de decorrelación intradiario | "
            f"{_num(e.tau_intradiario_min, '.0f')} min |",
            f"| Tiempo de decorrelación del residual completo | "
            f"{_num(e.tau_total_min, '.0f')} min |",
            f"| Fracción sinóptica de la varianza residual | "
            f"{e.fraccion_sinoptica:.0%} |",
            f"| Dispersión sinóptica | {np.sqrt(e.var_sinoptica):.3f} °C |",
            f"| Dispersión intradiaria | {np.sqrt(e.var_intradiaria):.3f} °C |",
            f"| Correlación entre jornadas consecutivas | "
            f"{_num(e.rho_diario, '+.2f')} |",
            f"| Cadencia de transmisión sugerida | {c['cadencia']} min |",
            "",
            "El tiempo de decorrelación del residual completo incorpora regímenes de "
            "varios días y crece con la longitud del registro: describe el período "
            "observado, no el proceso. El de la componente intradiaria, obtenido tras "
            "un filtro pasa altos de 24 h, es el que fija la cadencia de muestreo.",
            "",
            "![Persistencia intradiaria](figuras/02-persistencia-intradiaria.png)",
            "",
        ]

    if v is not None:
        lineas += [
            "## Pronóstico",
            "",
            f"Validación de origen móvil sobre {v.n_origenes} ventanas de "
            f"{v.horizonte_h:.0f} h, cada una pronosticada con parámetros "
            "estimados exclusivamente sobre los datos que la preceden.",
            "",
            "| Métrica | Valor |",
            "|---|---|",
            f"| Error absoluto medio | {v.mae:.3f} °C |",
            f"| Raíz del error cuadrático medio | {v.rmse:.3f} °C |",
            f"| Sesgo | {v.sesgo:+.3f} °C |",
            f"| Destreza frente a la climatología | {v.destreza:+.3f} |",
            f"| Destreza frente al ciclo sin persistencia | "
            f"{v.destreza_vs_ciclo:+.3f} |",
            f"| Cobertura de la banda | {v.cobertura:.1%} "
            f"(nominal {v.cobertura_nominal:.0%}) |",
            "",
            "| Horizonte | Error absoluto medio |",
            "|---|---|",
        ]
        for horizonte, mae in v.mae_por_horizonte.items():
            lineas.append(f"| ≤ {horizonte} | {mae:.3f} °C |")
        lineas += [
            "",
            "El error a horizontes cortos no constituye por sí solo evidencia de "
            "destreza: debe contrastarse con la persistencia ingenua del último valor.",
            "",
            "![Pronóstico](figuras/03-pronostico.png)",
            "",
            "![Error por horizonte](figuras/04-error-horizonte.png)",
            "",
        ]

    lineas += [
        "---",
        "",
        "**Alcance.** Lecturas sin corrección por calibración. La incertidumbre "
        "reportada recoge solo la dispersión intra-intervalo y constituye una cota "
        "inferior: la componente de calibración permanece indeterminada hasta "
        "completar la co-ubicación con una referencia trazable. Estos valores no "
        "deben emplearse con fines normativos.",
        "",
    ]
    return "\n".join(lineas)


# ============================================================================
#  Ejecución
# ============================================================================
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema", choices=["oscuro", "claro"], default="oscuro",
                    help="oscuro: tema de la consola; claro: fondo blanco")
    ap.add_argument("--escala", type=int, default=2,
                    help="factor de resolución (2 = pantalla, 3 = publicación)")
    args = ap.parse_args()

    DESTINO.mkdir(parents=True, exist_ok=True)
    for nombre in OBSOLETAS:
        (DESTINO / nombre).unlink(missing_ok=True)

    print(f"\nNodo {DEVICE_ID}")
    df, origen = cargar()
    if df.empty:
        print("Sin datos disponibles.")
        return
    print(f"  {len(df)} registros · {origen}")

    limpio, resumen = aplicar_qc(df)
    if limpio.empty:
        print("Ningún registro supera el control de calidad.")
        return

    # --- Cálculo ---
    contraste = detectar_tendencia(limpio, "temp_c.prom")
    modelo = ajustar_ciclo_diurno(limpio, "temp_c.prom",
                                  con_tendencia=contraste["recomendada"])
    try:
        escalas = separar_escalas(modelo, intervalo_min=INTERVALO_MIN)
    except ValueError:
        escalas = None

    pred = predecir(limpio, horas=HORAS_PRONOSTICO, intervalo_min=INTERVALO_MIN)
    validacion = pred.validacion if pred is not None else None

    diag = diagnostico_estabilidad(df)
    comp = completitud(limpio)
    huecos = detectar_huecos(limpio)

    t0 = limpio["t_fin"].min().tz_convert(TZ)
    t1 = limpio["t_fin"].max().tz_convert(TZ)
    dias = (t1 - t0).total_seconds() / 86400.0
    tema = args.tema

    # --- Construcción de figuras ---
    lote: list[tuple] = [(
        _encabezar(F.fig_descomposicion(modelo), "Descomposición de la señal",
                   f"Observado, ciclo diurno ajustado y residual · {dias:.1f} días · "
                   f"R² = {modelo.varianza_explicada:.3f}", tema),
        "01-descomposicion", ANCHO_COMPLETO,
    )]

    if escalas is not None:
        lote.append((
            _encabezar(F.fig_acf(escalas.acf_intradiaria,
                                 {"minutos": escalas.tau_intradiario_min},
                                 INTERVALO_MIN),
                       "Persistencia intradiaria",
                       "Autocorrelación del residual tras filtrar regímenes de 24 h · "
                       f"τ = {_num(escalas.tau_intradiario_min, '.0f')} min", tema),
            "02-persistencia-intradiaria", ANCHO_MEDIO,
        ))

    if pred is not None:
        lote.append((
            _encabezar(F.fig_prediccion(modelo, pred), "Pronóstico a 24 horas",
                       "Ciclo diurno con persistencia de régimen · "
                       "banda de predicción al 95 %", tema),
            "03-pronostico", ANCHO_COMPLETO,
        ))

    if validacion is not None:
        lote.append((
            _encabezar(F.fig_error_horizonte(validacion), "Error por horizonte",
                       "Error absoluto medio acumulado · origen móvil, "
                       f"{validacion.n_origenes} ventanas", tema),
            "04-error-horizonte", ANCHO_MEDIO,
        ))

    lote += [
        (_encabezar(F.fig_matriz(matriz_hora_dia(limpio, "temp_c.prom")),
                    "Patrón hora × día",
                    "Temperatura media por hora local y fecha · las celdas vacías "
                    "son intervalos ausentes", tema),
         "05-patron-hora-dia", ANCHO_MEDIO),
        (_encabezar(F.fig_histograma_residual(modelo), "Distribución del residual",
                    "Histograma con densidad normal de referencia · "
                    f"σ = {modelo.sigma_residual:.3f} °C", tema),
         "06-distribucion-residual", ANCHO_MEDIO),
        (_encabezar(F.fig_salud(df), "Estabilidad del nodo",
                    "Memoria libre y muestras por intervalo · las líneas punteadas "
                    "marcan arranques", tema),
         "07-estabilidad-nodo", ANCHO_COMPLETO),
    ]

    # --- Exportación en una sola sesión ---
    print(f"\nFiguras · tema {tema} · escala {args.escala}x")
    _exportar_lote(lote, args.escala)

    # --- Informe ---
    faltantes = int(huecos["intervalos_faltantes"].sum()) if not huecos.empty else 0
    horas_perdidas = (float(huecos["duracion_s"].sum() / 3600)
                      if not huecos.empty else 0.0)
    cadencia = (_cadencia_sugerida(escalas.tau_intradiario_min, INTERVALO_MIN)
                if escalas is not None else INTERVALO_MIN)

    INFORME.write_text(_informe({
        "t0": t0, "t1": t1, "dias": dias,
        "n_validos": len(limpio), "n_entrada": resumen.n_entrada,
        "completitud": comp["completitud"],
        "n_huecos": len(huecos), "faltantes": faltantes,
        "horas_perdidas": horas_perdidas,
        "diagnostico": diag, "modelo": modelo, "contraste": contraste,
        "escalas": escalas, "validacion": validacion, "cadencia": cadencia,
    }), encoding="utf-8")
    print(f"\nInforme\n  {INFORME.relative_to(RAIZ)}\n")


if __name__ == "__main__":
    main()
