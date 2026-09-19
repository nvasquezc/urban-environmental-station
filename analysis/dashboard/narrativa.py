"""Generación del texto interpretativo del tablero.

Los pies de figura no son decorativos: son la interpretación que separa un
conjunto de gráficos de un informe. Se generan a partir de los estadísticos
efectivamente calculados, de modo que el texto no puede contradecir a la
figura que acompaña.

Toda afirmación cuantitativa incluye su valor; ninguna afirma más de lo que
los datos sostienen.
"""

from __future__ import annotations

import numpy as np

from uestation.decompose import Descomposicion

# Especificación de fábrica del sensor de temperatura (hoja de datos AHT20).
ESPEC_AHT20_C = 0.3


def pie_descomposicion(d: Descomposicion) -> list:
    """Interpreta el ajuste del ciclo diurno y la magnitud del residual."""
    from dash import html

    n_anom = int(d.anomalias(k=2.0).sum())
    frac = n_anom / len(d.residual) if len(d.residual) else 0.0
    # Bajo normalidad, se espera un 4.6 % de observaciones fuera de ±2σ.
    esperado = 0.0455

    if d.sigma_residual < ESPEC_AHT20_C * 1.6:
        lectura_sigma = (
            f"La dispersión no explicada (σ = {d.sigma_residual:.3f} °C) es del mismo "
            f"orden que la incertidumbre de fábrica del sensor (±{ESPEC_AHT20_C} °C), "
            "lo que sugiere que el residual está dominado por ruido instrumental "
            "antes que por variabilidad ambiental."
        )
    else:
        lectura_sigma = (
            f"La dispersión no explicada (σ = {d.sigma_residual:.3f} °C) excede "
            f"holgadamente la incertidumbre de fábrica del sensor (±{ESPEC_AHT20_C} °C), "
            "lo que indica variabilidad ambiental real no capturada por el ciclo diurno."
        )

    if frac > esperado * 1.8:
        lectura_anom = (
            f" La proporción de observaciones fuera de ±2σ ({frac:.1%}, n = {n_anom}) "
            f"supera de forma apreciable lo esperado bajo normalidad ({esperado:.1%}), "
            "señal de eventos agrupados antes que de ruido aleatorio."
        )
    else:
        lectura_anom = (
            f" La proporción fuera de ±2σ ({frac:.1%}, n = {n_anom}) es compatible con "
            f"lo esperado bajo normalidad ({esperado:.1%})."
        )

    return [
        html.Strong(f"Figura 1. "),
        f"Serie observada, ciclo diurno ajustado mediante {d.n_armonicos} armónicos "
        f"de Fourier sobre la hora local, y residual resultante. El modelo explica el "
        f"{d.varianza_explicada:.1%} de la varianza total. ",
        lectura_sigma,
        lectura_anom,
    ]


def pie_acf(td: dict, intervalo_actual_min: int = 5) -> list:
    """Interpreta el tiempo de decorrelación en términos de diseño de muestreo."""
    from dash import html

    tau = td.get("minutos", np.nan)
    if not np.isfinite(tau):
        return [
            html.Strong("Figura 3. "),
            "La autocorrelación del residual no decae por debajo de 1/e dentro del "
            "rango examinado; se requiere una serie más extensa para estimar el "
            "tiempo de decorrelación.",
        ]

    factor = tau / intervalo_actual_min
    return [
        html.Strong("Figura 3. "),
        "Función de autocorrelación del residual. La banda gris delimita el rango "
        "compatible con ruido blanco. El decaimiento por debajo de 1/e ocurre a los ",
        html.Strong(f"{tau:.0f} minutos"),
        f", frente a un intervalo de muestreo actual de {intervalo_actual_min} minutos. ",
        f"El sistema opera por tanto con un sobremuestreo de factor {factor:.0f}: "
        "observaciones consecutivas aportan información redundante. ",
        html.Strong("Consecuencia de diseño: "),
        "el intervalo de transmisión admite una reducción sustancial sin pérdida de "
        "contenido informativo, con el consiguiente ahorro energético y de ancho de banda.",
    ]


