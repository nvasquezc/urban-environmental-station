"""Figuras de publicación para las campañas de caracterización.

Implementa las seis figuras obligatorias de docs/02-protocolo-calibracion.md §10.

Criterios de diseño:

1. **Paleta Okabe-Ito.** Cromáticamente distinguible bajo las tres formas de
   dicromatismo. Ninguna figura codifica información únicamente por color:
   siempre hay un segundo canal (posición, forma de marcador o etiqueta).

2. **La incertidumbre se representa, no se oculta.** Las bandas de dispersión,
   los intervalos de predicción y los límites de concordancia son parte de la
   figura, no un añadido opcional.

3. **Toda figura declara el estado de calibración.** Una serie sin corrección
   aplicada debe identificarse como tal en la propia figura, no solo en el pie.

Las funciones devuelven objetos `plotly.graph_objects.Figure` sin escribir a
disco. La exportación es responsabilidad de `guardar_figura`, que fija las
dimensiones y la resolución exigidas para publicación.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy import stats

# --- Paleta Okabe-Ito -------------------------------------------------------
# Okabe & Ito (2008), "Color Universal Design".
OKABE_ITO = {
    "negro": "#000000",
    "naranja": "#E69F00",
    "celeste": "#56B4E9",
    "verde": "#009E73",
    "amarillo": "#F0E442",
    "azul": "#0072B2",
    "bermellon": "#D55E00",
    "rosa": "#CC79A7",
    "gris": "#999999",
}

SECUENCIA = [
    OKABE_ITO["azul"],
    OKABE_ITO["bermellon"],
    OKABE_ITO["verde"],
    OKABE_ITO["naranja"],
    OKABE_ITO["rosa"],
    OKABE_ITO["celeste"],
]

MARCADORES = ["circle", "square", "diamond", "triangle-up", "cross", "x"]

TZ_LOCAL = "America/Bogota"

# Dimensiones para publicación: ancho de columna simple y doble en revistas
# de formato A4, a 300 ppp.
ANCHO_SIMPLE_PX = 1050   # 89 mm
ANCHO_DOBLE_PX = 2150    # 183 mm
ESCALA_EXPORT = 3

_PLANTILLA = {
    "template": "plotly_white",
    "font": {"family": "Arial, Helvetica, sans-serif", "size": 13, "color": "#111111"},
    "margin": {"l": 70, "r": 30, "t": 60, "b": 60},
    "hovermode": "x unified",
}


def _aplicar_estilo(fig: go.Figure, titulo: str, alto: int = 450) -> go.Figure:
    fig.update_layout(title={"text": titulo, "x": 0.01, "xanchor": "left"},
                      height=alto, **_PLANTILLA)
    fig.update_xaxes(showgrid=True, gridcolor="#E5E5E5", zeroline=False,
                     ticks="outside", linecolor="#333333")
    fig.update_yaxes(showgrid=True, gridcolor="#E5E5E5", zeroline=False,
                     ticks="outside", linecolor="#333333")
    return fig


def _nota_calibracion(fig: go.Figure, cal: str) -> go.Figure:
    """Estampa el estado de calibración sobre la figura.

    Una serie sin corrección no debe poder confundirse con una corregida, ni
    siquiera cuando la figura circula sin su pie.
    """
    texto = "SIN CALIBRAR" if cal == "sin-calibrar" else f"calibración: {cal}"
    color = OKABE_ITO["bermellon"] if cal == "sin-calibrar" else OKABE_ITO["gris"]
    fig.add_annotation(
        text=texto, xref="paper", yref="paper", x=1.0, y=1.06,
        xanchor="right", showarrow=False,
        font={"size": 11, "color": color},
    )
    return fig


def guardar_figura(
    fig: go.Figure,
    ruta: str | Path,
    ancho_px: int = ANCHO_SIMPLE_PX,
    escala: int = ESCALA_EXPORT,
) -> Path:
    """Exporta la figura a PNG con resolución de publicación.

    Requiere `kaleido`, declarado en las dependencias del proyecto.
    """
    p = Path(ruta)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.write_image(str(p), width=ancho_px, scale=escala)
    return p


# --- Figura 1: series temporales -------------------------------------------
def fig_serie_temporal(
    df: pd.DataFrame,
    variable: str = "temp_c",
    unidad: str = "°C",
    etiqueta: str = "Temperatura",
    col_tiempo: str = "t_fin",
    cal: str = "sin-calibrar",
    mostrar_banda: bool = True,
) -> go.Figure:
    """Serie temporal con banda de dispersión intra-intervalo.

    La banda min–max comunica la variabilidad dentro de cada intervalo de
    agregación, información que una línea de promedios por sí sola destruye.
    """
    d = df.copy()
    t = d[col_tiempo].dt.tz_convert(TZ_LOCAL) if d[col_tiempo].dt.tz is not None else d[col_tiempo]

    c_prom = f"{variable}.prom" if f"{variable}.prom" in d.columns else f"{variable}_prom"
    c_min = f"{variable}.min" if f"{variable}.min" in d.columns else f"{variable}_min"
    c_max = f"{variable}.max" if f"{variable}.max" in d.columns else f"{variable}_max"

    fig = go.Figure()

    if mostrar_banda and c_min in d.columns and c_max in d.columns:
        fig.add_trace(go.Scatter(
            x=t, y=d[c_max], mode="lines", line={"width": 0},
            showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=t, y=d[c_min], mode="lines", line={"width": 0},
            fill="tonexty", fillcolor="rgba(0,114,178,0.15)",
            name="rango intra-intervalo", hoverinfo="skip",
        ))

    fig.add_trace(go.Scatter(
        x=t, y=d[c_prom], mode="lines",
        line={"color": OKABE_ITO["azul"], "width": 1.8},
        name=f"{etiqueta} (promedio)",
    ))

    _aplicar_estilo(fig, f"{etiqueta} — serie temporal")
    fig.update_xaxes(title_text="Hora local (America/Bogota)")
    fig.update_yaxes(title_text=f"{etiqueta} ({unidad})")
    return _nota_calibracion(fig, cal)


# --- Figura 2: dispersión con ajuste ---------------------------------------
def fig_dispersion_ajuste(
    df: pd.DataFrame,
    col_x: str,
    col_y: str,
    etiqueta_x: str = "Estación (cruda)",
    etiqueta_y: str = "Referencia",
    unidad: str = "°C",
) -> go.Figure:
    """Dispersión con recta ajustada, intervalo de predicción y línea 1:1.

    La línea de identidad es imprescindible: sin ella, una recta ajustada de
    pendiente 0.8 y un ajuste perfecto se ven igualmente convincentes.
    """
    d = df[[col_x, col_y]].dropna()
    if len(d) < 3:
        raise ValueError("Se requieren al menos 3 pares para ajustar.")

    x = d[col_x].to_numpy(dtype=float)
    y = d[col_y].to_numpy(dtype=float)

    res = stats.linregress(x, y)
    n = len(x)
    gl = n - 2
    xg = np.linspace(x.min(), x.max(), 200)
    yg = res.slope * xg + res.intercept

    # Intervalo de predicción al 95 %
    resid = y - (res.slope * x + res.intercept)
    s = np.sqrt(np.sum(resid**2) / gl)
    sxx = np.sum((x - x.mean()) ** 2)
    t_crit = stats.t.ppf(0.975, gl)
    se_pred = s * np.sqrt(1 + 1 / n + (xg - x.mean()) ** 2 / sxx)
    banda = t_crit * se_pred

    lo = min(x.min(), y.min())
    hi = max(x.max(), y.max())

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[lo, hi], y=[lo, hi], mode="lines", name="identidad (1:1)",
        line={"color": OKABE_ITO["gris"], "dash": "dot", "width": 1.5},
    ))
    fig.add_trace(go.Scatter(
        x=np.concatenate([xg, xg[::-1]]),
        y=np.concatenate([yg + banda, (yg - banda)[::-1]]),
        fill="toself", fillcolor="rgba(213,94,0,0.12)",
        line={"width": 0}, name="IP 95 %", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="markers", name="observaciones",
        marker={"color": OKABE_ITO["azul"], "size": 5, "opacity": 0.65,
                "symbol": "circle"},
    ))
    fig.add_trace(go.Scatter(
        x=xg, y=yg, mode="lines", name="ajuste OLS",
        line={"color": OKABE_ITO["bermellon"], "width": 2},
    ))

    signo = "+" if res.intercept >= 0 else "−"
    fig.add_annotation(
        text=(f"y = {res.slope:.4f}·x {signo} {abs(res.intercept):.4f}<br>"
              f"R² = {res.rvalue**2:.4f}   n = {n}<br>"
              f"EE pendiente = {res.stderr:.4f}"),
        xref="paper", yref="paper", x=0.03, y=0.97,
        xanchor="left", yanchor="top", showarrow=False, align="left",
        bgcolor="rgba(255,255,255,0.85)", bordercolor="#CCCCCC", borderwidth=1,
        font={"size": 11, "family": "Courier New, monospace"},
    )

    _aplicar_estilo(fig, "Ajuste estación vs. referencia", alto=520)
    fig.update_xaxes(title_text=f"{etiqueta_x} ({unidad})")
    fig.update_yaxes(title_text=f"{etiqueta_y} ({unidad})",
                     scaleanchor="x", scaleratio=1)
    return fig


# --- Figura 3: Bland-Altman ------------------------------------------------
def fig_bland_altman(
    df: pd.DataFrame,
    col_estacion: str,
    col_referencia: str,
    unidad: str = "°C",
) -> go.Figure:
    """Gráfico de concordancia de Bland-Altman.

    Representa la diferencia frente a la media de ambos métodos. A diferencia
    de la regresión, revela si el sesgo depende de la magnitud medida, que es
    el modo de falla característico de los sensores de bajo costo.

    Los límites de concordancia son sesgo ± 1.96·sd de las diferencias: el
    intervalo donde se espera el 95 % de las discrepancias futuras.
    """
    d = df[[col_estacion, col_referencia]].dropna()
    if len(d) < 3:
        raise ValueError("Se requieren al menos 3 pares.")

    a = d[col_estacion].to_numpy(dtype=float)
    b = d[col_referencia].to_numpy(dtype=float)
    media = (a + b) / 2.0
    dif = a - b

    sesgo = float(dif.mean())
    sd = float(dif.std(ddof=1))
    lca_sup, lca_inf = sesgo + 1.96 * sd, sesgo - 1.96 * sd

    # Incertidumbre de los propios límites (Bland & Altman, 1999)
    ee_lca = sd * np.sqrt(3.0 / len(d))
    t_crit = stats.t.ppf(0.975, len(d) - 1)

    fig = go.Figure()
    for y, color, texto, dash in [
        (lca_sup, OKABE_ITO["bermellon"], f"LCA sup. {lca_sup:+.3f}", "dash"),
        (sesgo, OKABE_ITO["verde"], f"sesgo {sesgo:+.3f}", "solid"),
        (lca_inf, OKABE_ITO["bermellon"], f"LCA inf. {lca_inf:+.3f}", "dash"),
    ]:
        fig.add_hline(y=y, line={"color": color, "dash": dash, "width": 1.6},
                      annotation_text=texto, annotation_position="right",
                      annotation_font_size=10)

    # Banda de incertidumbre de los límites de concordancia
    for y in (lca_sup, lca_inf):
        fig.add_hrect(
            y0=y - t_crit * ee_lca, y1=y + t_crit * ee_lca,
            fillcolor="rgba(213,94,0,0.10)", line_width=0, layer="below",
        )

    fig.add_trace(go.Scatter(
        x=media, y=dif, mode="markers", name="pares",
        marker={"color": OKABE_ITO["azul"], "size": 5, "opacity": 0.65},
    ))

    # Tendencia del sesgo con la magnitud: si es significativa, el sesgo es
    # proporcional y una corrección de solo intercepto sería insuficiente.
    if len(d) >= 10:
        r = stats.linregress(media, dif)
        fig.add_trace(go.Scatter(
            x=np.sort(media), y=r.slope * np.sort(media) + r.intercept,
            mode="lines", name=f"tendencia (p={r.pvalue:.3f})",
            line={"color": OKABE_ITO["rosa"], "width": 1.4, "dash": "dot"},
        ))

    _aplicar_estilo(fig, "Concordancia (Bland-Altman)", alto=480)
    fig.update_xaxes(title_text=f"Media de ambos métodos ({unidad})")
    fig.update_yaxes(title_text=f"Diferencia estación − referencia ({unidad})")
    return fig


# --- Figura 4: residual contra covariable ----------------------------------
def fig_residual_vs_covariable(
    df: pd.DataFrame,
    col_residual: str,
    col_covariable: str,
    etiqueta_covariable: str = "Humedad relativa (%)",
    unidad_residual: str = "°C",
    ventana: int = 20,
) -> go.Figure:
    """Residual frente a una covariable, con tendencia suavizada.

    Un residual que depende de la humedad o de la hora del día indica que el
    modelo base es insuficiente y justifica el modelo extendido de §6.2.
    """
    d = df[[col_residual, col_covariable]].dropna().sort_values(col_covariable)
    x = d[col_covariable].to_numpy(dtype=float)
    y = d[col_residual].to_numpy(dtype=float)

    fig = go.Figure()
    fig.add_hline(y=0, line={"color": OKABE_ITO["gris"], "width": 1.2})
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="markers", name="residual",
        marker={"color": OKABE_ITO["azul"], "size": 4, "opacity": 0.5},
    ))

    if len(d) >= ventana * 2:
        suave = pd.Series(y).rolling(ventana, center=True, min_periods=ventana // 2).mean()
        fig.add_trace(go.Scatter(
            x=x, y=suave, mode="lines", name=f"media móvil (n={ventana})",
            line={"color": OKABE_ITO["bermellon"], "width": 2},
        ))

    _aplicar_estilo(fig, f"Residual vs. {etiqueta_covariable}", alto=420)
    fig.update_xaxes(title_text=etiqueta_covariable)
    fig.update_yaxes(title_text=f"Residual ({unidad_residual})")
    return fig


# --- Figura 5: evolución de coeficientes -----------------------------------
def fig_evolucion_coeficientes(
    df: pd.DataFrame,
    col_bloque: str = "bloque",
    col_coef: str = "pendiente",
    col_ic_inf: str = "ic_inf",
    col_ic_sup: str = "ic_sup",
    col_unidad: str = "unidad",
    etiqueta: str = "Pendiente",
    referencia: float | None = 1.0,
) -> go.Figure:
    """Evolución de un coeficiente de calibración por bloque temporal (§7.1).

    Una tendencia significativa sobre los bloques constituye evidencia de
    deriva. Las barras de error son indispensables: sin ellas, el ruido de
    estimación es indistinguible de una deriva real.
    """
    fig = go.Figure()

    unidades = df[col_unidad].unique() if col_unidad in df.columns else [None]
    for i, u in enumerate(unidades):
        g = df if u is None else df[df[col_unidad] == u]
        err_sup = g[col_ic_sup] - g[col_coef] if col_ic_sup in g.columns else None
        err_inf = g[col_coef] - g[col_ic_inf] if col_ic_inf in g.columns else None

        fig.add_trace(go.Scatter(
            x=g[col_bloque], y=g[col_coef], mode="lines+markers",
            name=str(u) if u is not None else etiqueta,
            line={"color": SECUENCIA[i % len(SECUENCIA)], "width": 1.8},
            marker={"symbol": MARCADORES[i % len(MARCADORES)], "size": 9},
            error_y=(
                {"type": "data", "symmetric": False,
                 "array": err_sup, "arrayminus": err_inf,
                 "thickness": 1.4, "width": 5}
                if err_sup is not None else None
            ),
        ))

    if referencia is not None:
        fig.add_hline(
            y=referencia, line={"color": OKABE_ITO["gris"], "dash": "dot", "width": 1.4},
            annotation_text="sin deriva", annotation_position="right",
            annotation_font_size=10,
        )

    _aplicar_estilo(fig, f"Evolución de {etiqueta.lower()} por bloque", alto=450)
    fig.update_xaxes(title_text="Bloque temporal")
    fig.update_yaxes(title_text=etiqueta)
    return fig


# --- Figura 6: desempeño estratificado -------------------------------------
def fig_boxplot_estratificado(
    df: pd.DataFrame,
    col_valor: str,
    col_estrato: str = "franja",
    etiqueta_valor: str = "Error absoluto (°C)",
    etiqueta_estrato: str = "Franja horaria",
    umbral: float | None = None,
) -> go.Figure:
    """Distribución de una métrica desagregada por estrato (§6.3).

    Un desempeño global aceptable puede ocultar falla sistemática en una
    franja concreta. Esta figura es la que impide que ese caso pase inadvertido.
    """
    fig = go.Figure()

    estratos = list(df[col_estrato].dropna().unique())
    for i, e in enumerate(estratos):
        v = df.loc[df[col_estrato] == e, col_valor].dropna()
        fig.add_trace(go.Box(
            y=v, name=str(e), boxpoints="outliers",
            marker={"color": SECUENCIA[i % len(SECUENCIA)], "size": 3},
            line={"width": 1.5},
            hovertext=f"n = {len(v)}",
        ))

    if umbral is not None:
        fig.add_hline(
            y=umbral, line={"color": OKABE_ITO["bermellon"], "dash": "dash", "width": 1.6},
            annotation_text=f"criterio de aceptación ({umbral})",
            annotation_position="right", annotation_font_size=10,
        )

    _aplicar_estilo(fig, f"{etiqueta_valor} por {etiqueta_estrato.lower()}", alto=450)
    fig.update_xaxes(title_text=etiqueta_estrato)
    fig.update_yaxes(title_text=etiqueta_valor)
    fig.update_layout(showlegend=False, hovermode="closest")
    return fig


# --- Figura auxiliar: diagnóstico de estabilidad ---------------------------
def fig_diagnostico_nodo(df: pd.DataFrame, col_tiempo: str = "t_fin") -> go.Figure:
    """Panel de salud del nodo: memoria, muestras y señal.

    No pertenece al conjunto obligatorio del protocolo, pero es la figura que
    se consulta primero cuando una serie presenta anomalías: distingue un
    fenómeno ambiental de un fallo del instrumento.
    """
    from plotly.subplots import make_subplots

    d = df.copy()
    t = d[col_tiempo].dt.tz_convert(TZ_LOCAL) if d[col_tiempo].dt.tz is not None else d[col_tiempo]

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07,
        subplot_titles=("Memoria libre (bytes)", "Muestras por intervalo", "RSSI (dBm)"),
    )

    if "diag.heap" in d.columns:
        fig.add_trace(go.Scatter(x=t, y=d["diag.heap"], mode="lines",
                                 line={"color": OKABE_ITO["azul"], "width": 1.4},
                                 name="heap"), row=1, col=1)
    if "temp_c.n" in d.columns:
        fig.add_trace(go.Scatter(x=t, y=d["temp_c.n"], mode="lines",
                                 line={"color": OKABE_ITO["verde"], "width": 1.4},
                                 name="muestras"), row=2, col=1)
        fig.add_hline(y=120, line={"color": OKABE_ITO["bermellon"], "dash": "dash",
                                   "width": 1.2}, row=2, col=1)
    if "diag.rssi" in d.columns:
        fig.add_trace(go.Scatter(x=t, y=d["diag.rssi"], mode="lines",
                                 line={"color": OKABE_ITO["naranja"], "width": 1.4},
                                 name="rssi"), row=3, col=1)

    # Marcas verticales en cada reinicio
    if "boot" in d.columns:
        cambios = d.index[d["boot"] != d["boot"].shift(1)][1:]
        for i in cambios:
            fig.add_vline(x=t.iloc[i], line={"color": OKABE_ITO["gris"],
                                             "dash": "dot", "width": 1})

    fig.update_layout(title={"text": "Diagnóstico del nodo", "x": 0.01},
                      height=720, showlegend=False, **_PLANTILLA)
    fig.update_xaxes(title_text="Hora local", row=3, col=1)
    return fig
