// Copy this file to config.h (which is git-ignored) and fill it in. Never commit config.h: it holds secrets.
#pragma once

// ---- Wi-Fi ---------------------------------------------------------------------------------------------
#define WIFI_SSID "YOUR_WIFI_NAME"
#define WIFI_PASS "YOUR_WIFI_PASSWORD"

// ---- backend -------------------------------------------------------------------------------------------
// Deployed: "https://gridpulse-api-yjd1.onrender.com"     Local dev: "http://<laptop-ip>:8000"
#define BACKEND_BASE_URL "https://gridpulse-api-yjd1.onrender.com"
// Must equal the backend's DEVICE_API_KEY (Render dashboard > Environment). Empty = backend has no key.
#define DEVICE_API_KEY ""
// Lower-case letters, digits, - and _ (2 to 40 chars). One id per physical node.
#define DEVICE_ID "bulb-01"

// ---- hardware (verified wiring) ------------------------------------------------------------------------
#define RELAY_PIN 25
#define BUTTON_PIN 27
// Most 5 V relay modules are active-LOW (IN low = relay energised). Set to 0 if yours switches on HIGH.
#define RELAY_ACTIVE_LOW 1
