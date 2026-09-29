/*
 * GridPulse - ESP32 "Station A" firmware (real device path)
 * ---------------------------------------------------------------------------------------------
 * LOW-VOLTAGE DEMO ONLY (12 V DC max). This is not an EV charger and must never switch mains.
 *
 * What it does (once per POLL_INTERVAL_MS):
 *   1. reads the INA219 (bus voltage, current, power) - or reports flagged placeholder values if it is absent
 *   2. GET  /device/{id}/command   -> {command, power_fraction, seq, valid_for_s}
 *   3. applies the command to the output pin (PWM into the MOSFET gate)  -- or only *pretends* when DRY_RUN
 *   4. POST /device/{id}/ack       -> once per new command sequence number
 *   5. POST /telemetry/update      -> readings + mode + flags (source="real", dry_run, sensor_status)
 *
 * Safety design:
 *   - boot state is OUTPUT OFF; the output stays off until the first valid command arrives
 *   - FAILSAFE: no valid command for `valid_for_s` (Wi-Fi lost, backend down) => OUTPUT OFF
 *   - duty is clamped to MAX_DUTY_PCT locally, whatever the backend says
 *   - latched fault (overcurrent / overvoltage, only when the output is really enabled) => OUTPUT OFF
 *   - button: short press toggles LOCAL OVERRIDE (output held OFF); long press clears a latched fault
 *   - external hardware must still provide a gate pull-down resistor and a fuse (>= 2 A)
 *
 * Honest fallbacks (all reported to the backend so the dashboard can label them):
 *   - DRY_RUN true       -> output pin is never driven; telemetry says dry_run=true
 *   - INA219 not found   -> values are 0 and sensor_status="missing" (placeholders, NOT measurements)
 *
 * Libraries (Arduino Library Manager or PlatformIO): "Adafruit INA219", "Adafruit BusIO", "ArduinoJson" (v7).
 * Board: "ESP32 Dev Module" (arduino-esp32 core 2.x or 3.x).
 */
#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Adafruit_INA219.h>
#include <ArduinoJson.h>

// =====================================================================================================
//  CONFIG  -  edit this block only.   (Do not commit real Wi-Fi passwords.)
// =====================================================================================================
#define WIFI_SSID          "YOUR_WIFI_NAME"
#define WIFI_PASSWORD      "YOUR_WIFI_PASSWORD"
#define BACKEND_BASE_URL   "http://192.168.1.50:8000"   // laptop LAN IP, port of `uvicorn`; plain http on the LAN
#define DEVICE_ID          "esp32-station-a"            // must match the station's device id (seeded: Station A)
#define STATION_CODE       "A"                          // bind to this station on register ("" = do not bind)
#define FIRMWARE_VERSION   "gridpulse-esp32 1.1.0"
#define DEVICE_API_KEY     ""                           // must equal the backend's DEVICE_API_KEY ("" = backend has none)

// Pin map (change to match your wiring - see docs/wiring.md)
constexpr int PIN_I2C_SDA    = 21;   // INA219 SDA
constexpr int PIN_I2C_SCL    = 22;   // INA219 SCL
constexpr int PIN_BUTTON     = 27;   // push button to GND (uses the internal pull-up)
constexpr int PIN_OUTPUT     = 25;   // MOSFET gate (via the LR7843 module's input), PWM
constexpr int PIN_STATUS_LED = 2;    // on-board LED
constexpr uint8_t INA219_I2C_ADDR = 0x40;

// Output
constexpr bool     DRY_RUN            = true;   // true = NEVER drive PIN_OUTPUT (MOSFET/bulb not connected yet)
constexpr bool     OUTPUT_ACTIVE_HIGH = true;   // false if the driver module is active-low
constexpr int      MAX_DUTY_PCT       = 90;     // local hard cap on output duty
constexpr uint32_t PWM_FREQ_HZ        = 1000;
constexpr uint8_t  PWM_RES_BITS       = 10;
constexpr int      PWM_CHANNEL        = 0;      // used only by arduino-esp32 core 2.x

