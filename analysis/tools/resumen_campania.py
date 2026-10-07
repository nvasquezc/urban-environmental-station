"""Resumen del estado de la campaña en curso.

Reporta los indicadores que sustentan cualquier afirmación sobre el período:
cobertura efectiva, continuidad, especificación del modelo, escalas temporales
del residual y estabilidad del instrumento.

Uso:
    cd analysis
    uv run python tools/resumen_campania.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "analysis"))

from dashboard.datos import DEVICE_ID, cargar  # noqa: E402
from uestation.decompose import (  # noqa: E402
    ajustar_ciclo_diurno,
    detectar_tendencia,
    incertidumbre_expandida,
    variabilidad_diaria,
)
from uestation.escalas import separar_escalas  # noqa: E402
from uestation.forecast import _cadencia_sugerida  # noqa: E402
from uestation.qc import (  # noqa: E402
    aplicar_qc,
    completitud,
    detectar_huecos,
    diagnostico_estabilidad,
)

TZ = "America/Bogota"
INTERVALO_MIN = 5


def seccion(titulo: str) -> None:
    print(f"\n{titulo}")
    print("─" * 68)


def _min(valor: float) -> str:
    return f"{valor:.0f} min" if np.isfinite(valor) else "no estimable"


def main() -> None:
    df, origen = cargar()
    if df.empty:
        print("Sin datos disponibles.")
        return

    limpio, resumen = aplicar_qc(df)
    if limpio.empty:
        print("Ningún registro supera el control de calidad.")
        return

    t0 = limpio["t_fin"].min().tz_convert(TZ)
    t1 = limpio["t_fin"].max().tz_convert(TZ)
    dias = (t1 - t0).total_seconds() / 86400.0

    seccion(f"CAMPAÑA · nodo {DEVICE_ID} · {origen}")
    print(f"  Período          {t0:%Y-%m-%d %H:%M} a {t1:%Y-%m-%d %H:%M}")
    print(f"  Duración         {dias:.1f} días")

    # --- Cobertura ---
    c = completitud(limpio)
    huecos = detectar_huecos(limpio)
    faltantes = int(huecos["intervalos_faltantes"].sum()) if not huecos.empty else 0

    seccion("COBERTURA")
    print(f"  Registros válidos    {len(limpio)} de {resumen.n_entrada} "
          f"({100 * resumen.n_salida / resumen.n_entrada:.1f} %)")
    print(f"  Descartados por QC   {resumen.n_descartado}")
    for causa, n in resumen.descartes.items():
        if n:
            print(f"      {causa:26s} {n}")
    print(f"  Completitud          {c['completitud']:.1%} "
          f"({c['presentes']} de {c['esperados']} esperados)")
    print(f"  Interrupciones       {len(huecos)} · {faltantes} intervalos ausentes")

    if not huecos.empty:
        print("\n  Cortes de mayor duración:")
        top = huecos.nlargest(min(4, len(huecos)), "duracion_s")
        for _, h in top.iterrows():
            ini = h["inicio"].tz_convert(TZ)
            print(f"      {ini:%d %b %H:%M}  ·  {h['duracion_s'] / 3600:5.1f} h  ·  "
                  f"{int(h['intervalos_faltantes'])} intervalos")

    # --- Modelo ---
    contraste = detectar_tendencia(limpio, "temp_c.prom")
    modelo = ajustar_ciclo_diurno(limpio, "temp_c.prom",
                                  con_tendencia=contraste["recomendada"])
    u = incertidumbre_expandida(limpio)

    seccion("MODELO")
    print(f"  Especificación       ciclo diurno, {modelo.n_armonicos} armónicos"
          + (" + tendencia" if modelo.con_tendencia else ""))
    print(f"  Varianza explicada   {modelo.varianza_explicada:.3f}")
    print(f"  σ residual           {modelo.sigma_residual:.3f} °C")
    print(f"  Amplitud diurna      {modelo.amplitud_diurna:.2f} °C")
    if u:
        print(f"  U (k=2)              {u['U_expandida_k2']:.4f} °C "
              "(cota inferior, sin calibración)")

    seccion("CONTRASTE DE TENDENCIA")
    print(f"  Pendiente global     {contraste['pendiente_dia']:+.4f} °C/día")
    print(f"  Bloques              {contraste['bloques_pendientes']}")
    print(f"  CV entre bloques     {contraste['cv_bloques']:.2f}")
    print(f"  ρ (rezago 1)         {contraste['rho_lag1']:.4f}")
    print(f"  n efectivo           {contraste['n_efectivo']:.0f} "
          f"de {contraste['n_observaciones']}")
    print(f"  t = {contraste['razon_senal_ruido']:.2f} frente a "
          f"{contraste['t_critico']:.2f} crítico")
    print(f"  Decisión             {contraste['recomendada']}")
    print(f"      {contraste['motivo']}")

    # --- Escalas temporales ---
    seccion("ESCALAS TEMPORALES DEL RESIDUAL")
    try:
        e = separar_escalas(modelo, intervalo_min=INTERVALO_MIN)
        print(f"  τ residual completo  {_min(e.tau_total_min)}  "
              "(dominado por regímenes sinópticos)")
        print(f"  τ intradiario        {_min(e.tau_intradiario_min)}  "
              f"(pasa altos de {e.ventana_h:.0f} h)")
        print(f"  σ sinóptica          {np.sqrt(e.var_sinoptica):.3f} °C")
        print(f"  σ intradiaria        {np.sqrt(e.var_intradiaria):.3f} °C")
        print(f"  Fracción sinóptica   {e.fraccion_sinoptica:.0%} de la varianza residual")
        if np.isfinite(e.rho_diario):
            print(f"  ρ entre jornadas     {e.rho_diario:+.2f} "
                  f"({e.n_dias} jornadas con cobertura suficiente)")
        if np.isfinite(e.tau_intradiario_min):
            cad = _cadencia_sugerida(e.tau_intradiario_min, INTERVALO_MIN)
            print(f"  Cadencia sugerida    {cad} min  (τ intradiario / 3)")
    except ValueError as exc:
        print(f"  No disponible: {exc}")

    # --- Instrumento ---
    diag = diagnostico_estabilidad(df)

    seccion("INSTRUMENTO")
    print(f"  Arranques            {diag.get('n_arranques', '—')}")
    print(f"  Espontáneos          {diag.get('reinicios_espontaneos', '—')}")
    print(f"  Causas de reinicio   {diag.get('causas_reset', {})}")
    print(f"  Heap mínimo          {diag.get('heap_min', 0):.0f} B")
    print(f"  Deriva de heap       {diag.get('heap_pendiente_bytes_hora', 0):+.1f} B/h")
    print(f"  Fragmentación máx.   {diag.get('frag_max_pct', 0):.0f} %")
    print(f"  Intervalos sin red   {diag.get('intervalos_sin_red', '—')} "
          "(recuperados por la cola persistente)")
    print(f"  Muestras · moda      {diag.get('muestras_moda', '—')}")
    print(f"  Muestras · mínimo    {diag.get('muestras_min', '—')}")
    print(f"  RSSI mediana         {diag.get('rssi_mediana', 0):.0f} dBm")

    # --- Variabilidad diaria ---
    v = variabilidad_diaria(limpio)
    if not v.empty:
        seccion("VARIABILIDAD POR JORNADA")
        print(f"  {'fecha':<12} {'n':>5} {'sesgo':>8} {'disp.':>8} "
              f"{'amplitud':>9} {'media':>8}")
        for _, f in v.iterrows():
            print(f"  {str(f['fecha']):<12} {int(f['n']):>5} {f['sesgo']:>+8.3f} "
                  f"{f['dispersion']:>8.3f} {f['amplitud']:>9.2f} {f['media']:>8.2f}")

    print()


if __name__ == "__main__":
    main()
