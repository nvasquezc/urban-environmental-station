#pragma once
#include "SoundSensor.h"
#include "config.h"

// Frontend analogico (DFR0034 u otro modulo de electret).
// NO TRAZABLE: sin ponderacion frecuencial, sin sensibilidad declarada.
class SoundAnalog : public SoundSensor {
 public:
  explicit SoundAnalog(uint8_t pin) : pin_(pin) { k_ = SND_K_DEFECTO; }

  bool begin() override {
    pinMode(pin_, INPUT);
    return true;
  }

  SoundBlock readBlock() override {
    SoundBlock b{NAN, false, false};
    long suma = 0;
    for (uint16_t i = 0; i < SND_MUESTRAS; i++) {
      int s = analogRead(pin_);
      if (s <= 2 || s >= (ADC_MAX - 2)) b.recorte = true;
      buf_[i] = (int16_t)s;
      suma += s;
      delayMicroseconds(SND_INTERVALO_US);
    }
    // Media del bloque: elimina la componente DC sin asumir un centro fijo.
    float media = (float)suma / SND_MUESTRAS;
    double sc = 0;
    for (uint16_t i = 0; i < SND_MUESTRAS; i++) {
      float d = buf_[i] - media;
      sc += (double)d * d;
    }
    float rms = sqrtf((float)(sc / SND_MUESTRAS));
    if (rms < 0.5f) rms = 0.5f;          // piso de cuantizacion
    b.nivel_db = 20.0f * log10f(rms) + k_;
    b.valido = true;
    return b;
  }

  const char* escala() const override { return "sin_ponderar_aprox"; }
  bool trazable() const override { return false; }

 private:
#if defined(ESP8266)
  static const int ADC_MAX = 1023;
#else
  static const int ADC_MAX = 4095;
#endif
  uint8_t pin_;
  int16_t buf_[SND_MUESTRAS];
};
