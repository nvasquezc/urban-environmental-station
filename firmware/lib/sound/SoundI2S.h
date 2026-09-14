#pragma once
#if defined(ESP32) && defined(UES_SOUND_I2S)

#include "SoundSensor.h"
#include "config.h"
#include "aweighting_coeffs.h"
#include <driver/i2s.h>
#include <math.h>
#include <string.h>

// Frontend digital I2S para microfono MEMS tipo ICS-43434.
// Base trazable: sensibilidad declarada en hoja de datos
// (-26 dBFS @ 94 dB SPL  =>  SPL = dBFS + 120).
// ESTADO: implementado, SIN VERIFICAR EN HARDWARE.
class SoundI2S : public SoundSensor {
 public:
  SoundI2S() { k_ = SND_K_DEFECTO; }

  bool begin() override {
    i2s_config_t cfg = {};
    cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
    cfg.sample_rate = SND_FS_HZ;
    cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
    cfg.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;
    cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
    cfg.dma_buf_count = 4;
    cfg.dma_buf_len = SND_MUESTRAS;
    cfg.use_apll = false;

    i2s_pin_config_t pines = {};
    pines.bck_io_num = PIN_I2S_BCLK;
    pines.ws_io_num = PIN_I2S_WS;
    pines.data_out_num = I2S_PIN_NO_CHANGE;
    pines.data_in_num = PIN_I2S_DIN;

    if (i2s_driver_install(I2S_NUM_0, &cfg, 0, nullptr) != ESP_OK) return false;
    if (i2s_set_pin(I2S_NUM_0, &pines) != ESP_OK) return false;
    memset(z_, 0, sizeof(z_));
    return true;
  }

  SoundBlock readBlock() override {
    SoundBlock b{NAN, false, false};
    size_t leidos = 0;
    if (i2s_read(I2S_NUM_0, raw_, sizeof(raw_), &leidos, pdMS_TO_TICKS(100)) != ESP_OK)
      return b;
    size_t n = leidos / sizeof(int32_t);
    if (n < SND_MUESTRAS / 2) return b;

    const float ESCALA = 1.0f / 8388608.0f;   // 2^23
    double sc = 0;
    for (size_t i = 0; i < n; i++) {
      int32_t s24 = raw_[i] >> 8;             // 24 bits alineados a la izquierda
      if (s24 >= 8388600 || s24 <= -8388600) b.recorte = true;
      float y = aplicarPonderacionA(s24 * ESCALA);
      sc += (double)y * y;
    }
    float rms = sqrtf((float)(sc / n));
    if (rms < 1e-7f) rms = 1e-7f;
    b.nivel_db = 20.0f * log10f(rms) + SND_REF_DBFS + k_;
    b.valido = true;
    return b;
  }

  const char* escala() const override { return "dBA_iec61672_aprox"; }
  bool trazable() const override { return true; }

 private:
  int32_t raw_[SND_MUESTRAS];
  float z_[AW_NSOS][2];

  // Cascada de biquads en forma directa II transpuesta.
  // Coeficientes generados por analysis/tools/gen_aweighting.py
  float aplicarPonderacionA(float x) {
    for (int s = 0; s < AW_NSOS; s++) {
      const float* c = AW_SOS[s];   // b0 b1 b2 a0 a1 a2  (a0 == 1)
      float y = c[0] * x + z_[s][0];
      z_[s][0] = c[1] * x - c[4] * y + z_[s][1];
      z_[s][1] = c[2] * x - c[5] * y;
      x = y;
    }
    return x;
  }
};

#endif  // ESP32 && UES_SOUND_I2S
