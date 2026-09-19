"""Consola de monitoreo de la estación ambiental urbana.

Vista única: estado del sistema, descomposición de la señal, estructura
temporal y registro de eventos, sin navegación intermedia.

Ejecución:
    cd analysis
    uv run python -m dashboard.app
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dash import Dash, Input, Output, dcc, html

from dashboard import figuras as F
from dashboard.datos import DEVICE_ID, cargar, deserializar, serializar
from uestation.decompose import (
    ajustar_ciclo_diurno,
    autocorrelacion,
    incertidumbre_expandida,
    matriz_hora_dia,
    tiempo_decorrelacion,
)
from uestation.qc import aplicar_qc, completitud, detectar_huecos, diagnostico_estabilidad

DOI = "10.5281/zenodo.22740968"
REPO = "https://github.com/nvasquezc/urban-environmental-station"
INTERVALO_MIN = 5
TZ = "America/Bogota"

app = Dash(__name__, title="UES · Consola", suppress_callback_exceptions=True)
server = app.server

SECCIONES = ["Resumen", "Señal", "Temporal", "Instrumento", "Calidad"]


def kpi(rotulo, id_cifra, unidad, id_nota, clase):
    return html.Div([
        html.Div(rotulo, className="kpi-rotulo"),
        html.Div([
            html.Span(id=id_cifra),
            html.Span(unidad, className="kpi-unidad"),
        ], className="kpi-cifra"),
        html.Div(id=id_nota, className="kpi-nota"),
    ], className=f"kpi {clase}", style={"gridColumn": "span 3"})


def panel(titulo, sub, hijos, cols):
    return html.Div(
        [html.Div(titulo, className="tarjeta-titulo"),
         html.Div(sub, className="tarjeta-sub")] + hijos,
        className="tarjeta", style={"gridColumn": f"span {cols}"})


app.layout = html.Div([
    dcc.Store(id="store"),
    dcc.Interval(id="reloj", interval=5 * 60 * 1000, n_intervals=0),

    html.Div([

        # ---------- Barra lateral ----------
        html.Div([
            html.Div([
                html.Div("UES", className="logo-marca"),
                html.Div("Estación", className="logo-texto"),
            ], className="logo"),

            html.Div([
                html.Div([html.Div(className="nav-punto"), s],
                         className="nav-item activo" if i == 0 else "nav-item")
                for i, s in enumerate(SECCIONES)
            ]),

            html.Div([
                html.Div([
                    html.Div("NV", className="avatar"),
                    html.Div([
                        html.Div("N. Vásquez", className="perfil-nombre"),
                        html.Div("Investigador", className="perfil-rol"),
                    ]),
                ], className="perfil"),
            ], className="lateral-pie"),
        ], className="lateral"),

        # ---------- Principal ----------
        html.Div([

            html.Div([
                html.Div([
                    html.H1("Monitoreo ambiental urbano"),
                    html.Div(f"Nodo {DEVICE_ID} · Bogotá · UTC−5", className="sub"),
                ]),
                html.Div([
                    html.Span([html.Span(className="pulso"), html.Span(id="origen")],
                              className="chip chip-vivo"),
                    html.Span("Sin calibrar", className="chip chip-aviso"),
                    html.Span(html.A("DOI", href=f"https://doi.org/{DOI}",
                                     target="_blank"), className="chip"),
                    html.Span(html.A("Repositorio", href=REPO, target="_blank"),
                              className="chip"),
                ], className="chips"),
            ], className="encabezado"),

            html.Div([

                # Fila 1 — indicadores
                kpi("Decorrelación", "k-tau", " min", "k-tau-nota", "kpi-violeta"),
                kpi("Registros válidos", "k-n", "", "k-n-nota", "kpi-cian"),
                kpi("Varianza explicada", "k-r2", "", "k-r2-nota", "kpi-verde"),
                kpi("Dispersión residual", "k-sigma", " °C", "k-sigma-nota", "kpi-rosa"),

                # Fila 2 — descomposición + calidad
                panel("Descomposición de la señal",
                      "Observado, ciclo diurno ajustado y residual con banda ±2σ",
                      [dcc.Graph(id="g-descomp", config={"displayModeBar": False})], 8),

                panel("Control de calidad",
                      "Registros que superan los siete criterios del protocolo",
                      [dcc.Graph(id="g-donut", config={"displayModeBar": False})], 4),

                # Fila 3 — ACF + matriz + eventos
                panel("Persistencia temporal",
                      "Autocorrelación del residual y tiempo de decorrelación",
                      [dcc.Graph(id="g-acf", config={"displayModeBar": False})], 4),

                panel("Patrón hora × día",
                      "Temperatura media por hora local y fecha",
                      [dcc.Graph(id="g-matriz", config={"displayModeBar": False})], 4),

                panel("Eventos recientes",
                      "Anomalías y sucesos del sistema",
                      [html.Div(id="eventos")], 4),

                # Fila 4 — salud + histograma + diagnóstico
                panel("Estabilidad del nodo",
                      "Memoria libre y completitud del muestreo",
                      [dcc.Graph(id="g-salud", config={"displayModeBar": False})], 5),

                panel("Distribución del residual",
                      "Histograma con densidad normal de referencia",
                      [dcc.Graph(id="g-hist", config={"displayModeBar": False})], 4),

                panel("Diagnóstico",
                      "Indicadores del instrumento",
                      [html.Table(html.Tbody(id="tabla"), className="tabla")], 3),

            ], className="rejilla"),

            html.Div([
                html.B("Alcance. "),
                "Lecturas sin corrección por calibración. La incertidumbre reportada "
                "recoge solo la dispersión intra-intervalo y constituye una cota "
                "inferior: la componente de calibración permanece indeterminada hasta "
                "completar la co-ubicación con una referencia trazable. No apto para "
                "uso normativo.",
            ], className="pie-nota"),

            html.Div([
                html.Span("Vásquez Castro, N. O. (2026) · Jitter Ingeniería SAS / "
                          "Universidad Central"),
                html.A(f"doi:{DOI}", href=f"https://doi.org/{DOI}", target="_blank"),
            ], className="creditos"),

        ], className="principal"),

    ], className="marco"),
])


# --- Datos ------------------------------------------------------------------
@app.callback(Output("store", "data"), Output("origen", "children"),
              Input("reloj", "n_intervals"))
def _cargar(_):
    df, origen = cargar()
    return serializar(df), origen.split("·")[0].strip().upper()


def _preparar(blob):
    df = deserializar(blob)
    if df.empty:
        return None, None, None
    limpio, resumen = aplicar_qc(df)
    return df, limpio, resumen


def _descomponer(limpio):
    try:
        return ajustar_ciclo_diurno(limpio, "temp_c.prom")
    except (ValueError, np.linalg.LinAlgError):
        return None


# --- Indicadores ------------------------------------------------------------
@app.callback(
    Output("k-tau", "children"), Output("k-tau-nota", "children"),
    Output("k-n", "children"), Output("k-n-nota", "children"),
    Output("k-r2", "children"), Output("k-r2-nota", "children"),
    Output("k-sigma", "children"), Output("k-sigma-nota", "children"),
    Input("store", "data"),
)
def _kpis(blob):
    g = "—"
    nada = (g, "", g, "", g, "", g, "")
    if not blob:
        return nada

    _, limpio, resumen = _preparar(blob)
    if limpio is None or limpio.empty:
        return nada

    c = completitud(limpio)
    u = incertidumbre_expandida(limpio)
    d = _descomponer(limpio)

    tau_txt, tau_nota = g, ""
    if d is not None:
        a = autocorrelacion(d.residual, max_rezago=min(288, len(limpio) // 2))
        tau = tiempo_decorrelacion(a).get("minutos", np.nan)
        if np.isfinite(tau):
            tau_txt = f"{tau:.0f}"
            tau_nota = [html.B(f"{tau / INTERVALO_MIN:.0f}× "),
                        f"sobre el intervalo de {INTERVALO_MIN} min"]

    r2_txt = f"{d.varianza_explicada:.3f}" if d else g
    r2_nota = (f"El ciclo diurno explica el {d.varianza_explicada:.1%} de la varianza"
               if d else "")

    sigma_txt = f"{d.sigma_residual:.3f}" if d else g
    u_val = u.get("U_expandida_k2")
    sigma_nota = ([html.B(f"U = {u_val:.3f} °C "), "(k=2, cota inferior)"]
                  if u_val else "")

    return (
        tau_txt, tau_nota,
        f"{len(limpio)}",
        [html.B(f"{c['completitud'] * 100:.1f}% "), "de completitud"],
        r2_txt, r2_nota,
        sigma_txt, sigma_nota,
    )


# --- Figuras y listas -------------------------------------------------------
@app.callback(
    Output("g-descomp", "figure"), Output("g-donut", "figure"),
    Output("g-acf", "figure"), Output("g-matriz", "figure"),
    Output("g-salud", "figure"), Output("g-hist", "figure"),
    Output("eventos", "children"), Output("tabla", "children"),
    Input("store", "data"),
)
def _figuras(blob):
    v = F.fig_vacia()
    if not blob:
        return v, v, v, v, v, v, [], []

    df, limpio, resumen = _preparar(blob)
    if limpio is None or limpio.empty:
        return v, v, v, v, v, v, [], []

    d = _descomponer(limpio)

    if d is not None:
        a = autocorrelacion(d.residual, max_rezago=min(288, len(limpio) // 2))
        f_desc = F.fig_descomposicion(d)
        f_acf = F.fig_acf(a, tiempo_decorrelacion(a), INTERVALO_MIN)
        f_hist = F.fig_histograma_residual(d)
    else:
        f_desc = f_acf = f_hist = F.fig_vacia("Serie insuficiente")

    diag = diagnostico_estabilidad(df)
    huecos = detectar_huecos(limpio)

    return (
        f_desc,
        F.fig_donut_calidad(resumen),
        f_acf,
        F.fig_matriz(matriz_hora_dia(limpio, "temp_c.prom")),
        F.fig_salud(df),
        f_hist,
        _eventos(d, df, huecos),
        _tabla(diag, huecos),
    )


def _eventos(d, df, huecos, maximo: int = 6):
    """Registro de sucesos: anomalías agrupadas, reinicios e interrupciones.

    Los residuales consecutivos fuera de banda se agrupan en un solo evento y
    se reportan por su pico, evitando que una excursión sostenida genere
    decenas de entradas.
    """
    filas = []

    if d is not None:
        anom = d.anomalias(k=2.0).to_numpy()
        resid = d.residual.to_numpy(dtype=float)
        t_series = d.tiempo.dt.tz_convert(TZ).to_numpy()

        if anom.any():
            idx = np.flatnonzero(anom)
            grupos = np.split(idx, np.flatnonzero(np.diff(idx) > 3) + 1)
            for grupo in grupos:
                if grupo.size == 0:
                    continue
                pico = grupo[np.argmax(np.abs(resid[grupo]))]
                valor = float(resid[pico])
                t = pd.Timestamp(t_series[pico])
                alto = valor > 0
                filas.append((
                    t, "▲" if alto else "▼", "ev-alto" if alto else "ev-bajo",
                    "Desviación térmica",
                    f"{grupo.size} intervalos · {t:%d %b %H:%M}",
                    f"{valor:+.2f} °C",
                    "alerta" if alto else "ok",
                ))

    if "boot" in df.columns:
        pos = np.flatnonzero(df["boot"].ne(df["boot"].shift(1)).to_numpy())[1:]
        for p in pos:
            t = df["t_fin"].iloc[p].tz_convert(TZ)
            causa = str(df["diag.reset"].iloc[p]) if "diag.reset" in df.columns else "—"
            filas.append((
                t, "⟳", "ev-fallo", "Reinicio del nodo",
                f"{causa} · {t:%d %b %H:%M}",
                f"boot {int(df['boot'].iloc[p])}", "malo",
            ))

    for _, h in huecos.iterrows():
        t = pd.Timestamp(h["fin"]).tz_convert(TZ)
        filas.append((
            t, "⌀", "ev-fallo", "Interrupción de datos",
            f"{int(h['intervalos_faltantes'])} intervalos · {t:%d %b %H:%M}",
            f"{h['duracion_s'] / 60:.0f} min", "malo",
        ))

    if not filas:
        return html.Div("Sin eventos en el período", className="sin-eventos")

    filas.sort(key=lambda f: f[0], reverse=True)

    return [
        html.Div([
            html.Div(ico, className=f"evento-icono {clase}"),
            html.Div([
                html.Div(titulo, className="evento-titulo"),
                html.Div(meta, className="evento-meta"),
            ], className="evento-cuerpo"),
            html.Div(valor, className=f"evento-valor {color}"),
        ], className="evento")
        for _, ico, clase, titulo, meta, valor, color in filas[:maximo]
    ]


def _tabla(diag, huecos):
    def fila(k, v, clase=""):
        return html.Tr([html.Td(k), html.Td(v, className=clase)])

    esp = diag.get("reinicios_espontaneos", 0)
    pend = diag.get("heap_pendiente_bytes_hora", 0.0)

    return [
        fila("Arranques", diag.get("n_arranques", "—")),
        fila("Reinicios espontáneos", esp, "ok" if esp == 0 else "malo"),
        fila("Heap mínimo", f"{diag.get('heap_min', 0):.0f} B"),
        fila("Deriva heap", f"{pend:+.1f} B/h", "ok" if abs(pend) < 20 else "alerta"),
        fila("Fragmentación", f"{diag.get('frag_max_pct', 0):.0f} %"),
        fila("Muestras (moda)", diag.get("muestras_moda", "—")),
        fila("Muestras (mín.)", diag.get("muestras_min", "—")),
        fila("Sin red", diag.get("intervalos_sin_red", "—")),
        fila("Interrupciones", len(huecos), "ok" if len(huecos) == 0 else "alerta"),
        fila("RSSI mediana", f"{diag.get('rssi_mediana', 0):.0f} dBm"),
    ]


if __name__ == "__main__":
    import os

    # El recargador de Werkzeug falla en Windows al reservar memoria compartida
    # cuando ya existe una instancia activa. Se desactiva manteniendo el modo
    # de depuración para conservar los mensajes de error en el navegador.
    app.run(debug=True, use_reloader=False,
            port=int(os.environ.get("PORT", 8050)))
