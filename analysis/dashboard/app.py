"""Consola de monitoreo de la estación ambiental urbana.

Dos vistas seleccionables desde la barra lateral: el resumen operativo, que
recoge el estado del sistema y el diagnóstico de la señal, y el pronóstico,
que aloja la capa predictiva junto a las recomendaciones que de ella derivan.

La separación responde a que ambas responden preguntas distintas: la primera,
qué está ocurriendo; la segunda, qué cabe esperar y qué conviene hacer.

El modelo de descomposición incorpora un término de tendencia únicamente
cuando el contraste de `detectar_tendencia` lo confirma. Los indicadores
derivados dependen de esa decisión, de modo que el panel de contraste no es
informativo sino constitutivo: documenta por qué los valores son los que son.

Ejecución:
    cd analysis
    uv run python -m dashboard.app
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
from dash import ALL, Dash, Input, Output, ctx, dcc, html

from dashboard import figuras as F
from dashboard.datos import DEVICE_ID, cargar, deserializar, serializar
from uestation.decompose import (
    ajustar_ciclo_diurno,
    autocorrelacion,
    detectar_tendencia,
    incertidumbre_expandida,
    matriz_hora_dia,
    tiempo_decorrelacion,
)
from uestation.forecast import predecir, prescribir
from uestation.qc import aplicar_qc, completitud, detectar_huecos, diagnostico_estabilidad

DOI = "10.5281/zenodo.22740968"
REPO = "https://github.com/nvasquezc/urban-environmental-station"
INTERVALO_MIN = 5
HORAS_PRONOSTICO = 24.0
TZ = "America/Bogota"

# Posición de referencia cuando no hay fijación satelital disponible.
LAT_DEFECTO = float(os.environ.get("UES_LAT", 4.6097))
LON_DEFECTO = float(os.environ.get("UES_LON", -74.0817))

app = Dash(__name__, title="UES · Consola", suppress_callback_exceptions=True)
server = app.server

VISTAS = [("resumen", "Resumen"), ("pronostico", "Pronóstico")]

TITULOS = {
    "resumen": "Monitoreo ambiental urbano",
    "pronostico": "Pronóstico y recomendaciones",
}


def kpi(rotulo, id_cifra, unidad, id_nota, clase, cols=3):
    return html.Div([
        html.Div(rotulo, className="kpi-rotulo"),
        html.Div([
            html.Span(id=id_cifra),
            html.Span(unidad, className="kpi-unidad"),
        ], className="kpi-cifra"),
        html.Div(id=id_nota, className="kpi-nota"),
    ], className=f"kpi {clase}", style={"gridColumn": f"span {cols}"})


def panel(titulo, sub, hijos, cols):
    return html.Div(
        [html.Div(titulo, className="tarjeta-titulo"),
         html.Div(sub, className="tarjeta-sub")] + hijos,
        className="tarjeta", style={"gridColumn": f"span {cols}"})


def barra_qc(etiqueta, id_valor, id_relleno, id_nota):
    """Indicador de barra para el encabezado."""
    return html.Div([
        html.Div([
            html.Span(etiqueta, className="qc-etiqueta"),
            html.Span(id=id_valor, className="qc-valor"),
        ], className="qc-fila"),
        html.Div(html.Div(id=id_relleno, className="qc-relleno"),
                 className="qc-pista"),
        html.Div(id=id_nota, className="qc-nota"),
    ], className="qc-item")


def botones_nav(activa: str) -> list:
    """Reconstruye la barra de navegación marcando la vista en curso."""
    return [
        html.Button(
            [html.Div(className="nav-punto"), etiqueta],
            id={"tipo": "nav", "vista": clave},
            className="nav-item activo" if clave == activa else "nav-item",
            n_clicks=0,
        )
        for clave, etiqueta in VISTAS
    ]


app.layout = html.Div([
    dcc.Store(id="store"),
    dcc.Store(id="vista", data="resumen"),
    dcc.Interval(id="reloj", interval=5 * 60 * 1000, n_intervals=0),

    html.Div([

        # ---------- Barra lateral ----------
        html.Div([
            html.Div([
                html.Div("UES", className="logo-marca"),
                html.Div("Estación", className="logo-texto"),
            ], className="logo"),

            html.Div(
                html.Div(html.Img(src=app.get_asset_url("logo.png")),
                         className="emblema"),
                className="emblema-caja"),

            html.Div(botones_nav("resumen"), id="nav"),

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
                    html.H1(TITULOS["resumen"], id="titulo-vista"),
                    html.Div(f"Nodo {DEVICE_ID} · Bogotá · UTC−5", className="sub"),
                ]),

                html.Div([
                    barra_qc("Válidos", "qc-val", "qc-val-b", "qc-val-n"),
                    barra_qc("Completitud", "qc-comp", "qc-comp-b", "qc-comp-n"),
                    barra_qc("Continuidad", "qc-cont", "qc-cont-b", "qc-cont-n"),
                ], className="qc-barras"),

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

            html.Div(id="contenido"),

            html.Div(id="nota-alcance", className="pie-nota"),

            html.Div([
                html.Span("Vásquez Castro, N. O. (2026) · Jitter Ingeniería SAS / "
                          "Universidad Central"),
                html.A(f"doi:{DOI}", href=f"https://doi.org/{DOI}", target="_blank"),
            ], className="creditos"),

        ], className="principal"),

    ], className="marco"),
])


# ============================================================================
#  Navegación
# ============================================================================
@app.callback(
    Output("vista", "data"),
    Output("nav", "children"),
    Output("titulo-vista", "children"),
    Input({"tipo": "nav", "vista": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _navegar(_clicks):
    """Selecciona la vista activa a partir del último botón pulsado."""
    activa = "resumen"
    if ctx.triggered_id and isinstance(ctx.triggered_id, dict):
        activa = ctx.triggered_id.get("vista", "resumen")

    return activa, botones_nav(activa), TITULOS[activa]


# ============================================================================
#  Datos
# ============================================================================
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


def _modelo(limpio):
    """Ajusta la descomposición con la especificación que el contraste avala.

    Devuelve (descomposición, resultado del contraste). El término de tendencia
    se incorpora únicamente si los tres criterios lo respaldan; en caso
    contrario se ajustaría una componente inexistente y el residual quedaría
    artificialmente reducido.
    """
    contraste = detectar_tendencia(limpio, "temp_c.prom")
    try:
        d = ajustar_ciclo_diurno(limpio, "temp_c.prom",
                                 con_tendencia=contraste["recomendada"])
    except (ValueError, np.linalg.LinAlgError):
        return None, contraste
    return d, contraste


def _ubicacion(df):
    """Posición del nodo a partir de las fijaciones satelitales disponibles.

    Se toma la mediana de las coordenadas válidas: es robusta frente a los
    errores de posicionamiento aislados, frecuentes con visibilidad parcial.
    La posición se emplea únicamente para centrar el mapa; nunca se publica.
    """
    if {"gps.lat", "gps.lon"} <= set(df.columns):
        g = df[["gps.lat", "gps.lon"]].dropna()
        if "gps.fix" in df.columns:
            g = g[df["gps.fix"].reindex(g.index).fillna(False).astype(bool)]
        if not g.empty:
            return (float(g["gps.lat"].median()),
                    float(g["gps.lon"].median()),
                    "Posición por GPS")
    return LAT_DEFECTO, LON_DEFECTO, "Posición configurada"


# ============================================================================
#  Composición de vistas
# ============================================================================
@app.callback(Output("contenido", "children"), Output("nota-alcance", "children"),
              Input("vista", "data"))
def _vista(vista):
    alcance_comun = [
        html.B("Alcance. "),
        "Lecturas sin corrección por calibración. La incertidumbre reportada "
        "recoge solo la dispersión intra-intervalo y constituye una cota "
        "inferior: la componente de calibración permanece indeterminada hasta "
        "completar la co-ubicación con una referencia trazable. No apto para "
        "uso normativo.",
    ]

    if vista == "pronostico":
        contenido = html.Div([
            kpi("Error medio", "p-mae", " °C", "p-mae-nota", "kpi-violeta"),
            kpi("Destreza", "p-destreza", "", "p-destreza-nota", "kpi-cian"),
            kpi("Cobertura", "p-cobertura", " %", "p-cobertura-nota", "kpi-verde"),
            kpi("Horizonte útil", "p-tau", " min", "p-tau-nota", "kpi-ambar"),

            panel("Pronóstico a 24 horas",
                  "Proyección del ciclo estimado con banda de predicción al 95 %",
                  [dcc.Graph(id="g-pred", config={"displayModeBar": False}),
                   html.Div(id="advertencias")], 7),

            panel("Recomendaciones operativas",
                  "Acciones derivadas del estado observado, por prioridad",
                  [html.Div(id="recomendaciones")], 5),
        ], className="rejilla")

        alcance = [
            html.B("Alcance. "),
            "El pronóstico proyecta el ciclo diurno estimado a partir del registro "
            "propio y no incorpora información meteorológica externa. Su validez "
            "está acotada por el tiempo de decorrelación del residual: más allá de "
            "ese horizonte converge al comportamiento climatológico del período. "
            "Las métricas provienen de validación sobre datos excluidos del ajuste.",
        ]
        return contenido, alcance

    # Vista de resumen
    contenido = html.Div([
        kpi("Decorrelación", "k-tau", " min", "k-tau-nota", "kpi-violeta"),
        kpi("Registros válidos", "k-n", "", "k-n-nota", "kpi-cian"),
        kpi("Varianza explicada", "k-r2", "", "k-r2-nota", "kpi-verde"),
        kpi("Dispersión residual", "k-sigma", " °C", "k-sigma-nota", "kpi-rosa"),

        panel("Descomposición de la señal",
              "Observado, componente determinista y residual con banda ±2σ",
              [dcc.Graph(id="g-descomp", config={"displayModeBar": False})], 8),

        panel("Zona de emplazamiento",
              "Sector de operación del instrumento",
              [html.Div(
                  dcc.Graph(id="g-mapa", config={"displayModeBar": False,
                                                 "scrollZoom": False}),
                  className="mapa-envoltura"),
               html.Div(id="mapa-pie", className="mapa-pie")], 4),

        panel("Persistencia temporal",
              "Autocorrelación del residual y tiempo de decorrelación",
              [dcc.Graph(id="g-acf", config={"displayModeBar": False})], 4),

        panel("Patrón hora × día",
              "Temperatura media por hora local y fecha",
              [dcc.Graph(id="g-matriz", config={"displayModeBar": False})], 4),

        panel("Contraste de tendencia",
              "Tres criterios deciden si el modelo incorpora deriva",
              [html.Div(id="criterios"), html.Div(id="veredicto")], 4),

        panel("Estabilidad del nodo",
              "Memoria libre y completitud del muestreo",
              [dcc.Graph(id="g-salud", config={"displayModeBar": False})], 5),

        panel("Distribución del residual",
              "Histograma con densidad normal de referencia",
              [dcc.Graph(id="g-hist", config={"displayModeBar": False})], 4),

        panel("Diagnóstico",
              "Indicadores del instrumento",
              [html.Table(html.Tbody(id="tabla"), className="tabla")], 3),

        panel("Eventos recientes",
              "Anomalías y sucesos del sistema",
              [html.Div(id="eventos")], 12),
    ], className="rejilla")

    return contenido, alcance_comun


# ============================================================================
#  Barras de calidad (comunes a ambas vistas)
# ============================================================================
@app.callback(
    Output("qc-val", "children"), Output("qc-val-b", "style"),
    Output("qc-val-n", "children"),
    Output("qc-comp", "children"), Output("qc-comp-b", "style"),
    Output("qc-comp-n", "children"),
    Output("qc-cont", "children"), Output("qc-cont-b", "style"),
    Output("qc-cont-n", "children"),
    Input("store", "data"),
)
def _barras(blob):
    cero = {"width": "0%", "background": "#2A3757"}
    nada = ("—", cero, "", "—", cero, "", "—", cero, "")
    if not blob:
        return nada

    _, limpio, resumen = _preparar(blob)
    if limpio is None or limpio.empty:
        return nada

    c = completitud(limpio)
    huecos = detectar_huecos(limpio)

    def estilo(p):
        color = "#2DD4A7" if p >= 99 else "#FBBF24" if p >= 90 else "#FB7185"
        return {"width": f"{min(max(p, 0), 100):.1f}%", "background": color}

    p_val = 100.0 * resumen.n_salida / resumen.n_entrada if resumen.n_entrada else 0
    p_comp = c["completitud"] * 100

    # Continuidad: fracción de intervalos no afectados por interrupciones.
    faltantes = int(huecos["intervalos_faltantes"].sum()) if not huecos.empty else 0
    esperados = max(c["esperados"], 1)
    p_cont = 100.0 * (esperados - faltantes) / esperados

    return (
        f"{p_val:.1f}%", estilo(p_val), f"{resumen.n_descartado} descartados",
        f"{p_comp:.1f}%", estilo(p_comp), f"{c['presentes']} intervalos",
        f"{p_cont:.1f}%", estilo(p_cont),
        ("sin cortes" if huecos.empty else f"{len(huecos)} cortes"),
    )


# ============================================================================
#  Vista: resumen
# ============================================================================
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

    _, limpio, _ = _preparar(blob)
    if limpio is None or limpio.empty:
        return nada

    c = completitud(limpio)
    u = incertidumbre_expandida(limpio)
    d, _ = _modelo(limpio)

    tau_txt, tau_nota = g, ""
    if d is not None:
        a = autocorrelacion(d.residual, max_rezago=min(576, len(limpio) // 2))
        tau = tiempo_decorrelacion(a).get("minutos", np.nan)
        if np.isfinite(tau):
            tau_txt = f"{tau:.0f}"
            tau_nota = [html.B(f"{tau / INTERVALO_MIN:.0f}× "),
                        f"sobre el intervalo de {INTERVALO_MIN} min"]

    r2_txt = f"{d.varianza_explicada:.3f}" if d else g
    if d is None:
        r2_nota = ""
    elif d.con_tendencia:
        r2_nota = "ciclo diurno y deriva confirmada"
    else:
        r2_nota = f"ciclo diurno, {d.n_armonicos} armónicos"

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


@app.callback(
    Output("criterios", "children"), Output("veredicto", "children"),
    Input("store", "data"),
)
def _contraste(blob):
    if not blob:
        return [], []

    _, limpio, _ = _preparar(blob)
    if limpio is None or limpio.empty:
        return [], []

    r = detectar_tendencia(limpio, "temp_c.prom")

    def criterio(cumple, titulo, detalle):
        return html.Div([
            html.Div("✓" if cumple else "✕",
                     className=f"criterio-marca {'marca-si' if cumple else 'marca-no'}"),
            html.Div([
                html.Div(titulo, className="criterio-titulo"),
                html.Div(detalle, className="criterio-detalle"),
            ], className="criterio-cuerpo"),
        ], className="criterio")

    bloques = ", ".join(f"{p:+.2f}" for p in r["bloques_pendientes"])

    filas = [
        criterio(r["supera_umbral"], "Relevancia práctica",
                 f"pendiente {r['pendiente_dia']:+.3f} °C/día"),
        criterio(r["significativa_corregida"], "Significancia corregida",
                 f"t = {r['razon_senal_ruido']:.2f} vs {r['t_critico']:.2f} · "
                 f"{r['gl_efectivos']:.0f} gl efectivos"),
        criterio(r["homogenea"], "Homogeneidad entre bloques",
                 f"CV = {r['cv_bloques']:.2f} · [{bloques}]"),
    ]

    if r["recomendada"]:
        veredicto = html.Div([
            html.B("Deriva confirmada. "),
            f"El modelo incorpora una pendiente de {r['pendiente_dia']:+.3f} °C/día. "
            f"La dispersión residual desciende de {r['sigma_sin']:.3f} a "
            f"{r['sigma_con']:.3f} °C al modelarla.",
        ], className="veredicto veredicto-si")
    else:
        veredicto = html.Div([
            html.B("Sin deriva sistemática. "),
            f"{r['motivo'].capitalize()}. ",
            f"Con ρ = {r['rho_lag1']:.3f}, las {r['n_observaciones']} observaciones "
            f"equivalen a {r['n_efectivo']:.0f} independientes: la significancia "
            "nominal resultaría engañosa sin esta corrección.",
        ], className="veredicto veredicto-no")

    return filas, veredicto


@app.callback(
    Output("g-descomp", "figure"), Output("g-mapa", "figure"),
    Output("mapa-pie", "children"),
    Output("g-acf", "figure"), Output("g-matriz", "figure"),
    Output("g-salud", "figure"), Output("g-hist", "figure"),
    Output("eventos", "children"), Output("tabla", "children"),
    Input("store", "data"),
)
def _figuras(blob):
    v = F.fig_vacia()
    mapa_ini = F.fig_mapa(LAT_DEFECTO, LON_DEFECTO, "Nodo")
    if not blob:
        return v, mapa_ini, [], v, v, v, v, [], []

    df, limpio, _ = _preparar(blob)
    if limpio is None or limpio.empty:
        return v, mapa_ini, [], v, v, v, v, [], []

    d, _ = _modelo(limpio)

    if d is not None:
        a = autocorrelacion(d.residual, max_rezago=min(576, len(limpio) // 2))
        f_desc = F.fig_descomposicion(d)
        f_acf = F.fig_acf(a, tiempo_decorrelacion(a), INTERVALO_MIN)
        f_hist = F.fig_histograma_residual(d)
    else:
        f_desc = f_acf = f_hist = F.fig_vacia("Serie insuficiente")

    lat, lon, fuente = _ubicacion(df)

    # No se publican coordenadas: el emplazamiento se describe de forma
    # cualitativa para no exponer la posición exacta del instrumento.
    pie_mapa = [
        html.Span([html.B("Emplazamiento "), "Bogotá D.C."]),
        html.Span([html.B("Altitud "), "≈ 2 600 m s. n. m."]),
        html.Span(fuente),
    ]

    diag = diagnostico_estabilidad(df)
    huecos = detectar_huecos(limpio)

    return (
        f_desc,
        F.fig_mapa(lat, lon, "Zona de operación"),
        pie_mapa,
        f_acf,
        F.fig_matriz(matriz_hora_dia(limpio, "temp_c.prom")),
        F.fig_salud(df),
        f_hist,
        _eventos(d, df, huecos),
        _tabla(diag, huecos),
    )


# ============================================================================
#  Vista: pronóstico
# ============================================================================
@app.callback(
    Output("p-mae", "children"), Output("p-mae-nota", "children"),
    Output("p-destreza", "children"), Output("p-destreza-nota", "children"),
    Output("p-cobertura", "children"), Output("p-cobertura-nota", "children"),
    Output("p-tau", "children"), Output("p-tau-nota", "children"),
    Output("g-pred", "figure"), Output("advertencias", "children"),
    Input("store", "data"),
)
def _pronostico(blob):
    g = "—"
    nada = (g, "", g, "", g, "", g, "", F.fig_vacia(), [])
    if not blob:
        return nada

    _, limpio, _ = _preparar(blob)
    if limpio is None or limpio.empty:
        return nada

    d, _ = _modelo(limpio)
    pred = predecir(limpio, horas=HORAS_PRONOSTICO, intervalo_min=INTERVALO_MIN)

    if d is None or pred is None:
        return (g, "", g, "", g, "", g, "",
                F.fig_vacia("Serie insuficiente para pronosticar"), [])

    v = pred.validacion
    if v is None:
        mae_txt = destreza_txt = cob_txt = g
        mae_nota = destreza_nota = cob_nota = "validación no disponible"
    else:
        mae_txt = f"{v.mae:.2f}"
        mae_nota = f"fuera de muestra · n = {v.n} · sesgo {v.sesgo:+.2f} °C"

        destreza_txt = f"{v.destreza:+.2f}"
        if v.destreza > 0.5:
            juicio = "mejora sustancial sobre la climatología"
        elif v.destreza > 0:
            juicio = "mejora marginal sobre la climatología"
        else:
            juicio = "no supera a predecir la media del período"
        destreza_nota = [html.B(f"{v.mae_climatologia:.2f} °C "), juicio]

        cob_txt = f"{v.cobertura * 100:.0f}"
        desv = v.cobertura - v.cobertura_nominal
        if abs(desv) < 0.05:
            cob_nota = f"acorde al {v.cobertura_nominal:.0%} nominal"
        elif desv < 0:
            cob_nota = [html.B("Subestima "),
                        f"la incertidumbre ({v.cobertura_nominal:.0%} nominal)"]
        else:
            cob_nota = [html.B("Sobreestima "),
                        f"la incertidumbre ({v.cobertura_nominal:.0%} nominal)"]

    if np.isfinite(pred.tau_min):
        tau_txt = f"{pred.tau_min:.0f}"
        tau_nota = ["más allá converge al ", html.B("ciclo climatológico")]
    else:
        tau_txt, tau_nota = g, ""

    avisos = [
        html.Div([html.Span("!", className="advertencia-icono"), html.Span(a)],
                 className="advertencia")
        for a in pred.advertencias
    ]

    return (mae_txt, mae_nota, destreza_txt, destreza_nota,
            cob_txt, cob_nota, tau_txt, tau_nota,
            F.fig_prediccion(d, pred), avisos)


@app.callback(Output("recomendaciones", "children"), Input("store", "data"))
def _recomendaciones(blob):
    if not blob:
        return []

    df, limpio, resumen = _preparar(blob)
    if limpio is None or limpio.empty:
        return []

    _, contraste = _modelo(limpio)
    pred = predecir(limpio, horas=HORAS_PRONOSTICO, intervalo_min=INTERVALO_MIN)
    diag = diagnostico_estabilidad(df)

    recs = prescribir(df, limpio, diag, resumen, pred, contraste,
                      intervalo_min=INTERVALO_MIN)

    if not recs:
        return html.Div("Sin acciones pendientes", className="sin-eventos")

    color_magnitud = {"alta": "malo", "media": "alerta", "baja": "ok"}

    return [
        html.Div([
            html.Div(className=f"rec-prioridad pri-{r.prioridad}"),
            html.Div([
                html.Div([
                    html.Div(r.titulo, className="rec-titulo"),
                    html.Div(r.magnitud,
                             className=f"rec-magnitud {color_magnitud[r.prioridad]}"),
                ], className="rec-encabezado"),
                html.Div(r.detalle, className="rec-detalle"),
                html.Div(r.categoria, className=f"rec-categoria cat-{r.categoria}"),
            ], className="rec-cuerpo"),
        ], className="recomendacion")
        for r in recs
    ]


# ============================================================================
#  Auxiliares de composición
# ============================================================================
def _eventos(d, df, huecos, maximo: int = 8):
    """Registro de sucesos: anomalías agrupadas, reinicios e interrupciones."""
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
    # El recargador de Werkzeug falla en Windows al reservar memoria compartida
    # cuando ya existe una instancia activa.
    app.run(debug=True, use_reloader=False,
            port=int(os.environ.get("PORT", 8050)))
