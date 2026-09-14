#pragma once
#include <Arduino.h>
#include <math.h>
#include <string.h>

// Estadistico escalar de un intervalo.
struct Estadistica {
  double suma; float mn, mx; uint32_t n;

  void reset() { suma = 0; mn = NAN; mx = NAN; n = 0; }

  void add(float x) {
    if (!isfinite(x)) return;
    suma += x; n++;
    if (n == 1 || x < mn) mn = x;
    if (n == 1 || x > mx) mx = x;
  }

  float prom() const { return n ? (float)(suma / n) : NAN; }
};

// Acumulador de nivel sonoro. Promedia en ENERGIA, no en dB.
struct AcumSonido {
  static const uint8_t BINS = 140;   // 0..139 dB, resolucion 1 dB
  double energia; float lmax, lmin; uint32_t n, clip; uint16_t hist[BINS];

  void reset() {
    energia = 0; lmax = NAN; lmin = NAN; n = 0; clip = 0;
    memset(hist, 0, sizeof(hist));
  }

  void add(float L, bool recorte) {
    if (!isfinite(L)) return;
    energia += pow(10.0, L / 10.0);
    if (n == 0 || L > lmax) lmax = L;
    if (n == 0 || L < lmin) lmin = L;
    n++;
    if (recorte) clip++;
    int b = (int)L;
    if (b < 0) b = 0;
    if (b >= BINS) b = BINS - 1;
    if (hist[b] < 65535) hist[b]++;
  }

  float leq() const { return n ? (float)(10.0 * log10(energia / n)) : NAN; }

  // Nivel excedido el p del tiempo: L10 -> p=0.10, L90 -> p=0.90
  float excedido(float p) const {
    if (!n) return NAN;
    uint32_t objetivo = (uint32_t)ceilf(p * n), acum = 0;
    for (int i = BINS - 1; i >= 0; --i) {
      acum += hist[i];
      if (acum >= objetivo) return i + 0.5f;
    }
    return 0.5f;
  }
};