// Safety limits (applied only when the output is really enabled, i.e. DRY_RUN == false)
constexpr float CURRENT_TRIP_A = 1.8f;   // must stay below the fuse rating
constexpr float VOLTAGE_MAX_V  = 16.0f;

// Telemetry
// The chip temperature is NOT load temperature and the backend uses `temperature` for its over-temperature rule,
// so it is not reported unless you attach a real sensor and change this.
constexpr bool REPORT_CHIP_TEMPERATURE = false;

// Timing
constexpr uint32_t POLL_INTERVAL_MS    = 1000;
constexpr uint32_t HTTP_TIMEOUT_MS     = 2500;
constexpr uint32_t WIFI_RETRY_MS       = 10000;
constexpr uint32_t SENSOR_RETRY_MS     = 10000;
constexpr uint32_t DEFAULT_VALID_FOR_MS = 15000;
constexpr uint32_t BUTTON_DEBOUNCE_MS  = 40;
constexpr uint32_t BUTTON_LONG_PRESS_MS = 2000;
// =====================================================================================================

// ---- state -----------------------------------------------------------------------------------------
static Adafruit_INA219 ina(INA219_I2C_ADDR);
static bool     sensorOk = false;
static uint32_t lastSensorTryMs = 0;

static bool     registered = false;
static bool     backendOk = false;
static bool     haveCommand = false;
static String   currentCommand = "NORMAL";
static float    targetFraction = 0.0f;
static long     lastSeq = -1;            // last command seq that was acknowledged successfully
static uint32_t lastCmdOkMs = 0;
static uint32_t validForMs = DEFAULT_VALID_FOR_MS;

static bool     localOverride = false;   // set by the button
static bool     faultLatched = false;
static String   faultName = "";
static String   pendingEvent = "";       // sent with the next telemetry packet, then cleared
static String   currentMode = "FAILSAFE";
static float    outputPct = 0.0f;

static uint32_t lastCycleMs = 0;
static uint32_t lastWifiTryMs = 0;
static bool     wifiWasUp = false;

// button (interrupt driven so a short press is not missed while an HTTP call blocks)
static volatile bool     btnDown = false;
static volatile bool     btnReleased = false;
static volatile uint32_t btnEdgeMs = 0;
static volatile uint32_t btnDownMs = 0;
static volatile uint32_t btnHeldMs = 0;
static bool              longHandled = false;

struct Reading {
  float v = 0, a = 0, w = 0;
  bool valid = false;
};

// ---- output ----------------------------------------------------------------------------------------
static void pwmWriteDuty(uint32_t duty) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(PIN_OUTPUT, duty);
#else
  ledcWrite(PWM_CHANNEL, duty);
#endif
}

static void writeOutput(float pct) {
  if (DRY_RUN) return;  // dry-run: the output pin is never driven
  const uint32_t maxDuty = (1u << PWM_RES_BITS) - 1;
  uint32_t duty = (uint32_t)(pct / 100.0f * maxDuty + 0.5f);
  if (duty > maxDuty) duty = maxDuty;
  if (!OUTPUT_ACTIVE_HIGH) duty = maxDuty - duty;
  pwmWriteDuty(duty);
}

static void outputInit() {
  if (DRY_RUN) {
    pinMode(PIN_OUTPUT, INPUT);  // high-impedance: definitely not driving anything
    return;
  }
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PIN_OUTPUT, PWM_FREQ_HZ, PWM_RES_BITS);
#else
  ledcSetup(PWM_CHANNEL, PWM_FREQ_HZ, PWM_RES_BITS);
  ledcAttachPin(PIN_OUTPUT, PWM_CHANNEL);
#endif
  writeOutput(0.0f);  // OFF first, before anything else runs
}

