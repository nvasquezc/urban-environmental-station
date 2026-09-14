#pragma once
#include <Arduino.h>

struct SoundBlock {
  float nivel_db;   // nivel del bloque
  bool  recorte;    // saturacion detectada
  bool  valido;
};

// Contrato comun a todos los frontends de sonido.
// Permite intercambiar DFR0034 <-> MEMS I2S sin tocar el resto del firmware.
class SoundSensor {
 public:
  virtual ~SoundSensor() {}
  virtual bool begin() = 0;
  virtual SoundBlock readBlock() = 0;

  // Identificador de escala; se serializa en cada registro.
  virtual const char* escala() const = 0;
  // true solo si existe sensibilidad declarada por el fabricante.
  virtual bool trazable() const = 0;

  float k() const { return k_; }
  void  setK(float v) { k_ = v; }

 protected:
  float k_ = 0.0f;
};
