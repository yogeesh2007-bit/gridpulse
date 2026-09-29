/*
 * GridPulse bulb node - ESP32 + relay + push button (verified wiring: relay IN = GPIO25, button = GPIO27 to GND).
 *
 *   button press  -> toggles the relay locally at once, then reports it   (source "manual_button")
 *   backend cmd   -> polled every 3 s, applied to the relay, reported      (source "remote_command")
 *   boot / 10 s   -> reports state                                        (sources "boot" / "heartbeat")
 *
 * Safe boot: the relay is driven OFF before Wi-Fi starts, and stays off until the backend says otherwise.
 * LOW-VOLTAGE LOADS ONLY (12 V bulb). A relay can switch mains: do not use this project for mains.
 * Settings live in config.h (git-ignored; copy config.example.h). Works with http:// and https:// backends.
 */
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include "config.h"

// ---- API contract (see docs/bulb-node.md) ---------------------------------------------------------------------
//   POST {BASE}/api/bulb/{id}/status   {"bulb_on":bool,"source":"boot|heartbeat|manual_button|remote_command","rssi":n,"firmware":"..."}
//   GET  {BASE}/api/bulb/{id}/command  -> {"bulb_on":bool,"seq":n,...}
static const char* FIRMWARE = "gp-bulb 1.0.0";
static const bool TLS_INSECURE = true;  // https is encrypted but the certificate is NOT verified (demo setting)

// ---- timing ----------------------------------------------------------------------------------------------------
static const unsigned long DEBOUNCE_MS = 50;
static const unsigned long HEARTBEAT_MS = 10000;
static const unsigned long POLL_MS = 3000;
static const unsigned long WIFI_RETRY_MS = 10000;
static const unsigned long HTTP_TIMEOUT_MS = 4000;
static const unsigned long MANUAL_HOLD_MS = 2500;  // ignore backend commands this long after a button press

// ---- state -----------------------------------------------------------------------------------------------------
static bool bulbOn = false;
static int lastRawReading = HIGH;
static int stableButtonState = HIGH;
static unsigned long lastChangeTime = 0;
static unsigned long lastHeartbeat = 0, lastPoll = 0, lastWifiTry = 0, lastManualPress = 0;
static bool everManual = false;

static void applyRelay(bool on) {
  bulbOn = on;
  const bool level = RELAY_ACTIVE_LOW ? !on : on;  // HIGH/LOW to write
  digitalWrite(RELAY_PIN, level ? HIGH : LOW);
  Serial.printf("[relay] bulb %s\n", on ? "ON" : "OFF");
}

static int httpCall(bool post, const String& path, const String& body, String& out) {
  WiFiClient plain;
  WiFiClientSecure secure;
  HTTPClient http;
  const String url = String(BACKEND_BASE_URL) + path;
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);
  bool ok;
  if (url.startsWith("https://")) {
    if (TLS_INSECURE) secure.setInsecure();
    ok = http.begin(secure, url);
  } else {
    ok = http.begin(plain, url);
  }
  if (!ok) return -1;
  if (strlen(DEVICE_API_KEY) > 0) http.addHeader("X-Device-Key", DEVICE_API_KEY);
  int code;
  if (post) {
    http.addHeader("Content-Type", "application/json");
    code = http.POST(body);
  } else {
    code = http.GET();
  }
  out = code > 0 ? http.getString() : http.errorToString(code);
  http.end();
  return code;
}

static void postStatus(const char* source) {
  if (WiFi.status() != WL_CONNECTED) return;
  String body = String("{\"bulb_on\":") + (bulbOn ? "true" : "false") + ",\"source\":\"" + source + "\",\"rssi\":" +
                String(WiFi.RSSI()) + ",\"firmware\":\"" + FIRMWARE + "\"}";
  String resp;
  const int code = httpCall(true, String("/api/bulb/") + DEVICE_ID + "/status", body, resp);
  Serial.printf("[net] POST status (%s) -> %d\n", source, code);
  if (code == 401) Serial.println("[net] 401: DEVICE_API_KEY in config.h does not match the backend");
  else if (code < 0 || code >= 400) Serial.println(resp);
}

static void pollCommand() {
  if (WiFi.status() != WL_CONNECTED) return;
  String resp;
  const int code = httpCall(false, String("/api/bulb/") + DEVICE_ID + "/command", "", resp);
  if (code != 200) {
    Serial.printf("[net] GET command failed: %d\n", code);
    return;
  }
  if (everManual && millis() - lastManualPress < MANUAL_HOLD_MS) return;  // a fresh button press wins over a stale reply
  if (resp.indexOf("\"bulb_on\":true") >= 0 && !bulbOn) {
    applyRelay(true);
    postStatus("remote_command");
  } else if (resp.indexOf("\"bulb_on\":false") >= 0 && bulbOn) {
    applyRelay(false);
    postStatus("remote_command");
  }
}

static void handleButton() {
  const int raw = digitalRead(BUTTON_PIN);
  if (raw != lastRawReading) {
    lastChangeTime = millis();
    lastRawReading = raw;
  }
  if ((millis() - lastChangeTime) > DEBOUNCE_MS && raw != stableButtonState) {
    stableButtonState = raw;
    if (stableButtonState == LOW) {  // pressed (INPUT_PULLUP)
      lastManualPress = millis();
      everManual = true;
      applyRelay(!bulbOn);  // local control never waits for the network
      postStatus("manual_button");
    }
  }
}

static void connectWiFi(bool blocking) {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("[wifi] connecting to %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  const unsigned long start = millis();
  while (blocking && WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) Serial.printf("[wifi] connected, IP %s\n", WiFi.localIP().toString().c_str());
  else if (blocking) Serial.println("[wifi] not connected yet: local button control still works, retrying in the background");
}

void setup() {
  Serial.begin(115200);
  delay(500);
  pinMode(RELAY_PIN, OUTPUT);
  applyRelay(false);  // safe boot: OFF before anything else runs
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  Serial.printf("\n=== %s | device %s | relay GPIO%d (%s) | button GPIO%d ===\n", FIRMWARE, DEVICE_ID, RELAY_PIN,
                RELAY_ACTIVE_LOW ? "active-LOW" : "active-HIGH", BUTTON_PIN);
  connectWiFi(true);
  postStatus("boot");
  lastHeartbeat = lastPoll = millis();
}

void loop() {
  handleButton();  // first, every pass: the button must stay responsive
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - lastWifiTry > WIFI_RETRY_MS) {
      lastWifiTry = millis();
      connectWiFi(false);
    }
    return;
  }
  if (millis() - lastPoll >= POLL_MS) {
    lastPoll = millis();
    pollCommand();
  }
  if (millis() - lastHeartbeat >= HEARTBEAT_MS) {
    lastHeartbeat = millis();
    postStatus("heartbeat");
  }
}