/** Decide mode + output from all inputs. Priority: fault > local override > failsafe > commanded. */
static void recomputeOutput() {
  const uint32_t now = millis();
  const bool failsafe = !haveCommand || (now - lastCmdOkMs > validForMs);
  if (faultLatched) {
    currentMode = String("FAULT_") + faultName;
    outputPct = 0.0f;
  } else if (localOverride) {
    currentMode = "LOCAL_OVERRIDE";
    outputPct = 0.0f;
  } else if (failsafe) {
    currentMode = "FAILSAFE";
    outputPct = 0.0f;
  } else {
    currentMode = currentCommand;
    outputPct = min(targetFraction * 100.0f, (float)MAX_DUTY_PCT);
  }
  writeOutput(outputPct);
}

// ---- sensor ----------------------------------------------------------------------------------------
static bool i2cPresent(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

static void initSensor() {
  lastSensorTryMs = millis();
  if (i2cPresent(INA219_I2C_ADDR) && ina.begin(&Wire)) {
    ina.setCalibration_32V_2A();
    sensorOk = true;
    Serial.println("[sensor] INA219 ready");
  } else {
    sensorOk = false;
    Serial.println("[sensor] INA219 NOT FOUND - telemetry will carry placeholder values (sensor_status=missing)");
  }
}

static Reading readSensor() {
  Reading r;
  if (!sensorOk) {
    if (millis() - lastSensorTryMs > SENSOR_RETRY_MS) initSensor();
    if (!sensorOk) return r;  // zeros, valid=false
  }
  if (!i2cPresent(INA219_I2C_ADDR)) {  // unplugged at runtime
    sensorOk = false;
    Serial.println("[sensor] INA219 stopped responding");
    return r;
  }
  const float v = ina.getBusVoltage_V();
  const float a = ina.getCurrent_mA() / 1000.0f;
  const float w = ina.getPower_mW() / 1000.0f;
  if (!isfinite(v) || !isfinite(a) || !isfinite(w) || v < 0 || v > 32.5f) {
    sensorOk = false;  // implausible => treat as a sensor error and retry later
    return r;
  }
  r.v = v; r.a = a; r.w = w; r.valid = true;
  return r;
}

static void latchFault(const char* name) {
  faultLatched = true;
  faultName = name;
  lastSeq = -1;  // force a re-ack (as "rejected") of the current command
  Serial.printf("[SAFETY] fault latched: %s - output OFF until a long button press\n", name);
  recomputeOutput();
}

static void checkFaults(const Reading& r) {
  if (!r.valid || DRY_RUN || faultLatched) return;  // trips only guard a really-driven output
  if (fabsf(r.a) > CURRENT_TRIP_A) latchFault("OVERCURRENT");
  else if (r.v > VOLTAGE_MAX_V) latchFault("OVERVOLTAGE");
}

// ---- http ------------------------------------------------------------------------------------------
static int httpCall(bool isPost, const String& path, const String& body, String& out) {
  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(client, String(BACKEND_BASE_URL) + path)) return -1;
  if (strlen(DEVICE_API_KEY) > 0) http.addHeader("X-Device-Key", DEVICE_API_KEY);
  int code;
  if (isPost) {
    http.addHeader("Content-Type", "application/json");
    code = http.POST(body);
  } else {
    code = http.GET();
  }
  out = (code > 0) ? http.getString() : http.errorToString(code);
  http.end();
  return code;
}

static bool registerDevice() {
  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["device_mode"] = "real";
  if (strlen(STATION_CODE) > 0) doc["station_code"] = STATION_CODE;
  doc["dry_run"] = DRY_RUN;
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["sensor_status"] = sensorOk ? "ok" : "missing";
  String body, resp;
  serializeJson(doc, body);
  const int code = httpCall(true, "/device/register", body, resp);
  Serial.printf("[net] register -> HTTP %d\n", code);
  if (code >= 200 && code < 300) return true;
  if (code == 409 || code == 404) Serial.printf("[net] register rejected: %s\n", resp.c_str());
  return false;
}

