#include "web_server.h"
#include <Arduino.h>
#include <SPIFFS.h>
#include <AsyncTCP.h>
#include <ESPAsyncWebServer.h>
#include <ArduinoJson.h>
#include "system_mode.h"

// mirror of pins used in main.cpp
static constexpr uint8_t PIN_LED_WD_LOCAL = 33; // lamp
// We'll control pump and valves via shared variables declared in main.cpp
extern volatile bool pumpOn;
// extern volatile bool valveOn[3];
extern volatile float airTemp;
extern volatile float airHum;
extern volatile float forecastTemp;
extern volatile float forecastHum;
extern volatile float forecast3Temp;
extern volatile float forecast3Hum;
extern volatile float forecastLight;
extern volatile float soilPct[3];
extern volatile bool rainSoon;
extern volatile uint64_t nextIrrigationMs;
void applyOutputs();

AsyncWebServer server(80);

// Use state helpers for atomic snapshot and expiry handling
extern void populateStatus(JsonDocument &doc);
extern void setPumpWithExpiry(bool on, uint32_t expiryMs);
extern void checkAndExpireState();

static void handleStatus(AsyncWebServerRequest *request)
{
  // expire any manual-controlled outputs before reporting
  checkAndExpireState();

  StaticJsonDocument<1024> doc;
  populateStatus(doc);

  String out;
  serializeJson(doc, out);
  request->send(200, "application/json", out);
}

static void handleControl(AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total)
{
  StaticJsonDocument<512> doc;
  DeserializationError err = deserializeJson(doc, data, len);
  if (err)
  {
    request->send(400, "application/json", "{\"error\":\"invalid json\"}");
    return;
  }
  if (doc.containsKey("pump"))
  {
    bool on = doc["pump"].as<int>() ? true : false;
    uint32_t expiry = 0;
    if (doc.containsKey("durationPump") && doc["durationPump"].as<int>() > 0)
    {
      expiry = (uint32_t)millis() + (uint32_t)(doc["durationPump"].as<int>() * 1000);
    }
    else if (doc.containsKey("manual") && doc["manual"].as<int>() == 0)
    {
      expiry = 0;
    }
    setPumpWithExpiry(on, expiry);
  }
  // valves removed: ignore any valve entries
  if (doc.containsKey("light"))
  {
    int l = doc["light"].as<int>();
    digitalWrite(PIN_LED_WD_LOCAL, l ? HIGH : LOW);
  }
  applyOutputs();
  request->send(200, "application/json", "{\"ok\":1}");
}

void initWebServer()
{
  if (!SPIFFS.begin(true))
  {
    Serial.println("[web] SPIFFS begin failed");
  }

  // Serve static files from /www
  server.serveStatic("/", SPIFFS, "/www/").setDefaultFile("index.html");

  server.on("/api/status", HTTP_GET, [](AsyncWebServerRequest *r){ handleStatus(r); });

  server.on("/api/control", HTTP_POST, [](AsyncWebServerRequest *r){
    // body handler will be called separately
  }, NULL, handleControl);

  server.begin();
  Serial.println("[web] server started on port 80");
}

// expiry handled by state helpers



