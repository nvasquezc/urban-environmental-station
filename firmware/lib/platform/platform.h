#pragma once
#include <Arduino.h>

#if defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266HTTPClient.h>
  #define UES_PLATFORM "esp8266"
#elif defined(ESP32)
  #include <WiFi.h>
  #include <HTTPClient.h>
  #include <esp_system.h>
  #define UES_PLATFORM "esp32"
#else
  #error "Plataforma no soportada"
#endif

#include <WiFiClientSecure.h>
#include <LittleFS.h>

namespace plat {

inline void chipId(char* out, size_t n) {
#if defined(ESP8266)
  snprintf(out, n, "ues-%06x", (unsigned)ESP.getChipId());
#else
  uint64_t mac = ESP.getEfuseMac();
  snprintf(out, n, "ues-%06x", (unsigned)(mac & 0xFFFFFF));
#endif
}

inline void resetReason(char* out, size_t n) {
#if defined(ESP8266)
  strlcpy(out, ESP.getResetReason().c_str(), n);
#else
  snprintf(out, n, "%d", (int)esp_reset_reason());
#endif
}

inline uint32_t freeHeap() { return ESP.getFreeHeap(); }

inline int heapFrag() {
#if defined(ESP8266)
  return ESP.getHeapFragmentation();
#else
  return -1;   // no disponible en ESP32
#endif
}

}  // namespace plat
