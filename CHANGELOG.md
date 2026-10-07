# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Versionado según [SemVer](https://semver.org/lang/es/).

## [No publicado]

## [0.3.0] - 2026-10-07

### Agregado
- Control de calidad con siete criterios de rechazo y atribución excluyente de causa.
- Agregación horaria y diaria con propagación de varianza y composición energética
  del nivel sonoro.
- Descomposición armónica del ciclo diurno con término de tendencia opcional.
- Contraste de deriva con tres criterios: relevancia práctica, significancia corregida
  por autocorrelación y homogeneidad entre bloques temporales.
- Separación del residual en componentes sinóptica e intradiaria, con autocorrelación
  sobre rejilla regular que respeta las interrupciones del registro.
- Pronóstico a 24 h con persistencia de régimen y banda dependiente del horizonte.
- Validación de origen móvil con referencias climatológica y de ciclo sin persistencia.
- Prescripción operativa: cadencia de transmisión, mantenimiento e indicadores de
  suficiencia metodológica.
- Consola de monitoreo con vistas de resumen y de pronóstico.
- Herramientas de línea de comandos: resumen de campaña, prueba de estabilidad del
  tiempo de decorrelación, exportación reproducible de figuras e informe, y
  diagnóstico de la consola.
- Informe de resultados generado desde los datos (`docs/07-resultados-campania.md`).
- Figuras de publicación con paleta Okabe-Ito.
- Documentos de visión y alcance, y de arquitectura.
- Bitácora de campaña.

### Corregido
- La lectura de datos se limitaba a los últimos 5000 registros y recortaba en silencio
  el inicio de campañas de más de 17 días. El límite pasa a 60 000 registros y se
  advierte cuando se alcanza.
- El tiempo de decorrelación se calculaba sobre el residual completo, cuyo valor crece
  con la longitud del registro. Se reporta ahora el de la componente intradiaria,
  estable entre particiones.
- El control de calidad descartaba el primer registro de cualquier serie que
  comenzara en un arranque.
- La exportación de figuras abría una instancia del navegador por figura, lo que en
  Windows provocaba fallos al cerrarla. Se renderiza ahora en una única sesión.

### Verificado
- Campaña de 21.2 días con 99.7 % de registros válidos y ningún reinicio espontáneo.
- Estabilidad del tiempo de decorrelación intradiario entre mitades y tercios del
  registro (CV de 0.15 y 0.07).
- Recuperación de 464 intervalos transmitidos con retraso por la cola persistente.

### Limitaciones conocidas
- La banda de predicción cubre el 78 % de las observaciones frente al 95 % nominal.
- El error a horizontes cortos no se ha contrastado aún con la persistencia ingenua.
- Sin respaldo energético, una interrupción del suministro comercial detiene el
  registro: 28 h perdidas en la primera campaña.

## [0.2.0] - 2026-09-13

### Agregado
- Agregación por intervalos de 5 min alineados al reloj, con estadísticos de
  dispersión y conteo de muestras por variable.
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
  UART por hardware en ESP32.

### Seguridad
- Credenciales movidas a `secrets.h`, excluido del control de versiones.

[No publicado]: https://github.com/nvasquezc/urban-environmental-station/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/nvasquezc/urban-environmental-station/releases/tag/v0.3.0
[0.2.0]: https://github.com/nvasquezc/urban-environmental-station/releases/tag/v0.2.0
