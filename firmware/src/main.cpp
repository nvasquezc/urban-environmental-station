
/*
 * ============================================================
 *  Estacion Ambiental Urbana - firmware v0.2.0
 *  ESP8266 / ESP32-S3 + AHT20 + BMP280 + GPS NMEA + OLED
 * ============================================================
 *  Principios de diseno:
 *   1. El firmware mide y agrega. La interpretacion (normativa,
 *      reduccion a nivel del mar, alertas) vive en el backend.
 *   2. Nada bloquea: sin WiFi la estacion sigue midiendo y
 *      encola en LittleFS (store-and-forward).
 *   3. Cada registro es un intervalo agregado alineado al reloj,
 *      con timestamp UTC generado en el dispositivo.
 *   4. Escritura idempotente: clave = epoch UTC, reintentar
 *      nunca duplica.
 *
 *  Ver docs/03-esquema-de-datos.md para el contrato del registro.
 * ============================================================
 */
#include <Arduino.h>
#include <Wire.h>
#if defined(ESP8266)
  #include <SoftwareSerial.h>
#endif
#include <TinyGPS++.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Adafruit_BMP280.h>
#include <Adafruit_AHTX0.h>
#include <ArduinoJson.h>
#include <time.h>
#include <sys/time.h>

#include "config.h"
#include "secrets.h"
#include "platform.h"
#include "IntervalStats.h"
#include "SoundSensor.h"

#if defined(UES_SOUND_I2S)
  #include "SoundI2S.h"
  static SoundI2S sonido;
#else
  #include "SoundAnalog.h"
  static SoundAnalog sonido(PIN_SONIDO);
#endif

// --------------------------- Objetos -----------------------------
Adafruit_SSD1306 display(128, 64, &Wire, -1);
Adafruit_BMP280  bmp;
Adafruit_AHTX0   aht;
TinyGPSPlus      gps;
#if defined(ESP8266)
  SoftwareSerial gpsSerial(PIN_GPS_RX, PIN_GPS_TX);
#else
  HardwareSerial& gpsSerial = Serial1;   // UART1 por hardware
#endif
WiFiClientSecure tls;
HTTPClient       http;

// --------------------------- Estado ------------------------------
char     deviceId[16];
char     resetReason[40];
uint32_t bootCount = 0;
uint32_t seq = 0;
bool     okAht = false, okBmp = false, okOled = false, okSonido = false;
uint32_t descartados = 0, enviosOk = 0, enviosFallidos = 0;
long     slotActual = -1;
uint32_t inicioIntervaloMs = 0;

Estadistica eTemp, eHr, ePres;
AcumSonido  aSon;
float tempAct = NAN, hrAct = NAN, presAct = NAN, sonAct = NAN;

// --------------------------- Prototipos ---------------------------
// (el IDE de Arduino los generaba solo; PlatformIO no)
void alimentarGPS();
void sincronizarHoraGPS();
void leerClima();
void reintentarSensores();
void medirBloqueSonido();
void revisarIntervalo();
void cerrarIntervalo(uint32_t tFin);
void vaciarCola();
bool enviarRegistro(const char* clave, const char* json);
bool encolar(const char* clave, const char* json);
size_t tamCola();
void dibujar();
void vigilarWiFi();

// --------------------------- Utilidades --------------------------
float r1(float x) { return isfinite(x) ? roundf(x * 10.0f) / 10.0f : NAN; }
float r2(float x) { return isfinite(x) ? roundf(x * 100.0f) / 100.0f : NAN; }

bool horaValida() { return time(nullptr) > 1700000000; }

// Dias desde 1970-01-01 para una fecha civil (algoritmo de H. Hinnant)
int64_t diasDesdeCivil(int y, unsigned m, unsigned d) {
  y -= m <= 2;
  const int era = (y >= 0 ? y : y - 399) / 400;
  const unsigned yoe = (unsigned)(y - era * 400);
  const unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return (int64_t)era * 146097 + (int64_t)doe - 719468;
}