static bool sendAck(long seq, const String& command) {
  const char* status = faultLatched ? "rejected" : (localOverride ? "local_override" : "applied");
  String detail;
  if (faultLatched) detail = String("fault latched: ") + faultName;
  else if (localOverride) detail = "local override active: output held OFF";
  else detail = String(DRY_RUN ? "dry-run: would output " : "output ") + String(outputPct, 0) + "%";

  JsonDocument doc;
  doc["seq"] = seq;
  doc["command"] = command;
  doc["status"] = status;
  doc["detail"] = detail;
  doc["dry_run"] = DRY_RUN;
  doc["output_pct"] = outputPct;
  String body, resp;
  serializeJson(doc, body);
  const int code = httpCall(true, String("/device/") + DEVICE_ID + "/ack", body, resp);
  Serial.printf("[net] ack seq=%ld %s -> HTTP %d\n", seq, status, code);
  return code >= 200 && code < 300;
}

static void pollCommand() {
  String resp;
  const int code = httpCall(false, String("/device/") + DEVICE_ID + "/command", "", resp);
  if (code == 404) {  // backend does not know us (e.g. it was reset): register again
    registered = false;
    backendOk = false;
    return;
  }
  if (code != 200) {
    backendOk = false;
    Serial.printf("[net] command poll failed: HTTP %d %s\n", code, resp.c_str());
    return;
  }
  JsonDocument doc;
  if (deserializeJson(doc, resp)) {
    backendOk = false;
    Serial.println("[net] command poll: bad JSON");
    return;
  }
  backendOk = true;
  const String command = String((const char*)(doc["command"] | "NORMAL"));
  const float fraction = doc["power_fraction"] | 0.0f;
  const long seq = doc["seq"] | -1L;
  const uint32_t validFor = (uint32_t)((doc["valid_for_s"] | 15) * 1000UL);

  haveCommand = true;
  lastCmdOkMs = millis();
  validForMs = validFor;
  currentCommand = command;
  targetFraction = constrain(fraction, 0.0f, 1.0f);
  recomputeOutput();

  if (seq != lastSeq) {  // new command (or a state change that needs re-acknowledging)
    if (sendAck(seq, command)) lastSeq = seq;
  }
}

static bool sendTelemetry(const Reading& r) {
  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["voltage"] = max(0.0f, r.v);
  doc["current"] = r.a;
  doc["power"] = r.w;
  if (REPORT_CHIP_TEMPERATURE) doc["temperature"] = temperatureRead();
  doc["mode"] = currentMode;
  doc["source"] = "real";
  doc["dry_run"] = DRY_RUN;
  doc["sensor_status"] = sensorOk ? "ok" : "missing";
  doc["local_override"] = localOverride;
  if (pendingEvent.length() > 0) doc["event"] = pendingEvent;
  if (!sensorOk) doc["note"] = "INA219 not found - voltage/current/power are placeholders";
  else if (DRY_RUN) doc["note"] = "dry-run: output pin not driven";
  String body, resp;
  serializeJson(doc, body);
  const int code = httpCall(true, "/telemetry/update", body, resp);
  if (code >= 200 && code < 300) {
    pendingEvent = "";
    backendOk = true;
    return true;
  }
  backendOk = false;
  Serial.printf("[net] telemetry failed: HTTP %d %s\n", code, resp.c_str());
  return false;
}

// ---- button ----------------------------------------------------------------------------------------
void IRAM_ATTR onButtonEdge() {
  const uint32_t now = millis();
  if (now - btnEdgeMs < BUTTON_DEBOUNCE_MS) return;
  btnEdgeMs = now;
  if (digitalRead(PIN_BUTTON) == LOW) {
    btnDown = true;
    btnDownMs = now;
  } else if (btnDown) {
    btnDown = false;
    btnHeldMs = now - btnDownMs;
    btnReleased = true;
  }
}

static void onShortPress() {
  localOverride = !localOverride;
  pendingEvent = "button_press";
  lastSeq = -1;  // re-acknowledge the current command with the new state
  Serial.printf("[button] short press -> local override %s\n", localOverride ? "ON (output held OFF)" : "off");
  recomputeOutput();
}