def pie_histograma(d: Descomposicion) -> list:
    """Evalúa la normalidad aparente del residual."""
    from dash import html

    from scipy import stats

    r = d.residual.dropna().to_numpy()
    asimetria = float(stats.skew(r))
    curtosis = float(stats.kurtosis(r))  # exceso sobre la normal

    if abs(asimetria) < 0.5 and abs(curtosis) < 1.0:
        juicio = (
            "Ambos estadísticos son compatibles con una distribución normal, lo que "
            "respalda el uso de bandas ±2σ como criterio de detección de anomalías."
        )
    else:
        juicio = (
            "La desviación respecto a la normal sugiere estructura remanente en el "
            "residual; el criterio de ±2σ debe interpretarse como orientativo."
        )

    return [
        html.Strong("Figura 2. "),
        "Distribución empírica del residual con densidad normal de referencia "
        f"superpuesta. Asimetría = {asimetria:+.3f}; exceso de curtosis = {curtosis:+.3f}. ",
        juicio,
    ]


def pie_descartes(resumen) -> list:
    """Interpreta la tasa de rechazo del control de calidad."""
    from dash import html

    f = resumen.fraccion_descartada
    if resumen.n_descartado == 0:
        juicio = (
            "Ningún registro fue rechazado: la totalidad de los intervalos satisface "
            "los siete criterios del protocolo."
        )
    elif f > 0.10:
        juicio = (
            f"La tasa de rechazo ({f:.1%}) supera el umbral del 10 % establecido en el "
            "protocolo §5.4 y constituye en sí misma un hallazgo que debe reportarse."
        )
    else:
        juicio = (
            f"La tasa de rechazo ({f:.1%}) se mantiene por debajo del umbral del 10 % "
            "establecido en el protocolo §5.4."
        )

    return [
        html.Strong("Figura 4. "),
        "Registros rechazados por el control de calidad, desagregados por causa. Las "
        "causas son mutuamente excluyentes por construcción, de modo que suman "
        f"exactamente el total descartado ({resumen.n_descartado} de "
        f"{resumen.n_entrada}). ",
        juicio,
    ]


def pie_matriz() -> list:
    from dash import html

    return [
        html.Strong("Figura 5. "),
        "Temperatura media por hora del día y fecha. La regularidad de las bandas "
        "horizontales evidencia la estabilidad del ciclo diurno; cualquier celda sin "
        "color corresponde a un intervalo ausente, de modo que la figura documenta "
        "simultáneamente el patrón y la cobertura efectiva.",
    ]


def pie_salud(diag: dict, n_huecos: int) -> list:
    """Interpreta la estabilidad del instrumento."""
    from dash import html

    pend = diag.get("heap_pendiente_bytes_hora", 0.0)
    espontaneos = diag.get("reinicios_espontaneos", 0)

    if abs(pend) < 20:
        lectura_mem = (
            f"La memoria libre no presenta deriva apreciable ({pend:+.1f} B/h), lo que "
            "descarta una fuga de memoria en el período observado."
        )
    else:
        lectura_mem = (
            f"La memoria libre presenta una deriva de {pend:+.1f} B/h, compatible con "
            "una fuga; el sistema requiere revisión antes de una campaña prolongada."
        )

    if espontaneos == 0:
        lectura_reinicio = (
            " No se registraron reinicios espontáneos: la totalidad de los arranques "
            "corresponde a reprogramaciones inducidas."
        )
    else:
        lectura_reinicio = (
            f" Se registraron {espontaneos} reinicios espontáneos, cuya causa consta "
            "en el campo de diagnóstico de cada registro."
        )

    lectura_cobertura = (
        " La serie no presenta interrupciones."
        if n_huecos == 0
        else f" La serie presenta {n_huecos} interrupciones de cobertura."
    )

    return [
        html.Strong("Figura 6. "),
        "Indicadores de estabilidad del nodo: memoria libre, completitud del muestreo "
        "por intervalo e intensidad de señal. Las líneas verticales punteadas señalan "
        "reinicios. ",
        lectura_mem,
        lectura_reinicio,
        lectura_cobertura,
    ]