void alimentarGPS() {
  while (gpsSerial.available()) gps.encode(gpsSerial.read());
}

// Respaldo de reloj si NTP no esta disponible
void sincronizarHoraGPS() {
  if (horaValida()) return;
  if (!gps.date.isValid() || !gps.time.isValid()) return;
  if (gps.time.age() > 1000 || gps.date.year() < 2024) return;
  int64_t dias = diasDesdeCivil(gps.date.year(), gps.date.month(), gps.date.day());
  time_t t = (time_t)(dias * 86400LL + gps.time.hour() * 3600L +
                      gps.time.minute() * 60L + gps.time.second());
  timeval tv = { t, 0 };
  settimeofday(&tv, nullptr);
  Serial.println("[HORA] Sincronizada desde GPS");
}

// --------------------------- Sistema de archivos ------------------
uint32_t leerIncrementarBoot() {
  uint32_t n = 0;
  File f = LittleFS.open("/boot.txt", "r");
  if (f) { n = (uint32_t)f.parseInt(); f.close(); }
  n++;
  f = LittleFS.open("/boot.txt", "w");
  if (f) { f.print(n); f.close(); }
  return n;
}

size_t tamCola() {
  File f = LittleFS.open(COLA, "r");
  if (!f) return 0;
  size_t s = f.size();
  f.close();
  return s;
}

bool espacioDisponible() {
#if defined(ESP8266)
  FSInfo info;
  LittleFS.info(info);
  return info.usedBytes < info.totalBytes * FS_UMBRAL_USO;
#else
  return LittleFS.usedBytes() < LittleFS.totalBytes() * FS_UMBRAL_USO;
#endif
}

bool encolar(const char* clave, const char* json) {
  if (!espacioDisponible()) { descartados++; return false; }
  File f = LittleFS.open(COLA, "a");
  if (!f) { descartados++; return false; }
  f.print(clave); f.print('\t'); f.print(json); f.print('\n');
  f.close();
  return true;
}

// --------------------------- Envio a Firebase ---------------------
// PATCH multi-ruta: escribe datos/<clave> y ultimo en una sola peticion.
bool enviarRegistro(const char* clave, const char* json) {
  if (WiFi.status() != WL_CONNECTED) return false;
  static char url[220];
  static char cuerpo[2400];
  snprintf(url, sizeof(url), "%s/estaciones/%s.json?auth=%s",
           FIREBASE_DB_URL, deviceId, FIREBASE_SECRET);
  int n = snprintf(cuerpo, sizeof(cuerpo),
                   "{\"datos/%s\":%s,\"ultimo\":%s}", clave, json, json);
  if (n <= 0 || n >= (int)sizeof(cuerpo)) return false;

  if (!http.begin(tls, url)) return false;
  http.addHeader("Content-Type", "application/json");
  int code = http.PATCH((uint8_t*)cuerpo, (size_t)n);
  http.end();

  if (code == 200) { enviosOk++; Serial.printf("[HTTP] OK %s\n", clave); return true; }
  enviosFallidos++;
  Serial.printf("[HTTP] Fallo %s -> %d\n", clave, code);
  return false;
}

// Envia hasta MAX_ENVIOS_CICLO registros en orden FIFO; conserva el resto.
void vaciarCola() {
  if (WiFi.status() != WL_CONNECTED || !LittleFS.exists(COLA)) return;
  File f = LittleFS.open(COLA, "r");
  if (!f) return;

  File resto;
  bool hayResto = false, fallo = false;
  uint8_t enviados = 0;
  static char linea[1200];

  while (f.available()) {
    size_t len = f.readBytesUntil('\n', linea, sizeof(linea) - 1);
    linea[len] = '\0';
    if (len < 3) continue;

    if (!fallo && enviados < MAX_ENVIOS_CICLO) {
      char* tab = strchr(linea, '\t');
      if (!tab) continue;                      // linea corrupta: se descarta
      *tab = '\0';
      if (enviarRegistro(linea, tab + 1)) { enviados++; alimentarGPS(); continue; }
      *tab = '\t';
      fallo = true;
    }
    if (!hayResto) { resto = LittleFS.open(COLA_TMP, "w"); hayResto = true; }
    resto.write((const uint8_t*)linea, strlen(linea));
    resto.write('\n');
  }
  f.close();
  if (hayResto) resto.close();
  LittleFS.remove(COLA);
  if (hayResto) LittleFS.rename(COLA_TMP, COLA);
}

