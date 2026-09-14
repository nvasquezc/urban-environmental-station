# Limitaciones conocidas (v0.2.0)

Este documento declara explícitamente qué **no** puede hacer el sistema en su
estado actual. Declarar límites con precisión es parte del método, no una
concesión.

## Nivel sonoro

1. **Sin ponderación frecuencial en el frontend analógico.** El DFR0034 entrega
   una señal sin filtro de ponderación A. Los valores reportados con
   `escala = "sin_ponderar_aprox"` no son dB(A) y no son comparables con los
   estándares de la Resolución 627 de 2006.
2. **Sin trazabilidad.** El transductor no cumple IEC 61672 clase 1 ni clase 2,
   y no tiene sensibilidad declarada por el fabricante.
3. **Constante K sin determinar.** El valor por defecto (40.0 dB) es arbitrario
   y no corresponde a ninguna calibración.
4. **Rango dinámico desconocido.** El campo `son.clip` cuenta bloques saturados;
   un valor no nulo indica que el rango útil fue excedido.
5. **Ponderación A del frontend I2S verificada hasta 4 kHz.** Con fs = 16 kHz la
   desviación a 4 kHz es de −0.49 dB respecto al valor nominal (dentro de
   tolerancia clase 1). Por encima de esa frecuencia el warping bilineal degrada
   la respuesta. Para cobertura hasta 8 kHz es necesario regenerar los
   coeficientes a 48 kHz.
6. **Frontend I2S sin verificar en hardware.** Compila correctamente, pero no ha
   sido probado contra un micrófono físico.

## Variables climáticas

1. **Sin escudo de radiación en el prototipo.** La temperatura registrada bajo
   insolación directa presenta sesgo positivo no corregido.
2. **Autocalentamiento.** El AHT20 comparte PCB con el microcontrolador. La
   magnitud del efecto se determina en la Fase 0 del protocolo de calibración.
3. **Deriva del sensor de humedad no caracterizada.** Es precisamente el objeto
   de estudio del proyecto.
4. **Presión reportada como QFE** (presión de estación). La reducción a nivel del
   mar depende de la temperatura y se realiza en la capa de análisis, nunca en
   el firmware.
5. **Coeficientes de calibración en identidad.** Mientras
   `cal == "sin-calibrar"`, los valores son lecturas crudas del sensor.

## Sistema

1. **Punto único de autenticación.** El secreto de base de datos es compartido
   entre todas las unidades. Si se extrae de un dispositivo, otorga acceso
   completo a la base.
2. **TLS sin validación de certificado** (`setInsecure()`). Protege contra
   escucha pasiva pero no contra un ataque de intermediario.
3. **Sin respaldo energético.** La v0.2 depende de alimentación continua.
4. **Wi-Fi como única vía de transmisión.** Limita los sitios de instalación a
   lugares con cobertura de red.
5. **Margen de RAM estrecho en ESP8266.** 47.4 % de uso deja poco espacio para
   el handshake TLS. Es una de las razones para migrar a ESP32-S3.

## Qué NO se debe hacer con estos datos

- Sustentar quejas, denuncias o procesos sancionatorios por ruido.
- Reportar cumplimiento normativo ante autoridad ambiental.
- Comparar directamente con series de una red de referencia sin aplicar las
  funciones de corrección documentadas en `02-protocolo-calibracion.md`.
- Combinar series con `son.trazable == false` y `son.trazable == true` en un
  mismo análisis.
