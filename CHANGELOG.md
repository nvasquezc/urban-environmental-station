# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Versionado según [SemVer](https://semver.org/lang/es/).

## [No publicado]

## [0.2.0] - 2026-09-13

### Agregado
- Agregación por intervalos de 5 min alineados al reloj, con estadísticos
  de dispersión y conteo de muestras por variable.
- Métricas de sonido compuestas en energía: Leq, Lmax, Lmin, L10, L90.
- Cola persistente en LittleFS (store-and-forward) con escritura idempotente.
- Diagnóstico de estado embebido en cada registro.
- Abstracción `SoundSensor` con implementaciones analógica e I2S.
- Soporte multiplataforma ESP8266 / ESP32-S3.
- Generador de coeficientes de ponderación A desde el prototipo IEC 61672.
- Protocolo de calibración por co-ubicación y esquema de datos versionado.

### Corregido respecto al prototipo inicial
- Nivel sonoro: mapeo logarítmico en lugar de lineal, RMS sin componente DC,
  promedio en energía en lugar de aritmético.
- Timestamps: epoch UTC único; se elimina la mezcla de fecha UTC con hora local.
- HDOP: se elimina la división redundante por 100.
- Telemetría desacoplada del ciclo de pantalla.
- Conexión WiFi no bloqueante; un fallo de sensor ya no detiene el sistema.
- Muestreo de sonido en bloques cortos, evitando desbordar el buffer del GPS.
- Se elimina el servidor HTTP local, inalcanzable desde entornos externos.
- UART del GPS abstraído por plataforma: SoftwareSerial en ESP8266,
  UART por hardware en ESP32 (elimina el riesgo de desbordamiento de buffer).

### Seguridad
- Credenciales movidas a `secrets.h`, excluido del control de versiones.

### Limitaciones conocidas
- Nivel sonoro sin trazabilidad metrológica.
  Ver `docs/06-limitaciones-conocidas.md`.
- TLS sin validación de certificado.
- Ponderación A verificada hasta 4 kHz con fs = 16 kHz; a 4 kHz la desviación
  es de −0.49 dB respecto al valor nominal, dentro de tolerancia clase 1.
- El build de ESP32 requiere PlatformIO Core >= 6.2.0 y el módulo `intelhex`
  instalado en el entorno de PlatformIO.

### Verificado
- Compilación exitosa en los tres entornos: `esp8266_d1mini`,
  `esp32s3_analog`, `esp32s3_i2s`.
- Uso de recursos: ESP8266 47.4% RAM / 45.9% Flash;
  ESP32-S3 con I2S 16.6% RAM / 30.0% Flash.

[0.2.0]: https://github.com/nvasquezc/urban-environmental-station/releases/tag/v0.2.0