// --------------------------- Sensores -----------------------------
void configurarBmp() {
  bmp.setSampling(Adafruit_BMP280::MODE_NORMAL,
                  Adafruit_BMP280::SAMPLING_X2,
                  Adafruit_BMP280::SAMPLING_X16,
                  Adafruit_BMP280::FILTER_X16,
                  Adafruit_BMP280::STANDBY_MS_1000);
}

void leerClima() {
  if (okAht) {
    sensors_event_t h, t;
    if (aht.getEvent(&h, &t)) {
      float tc = CAL_TEMP.a * t.temperature + CAL_TEMP.b;
      float hr = CAL_HR.a * h.relative_humidity + CAL_HR.b;
      if (tc > LIM_TEMP_MIN && tc < LIM_TEMP_MAX) { tempAct = tc; eTemp.add(tc); }
      if (hr >= LIM_HR_MIN && hr <= LIM_HR_MAX) {
        hrAct = constrain(hr, 0.0f, 100.0f);
        eHr.add(hrAct);
      }
    } else {
      okAht = false;
    }
  }
  if (okBmp) {
    float p = CAL_PRES.a * (bmp.readPressure() / 100.0f) + CAL_PRES.b;
    if (p > LIM_PRES_MIN && p < LIM_PRES_MAX) { presAct = p; ePres.add(p); }
    else okBmp = false;
  }
}

void reintentarSensores() {
  static uint32_t t = 0;
  if (millis() - t < 60000) return;
  t = millis();
  if (!okAht) okAht = aht.begin();
  if (!okBmp) {
    okBmp = bmp.begin(BMP280_ADDRESS) || bmp.begin(BMP280_ADDRESS_ALT);
    if (okBmp) configurarBmp();
  }
}

void medirBloqueSonido() {
  if (!okSonido) return;
  SoundBlock b = sonido.readBlock();
  if (b.valido) { sonAct = b.nivel_db; aSon.add(b.nivel_db, b.recorte); }
}

