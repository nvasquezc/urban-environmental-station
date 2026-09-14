# Urban Environmental Station

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Estación ambiental urbana de bajo costo con trazabilidad metrológica declarada.

## Motivación

Bogotá opera cerca de veinte estaciones de referencia para una ciudad de unos ocho
millones de habitantes. La densidad espacial resultante no captura la variabilidad
intraurbana de temperatura, humedad y ruido a escala de barrio.

Los sensores de bajo costo pueden cerrar esa brecha, pero solo si su incertidumbre
está caracterizada. Este proyecto no propone reemplazar la red de referencia: propone
densificarla y, sobre todo, cuantificar cuánto se le puede creer a un sensor de bajo
costo y por cuánto tiempo.

## Pregunta de investigación

¿Es posible estimar la deriva de sensores ambientales de bajo costo a partir de los
residuales entre nodos vecinos y una estación de referencia, sin recalibración física
periódica?

## Estado

**v0.2.0 — prototipo funcional, sin calibrar.** Las mediciones de nivel sonoro usan
una escala sin ponderación frecuencial y no son comparables con un sonómetro clase 1
o 2. No deben usarse con fines normativos ni legales.
Ver [docs/06-limitaciones-conocidas.md](docs/06-limitaciones-conocidas.md).

## Arquitectura

Nodo embebido → agregación de intervalos de 5 min alineados al reloj → cola persistente
en LittleFS → Firebase RTDB → capa bronze/silver/gold → validación por co-ubicación.

## Variables medidas

| Variable | Sensor | Rango declarado | Incertidumbre |
|---|---|---|---|
| Temperatura | AHT20 | −20 a 60 °C | pendiente de co-ubicación |
| Humedad relativa | AHT20 | 0 a 100 % | pendiente de co-ubicación |
| Presión (QFE) | BMP280 | 500 a 1100 hPa | pendiente de co-ubicación |
| Nivel sonoro | DFR0034 | sin determinar | **no trazable** |

## Compilar el firmware

```bash
cp firmware/include/secrets.example.h firmware/include/secrets.h
# editar secrets.h con las credenciales propias
pio run -d firmware -e esp8266_d1mini -t upload
```

## Reproducir el análisis

```bash
cd analysis
uv sync
uv run python tools/gen_aweighting.py
```

## Documentación

- [Protocolo de calibración](docs/02-protocolo-calibracion.md)
- [Esquema de datos](docs/03-esquema-de-datos.md)
- [Limitaciones conocidas](docs/06-limitaciones-conocidas.md)

## Cómo citar

Ver [CITATION.cff](CITATION.cff).

## Licencias

Código Apache-2.0 · Documentación y datos CC BY 4.0 · Hardware CERN-OHL-P v2.
Ver [LICENSE-docs.md](LICENSE-docs.md).

## Autor

Néstor Oswaldo Vásquez Castro · [ORCID 0009-0003-6483-790X](https://orcid.org/0009-0003-6483-790X)
Jitter Ingeniería SAS / Universidad Central · Bogotá, Colombia