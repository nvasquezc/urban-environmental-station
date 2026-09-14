#pragma once
#include <Arduino.h>

// ===================== Identidad y versiones =====================
// Cambiar a "AAAA-MM-<sitio>" al aplicar coeficientes de una campana.
static const char* VERSION_CAL = "sin-calibrar";

// ===================== Temporizacion =============================
static const uint32_t INTERVALO_S         = 300;   // agregacion, alineada al reloj
static const uint32_t PERIODO_CLIMA_MS    = 2000;
static const uint32_t PERIODO_SONIDO_MS   = 125;   // cadencia "Fast"
static const uint32_t PERIODO_COLA_MS     = 10000;
static const uint32_t PERIODO_PANTALLA_MS = 5000;
static const uint8_t  MAX_ENVIOS_CICLO    = 3;
static const long     OFFSET_COLOMBIA_S   = -5L * 3600L;

// ===================== Pines =====================================
#if defined(ESP8266)
  static const uint8_t PIN_GPS_RX = 14;   // D5
  static const uint8_t PIN_GPS_TX = 12;   // D6
  static const uint8_t PIN_SONIDO = A0;
#elif defined(ESP32)
  static const uint8_t PIN_GPS_RX = 18;
  static const uint8_t PIN_GPS_TX = 17;
  static const uint8_t PIN_SONIDO = 4;    // ADC1_CH3
  static const int PIN_I2S_BCLK   = 5;
  static const int PIN_I2S_WS     = 6;
  static const int PIN_I2S_DIN    = 7;
#endif

// ===================== Calibracion clima =========================
// y = a*x + b. Se derivan por co-ubicacion (docs/02-protocolo-calibracion.md).
// NO modificar durante una campana de calibracion activa.
struct Cal { float a; float b; };
static const Cal CAL_TEMP = {1.0f, 0.0f};
static const Cal CAL_HR   = {1.0f, 0.0f};
static const Cal CAL_PRES = {1.0f, 0.0f};

// ===================== Sonido ====================================
#if defined(UES_SOUND_ANALOG)
  static const uint16_t SND_MUESTRAS     = 256;    // ~30 ms por bloque
  static const uint16_t SND_INTERVALO_US = 60;
  static const float    SND_K_DEFECTO    = 40.0f;  // arbitrario hasta calibrar
#elif defined(UES_SOUND_I2S)
  static const uint32_t SND_FS_HZ        = 16000;
  static const uint16_t SND_MUESTRAS     = 512;    // 32 ms por bloque
  // ICS-43434: -26 dBFS @ 94 dB SPL  =>  SPL = dBFS + 120
  static const float    SND_REF_DBFS     = 120.0f;
  static const float    SND_K_DEFECTO    = 0.0f;   // correccion residual
#else
  #error "Definir UES_SOUND_ANALOG o UES_SOUND_I2S en platformio.ini"
#endif

// ===================== Rangos de validez =========================
static const float LIM_TEMP_MIN = -20.0f, LIM_TEMP_MAX =   60.0f;
static const float LIM_HR_MIN   =   0.0f, LIM_HR_MAX   =  105.0f;
static const float LIM_PRES_MIN = 500.0f, LIM_PRES_MAX = 1100.0f;

// ===================== Almacenamiento ============================
static const char* COLA          = "/cola.jsonl";
static const char* COLA_TMP      = "/cola.tmp";
static const float FS_UMBRAL_USO = 0.85f;

// ===================== Esquema de datos ==========================
// Incrementar SOLO ante cambios incompatibles.
// Ver docs/03-esquema-de-datos.md
static const int ESQUEMA_DATOS = 1;