// --------------------------- Intervalos ---------------------------
void cerrarIntervalo(uint32_t tFin) {
  JsonDocument doc;
  doc["esquema"]     = ESQUEMA_DATOS;
  doc["v"]           = FW_VERSION;
  doc["cal"]         = VERSION_CAL;
  doc["plat"]        = UES_PLATFORM;
  doc["id"]          = deviceId;
  doc["boot"]        = bootCount;
  doc["seq"]         = ++seq;
  doc["uptime_s"]    = millis() / 1000;
  doc["intervalo_s"] = INTERVALO_S;
  if (tFin > 0) doc["t_fin"] = tFin; else doc["t_fin"] = nullptr;

  doc["temp_c"]["prom"] = r2(eTemp.prom());
  doc["temp_c"]["min"]  = r2(eTemp.mn);
  doc["temp_c"]["max"]  = r2(eTemp.mx);
  doc["temp_c"]["n"]    = eTemp.n;

  doc["hr_pct"]["prom"] = r1(eHr.prom());
  doc["hr_pct"]["min"]  = r1(eHr.mn);
  doc["hr_pct"]["max"]  = r1(eHr.mx);
  doc["hr_pct"]["n"]    = eHr.n;

  doc["p_hpa"]["prom"]  = r2(ePres.prom());   // QFE, presion de estacion
  doc["p_hpa"]["min"]   = r2(ePres.mn);
  doc["p_hpa"]["max"]   = r2(ePres.mx);
  doc["p_hpa"]["n"]     = ePres.n;

  doc["son"]["leq"]      = r1(aSon.leq());
  doc["son"]["lmax"]     = r1(aSon.lmax);
  doc["son"]["lmin"]     = r1(aSon.lmin);
  doc["son"]["l10"]      = r1(aSon.excedido(0.10f));
  doc["son"]["l90"]      = r1(aSon.excedido(0.90f));
  doc["son"]["n"]        = aSon.n;
  doc["son"]["clip"]     = aSon.clip;
  doc["son"]["k"]        = sonido.k();
  doc["son"]["escala"]   = sonido.escala();
  doc["son"]["trazable"] = sonido.trazable();

  bool fix = gps.location.isValid() && gps.location.age() < 10000;
  doc["gps"]["fix"] = fix;
  if (fix) {
    doc["gps"]["lat"]   = gps.location.lat();
    doc["gps"]["lon"]   = gps.location.lng();
    doc["gps"]["alt_m"] = r1(gps.altitude.meters());
    doc["gps"]["sat"]   = gps.satellites.value();
    doc["gps"]["hdop"]  = r2(gps.hdop.hdop());
  }

  if (WiFi.status() == WL_CONNECTED) doc["diag"]["rssi"] = WiFi.RSSI();
  else doc["diag"]["rssi"] = nullptr;
  doc["diag"]["heap"]        = plat::freeHeap();
  doc["diag"]["frag"]        = plat::heapFrag();
  doc["diag"]["reset"]       = resetReason;
  doc["diag"]["aht"]         = okAht;
  doc["diag"]["bmp"]         = okBmp;
  doc["diag"]["descartados"] = descartados;
  doc["diag"]["fallos_http"] = enviosFallidos;

  static char json[1100];
  if (measureJson(doc) >= sizeof(json)) {
    Serial.println("[INT] JSON demasiado grande, registro omitido");
  } else {
    serializeJson(doc, json, sizeof(json));
    char clave[32];
    if (tFin > 0) snprintf(clave, sizeof(clave), "%lu", (unsigned long)tFin);
    else snprintf(clave, sizeof(clave), "nt_%lu_%lu",
                  (unsigned long)bootCount, (unsigned long)seq);
    encolar(clave, json);
    Serial.printf("[INT] %s %s\n", clave, json);
  }

  eTemp.reset(); eHr.reset(); ePres.reset(); aSon.reset();
}

void revisarIntervalo() {
  if (horaValida()) {
    uint32_t ahora = (uint32_t)time(nullptr);
    long slot = (long)(ahora / INTERVALO_S);
    if (slotActual < 0) { slotActual = slot; return; }
    if (slot != slotActual) {
      slotActual = slot;
      cerrarIntervalo((uint32_t)slot * INTERVALO_S);
      inicioIntervaloMs = millis();
    }
  } else if (millis() - inicioIntervaloMs >= INTERVALO_S * 1000UL) {
    inicioIntervaloMs = millis();
    cerrarIntervalo(0);
  }
}

// --------------------------- Pantalla -----------------------------
void dibujar() {
  static uint8_t pantalla = 0;
  static uint32_t tCambio = 0;
  if (millis() - tCambio > PERIODO_PANTALLA_MS) {
    tCambio = millis();
    pantalla = (pantalla + 1) % 3;
  }

  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);

  if (pantalla == 0) {
    display.println("CLIMA");
    display.println("---------------------");
    display.printf("T:  %.1f C\n", tempAct);
    display.printf("HR: %.1f %%\n", hrAct);
    display.printf("P:  %.1f hPa\n", presAct);
    display.printf("muestras: %lu\n", (unsigned long)eTemp.n);
  } else if (pantalla == 1) {
    display.println("SONIDO (sin calibrar)");
    display.println("---------------------");
    display.setTextSize(2);
    display.printf("%.0f dB\n", sonAct);
    display.setTextSize(1);
    display.printf("Leq int: %.1f\n", aSon.leq());
    display.printf("Lmax:    %.1f\n", aSon.lmax);
  } else {
    char hora[24] = "sin hora";
    if (horaValida()) {
      time_t loc = time(nullptr) + OFFSET_COLOMBIA_S;
      struct tm tmL;
      gmtime_r(&loc, &tmL);
      strftime(hora, sizeof(hora), "%d/%m %H:%M:%S", &tmL);
    }
    display.println("ESTADO");
    display.println("---------------------");
    display.println(hora);
    display.printf("WiFi: %s\n", WiFi.status() == WL_CONNECTED ? "OK" : "sin red");
    display.printf("GPS: %s sat:%lu\n", gps.location.isValid() ? "fix" : "--",
                   (unsigned long)gps.satellites.value());
    display.printf("Cola: %u B\n", (unsigned)tamCola());
    display.print(deviceId);
  }
  display.display();
}

