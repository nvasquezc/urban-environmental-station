"""Figuras del tablero, adaptadas a fondo oscuro.

Las áreas se rellenan con degradado simulado mediante capas de transparencia
decreciente: Plotly no admite degradados nativos en rellenos, de modo que el
efecto se construye superponiendo trazas con opacidad graduada.

Todas las operaciones numéricas se realizan sobre arrays de numpy y no sobre
Series: la alineación automática por índice de pandas introduce valores nulos
cuando los operandos provienen de objetos con índices distintos.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from uestation.decompose import Descomposicion

TZ = "America/Bogota"

# Paleta de la consola
VIOLETA = "#7C6CF6"
CIAN = "#22C7E8"
VERDE = "#2DD4A7"
ROSA = "#F472B6"
AMBAR = "#FBBF24"
ROJO = "#FB7185"

TEXTO = "#EAF0FB"
TEXTO_MED = "#93A3C4"
TEXTO_BAJO = "#64749A"
REJILLA = "rgba(42,55,87,0.55)"

BASE = {
    "template": "plotly_dark",
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "font": {"family": "Inter, Segoe UI, Arial, sans-serif",
             "size": 11, "color": TEXTO_MED},
    "margin": {"l": 48, "r": 18, "t": 18, "b": 38},
    "hoverlabel": {"bgcolor": "#1A2542", "bordercolor": "#2A3757",
                   "font": {"color": TEXTO, "size": 11}},
}


def _sin_margen(alto: int, **extra) -> dict:
    """Combina la configuración base con sobrescrituras puntuales."""
    cfg = {k: v for k, v in BASE.items() if k != "margin"}
    cfg["height"] = alto
    cfg.update(extra)
    return cfg


def _ejes(fig: go.Figure) -> go.Figure:
    fig.update_xaxes(showgrid=False, zeroline=False, showline=False,
                     color=TEXTO_BAJO)
    fig.update_yaxes(showgrid=True, gridcolor=REJILLA, gridwidth=1,
                     zeroline=False, showline=False, color=TEXTO_BAJO)
    return fig


def _degradado(fig, x, y_sup, y_inf, color_rgb, capas=5, alpha_max=0.30, **kw):
    """Simula un relleno degradado mediante capas de opacidad decreciente."""
    r, g, b = color_rgb
    xv = np.asarray(x)
    sup = np.asarray(y_sup, dtype=float)
    inf = np.asarray(y_inf, dtype=float)

    for i in range(capas):
        f = (i + 1) / capas
        y_mid = inf + (sup - inf) * f
        alpha = alpha_max * (1 - i / capas) ** 1.4
        fig.add_trace(go.Scatter(
            x=xv, y=inf, mode="lines", line={"width": 0},
            showlegend=False, hoverinfo="skip"), **kw)
        fig.add_trace(go.Scatter(
            x=xv, y=y_mid, mode="lines", line={"width": 0},
            fill="tonexty", fillcolor=f"rgba({r},{g},{b},{alpha:.3f})",
            showlegend=False, hoverinfo="skip"), **kw)
    return fig


def fig_vacia(mensaje: str = "Sin datos") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=mensaje, xref="paper", yref="paper", x=0.5, y=0.5,
                       showarrow=False, font={"size": 12, "color": TEXTO_BAJO})
    fig.update_layout(xaxis={"visible": False}, yaxis={"visible": False},
                      margin={"l": 10, "r": 10, "t": 10, "b": 10},
                      **_sin_margen(220))
    return fig


# --- Descomposición ---------------------------------------------------------
def fig_descomposicion(d: Descomposicion, unidad: str = "°C") -> go.Figure:
    """Observado, ciclo diurno ajustado y residual con banda de tolerancia."""
    t = d.tiempo.dt.tz_convert(TZ).to_numpy()
    obs = d.observado.to_numpy(dtype=float)
    ciclo = d.ciclo.to_numpy(dtype=float)
    resid = d.residual.to_numpy(dtype=float)
    b_sup = d.banda_superior.to_numpy(dtype=float)
    b_inf = d.banda_inferior.to_numpy(dtype=float)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.06, row_heights=[0.68, 0.32])

    # Banda ±2σ alrededor del ciclo
    _degradado(fig, t, b_sup, b_inf, (45, 212, 167),
               capas=4, alpha_max=0.16, row=1, col=1)

    # Relleno bajo la curva observada
    piso = np.full(len(t), obs.min() - 0.6)
    _degradado(fig, t, obs, piso, (124, 108, 246),
               capas=6, alpha_max=0.26, row=1, col=1)

    fig.add_trace(go.Scatter(
        x=t, y=ciclo, mode="lines", name="Ciclo diurno",
        line={"color": VERDE, "width": 2, "dash": "dot"},
        hovertemplate="%{y:.2f} " + unidad + "<extra>ciclo</extra>"), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=t, y=obs, mode="lines", name="Observado",
        line={"color": VIOLETA, "width": 2.2, "shape": "spline", "smoothing": 0.4},
        hovertemplate="%{y:.2f} " + unidad + "<extra>observado</extra>"), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=t, y=resid, mode="lines", name="Residual",
        line={"color": CIAN, "width": 1.3},
        fill="tozeroy", fillcolor="rgba(34,199,232,0.13)",
        hovertemplate="%{y:+.3f} " + unidad + "<extra>residual</extra>"), row=2, col=1)

    anom = d.anomalias(k=2.0).to_numpy()
    if anom.any():
        fig.add_trace(go.Scatter(
            x=t[anom], y=resid[anom], mode="markers",
            name=f"Anomalías ({int(anom.sum())})",
            marker={"color": AMBAR, "size": 6,
                    "line": {"color": "#0F1729", "width": 1}},
            hovertemplate="%{y:+.3f} " + unidad + "<extra>anomalía</extra>"),
            row=2, col=1)

    for s in (2, -2):
        fig.add_hline(y=s * d.sigma_residual, row=2, col=1,
                      line={"color": "rgba(251,191,36,0.35)",
                            "dash": "dash", "width": 1})

    fig.update_layout(
        showlegend=True,
        legend={"orientation": "h", "y": 1.13, "x": 0,
                "bgcolor": "rgba(0,0,0,0)", "font": {"size": 10}},
        margin={"l": 48, "r": 18, "t": 34, "b": 34},
        **_sin_margen(340))
    _ejes(fig)
    fig.update_yaxes(title_text=unidad, title_font_size=10, row=1, col=1)
    fig.update_yaxes(title_text="resid.", title_font_size=10, row=2, col=1)
    return fig


# --- Autocorrelación --------------------------------------------------------
def fig_acf(acf: pd.DataFrame, td: dict, intervalo_min: int = 5) -> go.Figure:
    if acf.empty:
        return fig_vacia("Serie insuficiente")

    x = acf["rezago"].to_numpy(dtype=float) * intervalo_min
    y = acf["acf"].to_numpy(dtype=float)
    banda = float(acf["banda"].iloc[0])

    fig = go.Figure()
    fig.add_hrect(y0=-banda, y1=banda, fillcolor="rgba(100,116,154,0.16)",
                  line_width=0, layer="below")
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="lines", name="ACF",
        line={"color": CIAN, "width": 2.2},
        fill="tozeroy", fillcolor="rgba(34,199,232,0.14)",
        hovertemplate="%{x:.0f} min · %{y:.3f}<extra></extra>"))
    fig.add_hline(y=1 / np.e, line={"color": "rgba(251,191,36,0.5)",
                                    "dash": "dot", "width": 1.2})

    tau = td.get("minutos", np.nan)
    if np.isfinite(tau):
        fig.add_vline(x=tau, line={"color": AMBAR, "dash": "dash", "width": 1.6},
                      annotation_text=f"τ = {tau:.0f} min",
                      annotation_position="top right",
                      annotation_font={"size": 11, "color": AMBAR})

    fig.update_layout(showlegend=False, margin=BASE["margin"], **_sin_margen(232))
    _ejes(fig)
    fig.update_xaxes(title_text="rezago (min)", title_font_size=10)
    fig.update_yaxes(range=[-0.25, 1.05])
    return fig


# --- Donut de calidad -------------------------------------------------------
def fig_donut_calidad(resumen) -> go.Figure:
    """Proporción de registros aceptados, con el porcentaje al centro."""
    ok = resumen.n_salida
    desc = max(resumen.n_descartado, 0)
    pct = 100.0 * ok / resumen.n_entrada if resumen.n_entrada else 0.0

    fig = go.Figure(go.Pie(
        values=[ok, desc],
        labels=["Aceptados", "Descartados"],
        hole=0.72,
        marker={"colors": [VERDE, "rgba(251,113,133,0.55)"],
                "line": {"color": "#1A2542", "width": 2}},
        textinfo="none",
        hovertemplate="%{label}: %{value}<extra></extra>",
        sort=False,
    ))
    fig.add_annotation(text=f"<b>{pct:.0f}%</b>", x=0.5, y=0.54,
                       showarrow=False, font={"size": 26, "color": TEXTO})
    fig.add_annotation(text="válidos", x=0.5, y=0.38,
                       showarrow=False, font={"size": 10, "color": TEXTO_BAJO})

    fig.update_layout(
        showlegend=True,
        legend={"orientation": "h", "y": -0.06, "x": 0.5,
                "xanchor": "center", "font": {"size": 10}},
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        **_sin_margen(214))
    return fig


# --- Matriz hora × día ------------------------------------------------------
def fig_matriz(m: pd.DataFrame, unidad: str = "°C") -> go.Figure:
    if m.empty:
        return fig_vacia("Sin cobertura")

    fig = go.Figure(go.Heatmap(
        z=m.to_numpy(), x=[str(c) for c in m.columns], y=m.index,
        colorscale=[[0, "#1A2542"], [0.3, "#3B4B9E"], [0.6, VIOLETA],
                    [0.85, ROSA], [1, AMBAR]],
        colorbar={"thickness": 9, "len": 0.85, "tickfont": {"size": 9},
                  "outlinewidth": 0},
        hovertemplate="%{x} · %{y}:00 · %{z:.2f} " + unidad + "<extra></extra>",
    ))
    fig.update_layout(margin=BASE["margin"], **_sin_margen(232))
    fig.update_xaxes(showgrid=False, color=TEXTO_BAJO, tickfont_size=9)
    fig.update_yaxes(showgrid=False, color=TEXTO_BAJO, dtick=6, tickfont_size=9)
    return fig


# --- Histograma del residual ------------------------------------------------
def fig_histograma_residual(d: Descomposicion, unidad: str = "°C") -> go.Figure:
    r = d.residual.dropna().to_numpy(dtype=float)
    if r.size < 20:
        return fig_vacia("Serie insuficiente")

    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=r, nbinsx=34, histnorm="probability density", name="residual",
        marker={"color": "rgba(124,108,246,0.62)",
                "line": {"color": VIOLETA, "width": 1}},
        hovertemplate="%{x:.3f} · %{y:.2f}<extra></extra>"))

    xg = np.linspace(r.min(), r.max(), 240)
    dens = np.exp(-0.5 * (xg / d.sigma_residual) ** 2) / (
        d.sigma_residual * np.sqrt(2 * np.pi))
    fig.add_trace(go.Scatter(
        x=xg, y=dens, mode="lines", name="normal",
        line={"color": AMBAR, "width": 2}))

    fig.update_layout(showlegend=False, margin=BASE["margin"], **_sin_margen(232))
    _ejes(fig)
    fig.update_xaxes(title_text=f"residual ({unidad})", title_font_size=10)
    return fig


# --- Salud del nodo ---------------------------------------------------------
def fig_salud(df: pd.DataFrame) -> go.Figure:
    """Memoria libre y completitud del muestreo, en ejes independientes."""
    t = df["t_fin"].dt.tz_convert(TZ).to_numpy()

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    if "diag.heap" in df.columns:
        fig.add_trace(go.Scatter(
            x=t, y=df["diag.heap"].to_numpy(dtype=float), mode="lines",
            name="Heap (B)",
            line={"color": CIAN, "width": 1.8},
            fill="tozeroy", fillcolor="rgba(34,199,232,0.10)",
            hovertemplate="%{y:.0f} B<extra>heap</extra>"), secondary_y=False)

    if "temp_c.n" in df.columns:
        fig.add_trace(go.Scatter(
            x=t, y=df["temp_c.n"].to_numpy(dtype=float), mode="lines",
            name="Muestras",
            line={"color": ROSA, "width": 1.6},
            hovertemplate="%{y:.0f}<extra>muestras</extra>"), secondary_y=True)

    if "boot" in df.columns:
        cambios = np.flatnonzero(df["boot"].ne(df["boot"].shift(1)).to_numpy())[1:]
        for i in cambios:
            fig.add_vline(x=t[i], line={"color": "rgba(251,191,36,0.32)",
                                        "dash": "dot", "width": 1})

    fig.update_layout(
        showlegend=True,
        legend={"orientation": "h", "y": 1.16, "x": 0,
                "bgcolor": "rgba(0,0,0,0)", "font": {"size": 10}},
        margin={"l": 48, "r": 42, "t": 30, "b": 34},
        **_sin_margen(232))
    fig.update_xaxes(showgrid=False, color=TEXTO_BAJO)
    fig.update_yaxes(showgrid=True, gridcolor=REJILLA, color=TEXTO_BAJO,
                     secondary_y=False)
    fig.update_yaxes(showgrid=False, color=TEXTO_BAJO, secondary_y=True)
    return fig
