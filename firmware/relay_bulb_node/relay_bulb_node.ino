#include <WiFi.h>
#include <HTTPClient.h>

#define RELAY_PIN 25
#define BUTTON_PIN 27

const char* WIFI_SSID = "YOUR_WIFI_NAME";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";

const char* POST_URL = "YOUR_POST_URL";
const char* GET_URL  = "YOUR_GET_URL";

String deviceId = "bulb-01";

bool bulbOn = false;

// debounce
int lastRawReading = HIGH;
int stableButtonState = HIGH;
unsigned long lastChangeTime = 0;
const unsigned long debounceDelay = 50;

// timers
unsigned long lastStatusPost = 0;
unsigned long lastCommandPoll = 0;
const unsigned long statusPostInterval = 10000;   // every 10 sec
const unsigned long commandPollInterval = 3000;   // every 3 sec

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.print("Connecting to WiFi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  unsigned long startAttempt = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startAttempt < 20000) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("WiFi connected. IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("WiFi connect failed");
  }
}

void setRelayState(bool on, bool notifyServer = true) {
  bulbOn = on;

  // active-LOW relay
  digitalWrite(RELAY_PIN, bulbOn ? LOW : HIGH);

  Serial.print("Bulb: ");
  Serial.println(bulbOn ? "ON" : "OFF");

  if (notifyServer) {
    postStatus("state_change");
  }
}

void postStatus(String source) {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  WiFiClient client;

  http.begin(client, POST_URL);
  http.addHeader("Content-Type", "application/json");

  String payload = "{";
  payload += "\"device_id\":\"" + deviceId + "\",";
  payload += "\"bulb_on\":" + String(bulbOn ? "true" : "false") + ",";
  payload += "\"source\":\"" + source + "\",";
  payload += "\"rssi\":" + String(WiFi.RSSI());
  payload += "}";

  int httpCode = http.POST(payload);
  String response = http.getString();

  Serial.print("POST code: ");
  Serial.println(httpCode);
  Serial.print("POST response: ");
  Serial.println(response);

  http.end();
}

void pollCommand() {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  WiFiClient client;

  http.begin(client, GET_URL);
  int httpCode = http.GET();

  if (httpCode > 0) {
    String response = http.getString();

    Serial.print("GET code: ");
    Serial.println(httpCode);
    Serial.print("GET response: ");
    Serial.println(response);

    // Expected response examples:
    // {"bulb_on":true}
    // {"bulb_on":false}

    if (response.indexOf("\"bulb_on\":true") >= 0 && !bulbOn) {
      setRelayState(true, false);
      postStatus("remote_command");
    }
    else if (response.indexOf("\"bulb_on\":false") >= 0 && bulbOn) {
      setRelayState(false, false);
      postStatus("remote_command");
    }
  } else {
    Serial.print("GET failed, code: ");
    Serial.println(httpCode);
  }

  http.end();
}

void handleButton() {
  int rawReading = digitalRead(BUTTON_PIN);

  if (rawReading != lastRawReading) {
    lastChangeTime = millis();
    lastRawReading = rawReading;
  }

  bool settled = (millis() - lastChangeTime) > debounceDelay;

  if (settled && rawReading != stableButtonState) {
    stableButtonState = rawReading;

    if (stableButtonState == LOW) {
      setRelayState(!bulbOn, true);
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(RELAY_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  // relay OFF at startup
  digitalWrite(RELAY_PIN, HIGH);

  Serial.println("System boot");
  Serial.println("Relay pin: GPIO25");
  Serial.println("Button pin: GPIO27");

  connectWiFi();
  setRelayState(false, false);
  postStatus("boot");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  handleButton();

  if (millis() - lastStatusPost >= statusPostInterval) {
    lastStatusPost = millis();
    postStatus("heartbeat");
  }

  if (millis() - lastCommandPoll >= commandPollInterval) {
    lastCommandPoll = millis();
    pollCommand();
  }
}