// --------------------------- WiFi ---------------------------------
void vigilarWiFi() {
  static uint32_t desconectadoDesde = 0;
  if (WiFi.status() == WL_CONNECTED) { desconectadoDesde = 0; return; }
  if (desconectadoDesde == 0) desconectadoDesde = millis();
  if (millis() - desconectadoDesde > 300000UL) {   // 5 min sin red
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    desconectadoDesde = millis();
  }
}

// --------------------------- Setup / Loop -------------------------
void setup() {
  #if defined(ESP8266)
  gpsSerial.begin(9600);
#else
  gpsSerial.begin(9600, SERIAL_8N1, PIN_GPS_RX, PIN_GPS_TX);
#endif
  delay(200);
  plat::chipId(deviceId, sizeof(deviceId));
  plat::resetReason(resetReason, sizeof(resetReason));
  Serial.printf("\nEstacion %s | fw %s | plat %s | reset: %s\n",
                deviceId, FW_VERSION, UES_PLATFORM, resetReason);

  if (!LittleFS.begin()) {
    Serial.println("[FS] Formateando LittleFS...");
    LittleFS.format();
    LittleFS.begin();
  }
  if (!LittleFS.exists(COLA) && LittleFS.exists(COLA_TMP))
    LittleFS.rename(COLA_TMP, COLA);
  bootCount = leerIncrementarBoot();

  Wire.begin();
  okOled = display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  if (okOled) {
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.println("Iniciando...");
    display.println(deviceId);
    display.display();
  }
  okAht = aht.begin();
  okBmp = bmp.begin(BMP280_ADDRESS) || bmp.begin(BMP280_ADDRESS_ALT);
  if (okBmp) configurarBmp();
  okSonido = sonido.begin();

  Serial.printf("AHT20:%d BMP280:%d OLED:%d Sonido:%d | boot:%lu\n",
                okAht, okBmp, okOled, okSonido, (unsigned long)bootCount);
  Serial.printf("Sonido: escala=%s trazable=%d\n",
                sonido.escala(), sonido.trazable());

  gpsSerial.begin(9600);
  eTemp.reset(); eHr.reset(); ePres.reset(); aSon.reset();

  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  configTime(0, 0, "pool.ntp.org", "time.google.com");   // reloj interno en UTC

  tls.setInsecure();   // PROTOTIPO: sin validacion de certificado
  http.setReuse(true);
  http.setTimeout(8000);

  inicioIntervaloMs = millis();
}

void loop() {
  static uint32_t tSon = 0, tClima = 0, tCola = 0, tPant = 0;
  alimentarGPS();
  uint32_t ahora = millis();

  if (ahora - tSon >= PERIODO_SONIDO_MS) {
    tSon = ahora; medirBloqueSonido(); alimentarGPS();
  }
  if (ahora - tClima >= PERIODO_CLIMA_MS) { tClima = ahora; leerClima(); }

  sincronizarHoraGPS();
  revisarIntervalo();

  if (ahora - tCola >= PERIODO_COLA_MS) { tCola = ahora; vaciarCola(); }
  if (okOled && ahora - tPant >= 1000) { tPant = ahora; dibujar(); }

  reintentarSensores();
  vigilarWiFi();
}