static void onLongPress() {
  if (faultLatched) {
    faultLatched = false;
    faultName = "";
    pendingEvent = "fault_cleared";
    lastSeq = -1;
    Serial.println("[button] long press -> fault cleared");
    recomputeOutput();
  } else {
    Serial.println("[button] long press (no fault latched)");
  }
}

static void handleButton() {
  if (btnDown && !longHandled && millis() - btnDownMs >= BUTTON_LONG_PRESS_MS) {
    longHandled = true;
    onLongPress();
  }
  if (btnReleased) {
    noInterrupts();
    const bool released = btnReleased;
    const uint32_t held = btnHeldMs;
    btnReleased = false;
    interrupts();
    if (released) {
      if (!longHandled && held < BUTTON_LONG_PRESS_MS) onShortPress();
      longHandled = false;
    }
  }
}

// ---- wifi ------------------------------------------------------------------------------------------
static void ensureWifi() {
  const bool up = WiFi.status() == WL_CONNECTED;
  if (up && !wifiWasUp) {
    Serial.printf("[wifi] connected, IP %s\n", WiFi.localIP().toString().c_str());
    registered = false;  // (re)register after every reconnect
  } else if (!up && wifiWasUp) {
    Serial.println("[wifi] connection lost - output will fail safe if commands stop");
  }
  wifiWasUp = up;
  if (!up && millis() - lastWifiTryMs > WIFI_RETRY_MS) {
    lastWifiTryMs = millis();
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.println("[wifi] reconnecting...");
  }
}

// ---- main ------------------------------------------------------------------------------------------
static void cycle() {
  const Reading r = readSensor();
  checkFaults(r);
  recomputeOutput();

  if (WiFi.status() == WL_CONNECTED) {
    if (!registered) registered = registerDevice();
    if (registered) {
      pollCommand();
      sendTelemetry(r);
    }
  } else {
    backendOk = false;
  }
  recomputeOutput();  // applies failsafe if commands stopped arriving

  Serial.printf("[cycle] mode=%-16s out=%3.0f%% %5.2f V %6.3f A %6.2f W  sensor=%s wifi=%s backend=%s%s%s\n",
                currentMode.c_str(), outputPct, r.v, r.a, r.w, sensorOk ? "ok" : "MISSING",
                WiFi.status() == WL_CONNECTED ? "up" : "DOWN", backendOk ? "ok" : "no",
                DRY_RUN ? " [DRY-RUN]" : "", localOverride ? " [OVERRIDE]" : "");
}

void setup() {
  Serial.begin(115200);
  delay(200);
  pinMode(PIN_STATUS_LED, OUTPUT);
  outputInit();  // first thing: guarantee the output is OFF (or untouched in dry-run)
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_BUTTON), onButtonEdge, CHANGE);

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setClock(100000);
  initSensor();

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lastWifiTryMs = millis();

  Serial.println();
  Serial.println("=== GridPulse ESP32 " FIRMWARE_VERSION " ===");
  Serial.printf("device=%s station=%s backend=%s\n", DEVICE_ID, STATION_CODE, BACKEND_BASE_URL);
  Serial.printf("mode: %s output, INA219 %s\n", DRY_RUN ? "DRY-RUN (pin not driven)" : "LIVE (PWM active)",
                sensorOk ? "present" : "missing");
  recomputeOutput();
}

void loop() {
  handleButton();
  ensureWifi();
  recomputeOutput();  // keeps the failsafe timer honest even between cycles

  const uint32_t now = millis();
  if (now - lastCycleMs >= POLL_INTERVAL_MS) {
    lastCycleMs = now;
    cycle();
  }
  // status LED: solid = talking to backend, slow blink = no backend
  digitalWrite(PIN_STATUS_LED, backendOk ? HIGH : ((now / 500) % 2 ? HIGH : LOW));
  delay(5);
}
