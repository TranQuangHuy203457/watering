#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>
#include <ArduinoJson.h>
#include "SPIFFS.h"
#include <cstdarg>
#include "web_server.h"
#include "state.h"

// Pin map
static constexpr uint8_t PIN_SDA = 21;
static constexpr uint8_t PIN_SCL = 22;
static constexpr uint8_t PIN_DHT = 19;
static constexpr uint8_t PIN_RELAY_PUMP = 25;
static constexpr uint8_t PIN_RELAY_V1 = 26;
static constexpr uint8_t PIN_RELAY_V2 = 27;
static constexpr uint8_t PIN_RELAY_V3 = 14;
static constexpr uint8_t PIN_LED_WD = 33;
static constexpr uint8_t PIN_SOIL1 = 34;
static constexpr uint8_t PIN_SOIL2 = 35;
static constexpr uint8_t PIN_SOIL3 = 32;

// WiFi and endpoints (fill in your values)
static const char *WIFI_SSID = "";
static const char *WIFI_PASS = "";

#ifndef WEATHER_API_KEY
static const char *WEATHER_API_KEY_STR = "";
#else
#ifndef STR_HELPER
#define STR_HELPER(x) #x
#endif
#ifndef STR
#define STR(x) STR_HELPER(x)
#endif
static const char *WEATHER_API_KEY_STR = STR(WEATHER_API_KEY);
#endif

// Supabase settings: provide at build time via
// -DSUPABASE_URL="https://<project>.supabase.co" -DSUPABASE_KEY="your_key"
#ifndef SUPABASE_URL
static const char *SUPABASE_URL_STR = "";
#else
static const char *SUPABASE_URL_STR = STR(SUPABASE_URL);
#endif

#ifndef SUPABASE_KEY
static const char *SUPABASE_KEY_STR = "";
#else
static const char *SUPABASE_KEY_STR = STR(SUPABASE_KEY);
#endif

// LCD
LiquidCrystal_I2C lcd(0x27, 20, 4);

// DHT
#define DHTTYPE DHT11
static DHT dht(PIN_DHT, DHTTYPE);

// Shared state
volatile float soilPct[3] = {0};
volatile float airTemp = 0;
volatile float airHum = 0;
// Forecasted weather from remote API
volatile float forecastTemp = 0;
volatile float forecastHum = 0;
volatile float forecastLight = 0; // proxy: visibility or uvIndex
// Forecast 3 hours ahead (when available)
volatile float forecast3Temp = 0;
volatile float forecast3Hum = 0;
volatile float forecast3Light = 0;
volatile bool pumpOn = false;
volatile bool rainSoon = false;
volatile uint64_t nextIrrigationMs = 0;

// share system mode with other translation units
#include "system_mode.h"
volatile SystemMode systemMode = MODE_NORMAL;

// Irrigation runtime state (moved up so DisplayTask can reference it)
struct IrrState { bool active; uint32_t startMs; int plant; };
static IrrState irr = {false, 0, 0};


// Optional feedback pins: set to -1 if not wired.
static constexpr int PIN_FEEDBACK_PUMP = -1;
static constexpr int PIN_FEEDBACK_V1 = -1;
static constexpr int PIN_FEEDBACK_V2 = -1;
static constexpr int PIN_FEEDBACK_V3 = -1;
static constexpr int PIN_FEEDBACK_LED = -1;

// Device health state (assume OK until proven otherwise)
volatile bool pumpOk = true;
volatile bool ledOk = true;
// pump expiry for manual control (managed via state API)
volatile uint32_t pumpExpiryMs = 0;

// Config
static constexpr float SOIL_ON = 60.0f;
static constexpr float SOIL_OFF = 70.0f;
static constexpr uint32_t IRRIG_MS = static_cast<uint32_t>(2.3f * 3600.0f * 1000.0f); // 2.3 h
static constexpr uint64_t SCHEDULE_MS = static_cast<uint64_t>(5ULL * 7ULL * 24ULL * 3600ULL * 1000ULL); // 5 weeks

// ADC calibration window for capacitive soil sensor (adjust after calibration)
static constexpr int ADC_WET = 800;   // value when soil fully wet
static constexpr int ADC_DRY = 2400;  // value when soil dry

// Instrumentation / scheduling measurement
#define MEASURE_DEADLINES 1
static constexpr uint32_t DL_SOIL_MS = 500;
static constexpr uint32_t DL_DHT_MS = 2000;
static constexpr uint32_t DL_SWITCH_MS = 500;
static constexpr uint32_t DL_ERROR_MS = 5000;
static constexpr uint32_t DL_WEATHER_MS = 60000;
static constexpr uint32_t DL_NETWORK_MS = 2000;
static constexpr uint32_t DL_DISPLAY_MS = 1000;
static constexpr uint32_t DL_WATCHDOG_MS = 5000;
static constexpr uint32_t DL_LOG_MS = 5000;

// Network throttling / admission control
static constexpr uint32_t NETWORK_MIN_SEND_INTERVAL_MS = 1000; // min time between sends (1s period)
static constexpr int NETWORK_MAX_RETRIES = 3;

static void logTask(const char *name, uint32_t start, uint32_t duration, uint32_t deadline)
{
#if MEASURE_DEADLINES
  bool miss = duration > deadline;
  Serial.printf("[%ums] %s end duration=%ums deadline=%ums %s\n", start + duration, name, duration, deadline, miss ? "MISS" : "HIT");
#endif
}

// Forward decl
void applyOutputs();
void stopIrrigation();
void startIrrigation(int plant, uint32_t durationMs = IRRIG_MS);
static void reportTaskStart();

// State mutex for safe snapshotting from web server
static SemaphoreHandle_t stateMutex = nullptr;

void initStateLock()
{
  if (stateMutex == nullptr)
  {
    stateMutex = xSemaphoreCreateMutex();
  }
}

void populateStatus(JsonDocument &doc)
{
  if (stateMutex) xSemaphoreTake(stateMutex, portMAX_DELAY);
  doc["airTemp"] = airTemp;
  doc["airHum"] = airHum;
  JsonArray s = doc.createNestedArray("soil");
  s.add(soilPct[0]); s.add(soilPct[1]); s.add(soilPct[2]);
  doc["pumpOn"] = pumpOn ? 1 : 0;
  doc["forecastTemp"] = forecastTemp;
  doc["forecastHum"] = forecastHum;
  doc["forecast3Temp"] = forecast3Temp;
  doc["forecast3Hum"] = forecast3Hum;
  doc["forecastLight"] = forecastLight;
  doc["rainSoon"] = rainSoon ? 1 : 0;
  doc["nextIrrigationMs"] = (uint32_t)(nextIrrigationMs / 1000);
  doc["mode"] = (int)systemMode;
  if (stateMutex) xSemaphoreGive(stateMutex);
}

void setPumpWithExpiry(bool on, uint32_t expiryMs)
{
  if (stateMutex) xSemaphoreTake(stateMutex, portMAX_DELAY);
  pumpOn = on;
  pumpExpiryMs = expiryMs;
  if (stateMutex) xSemaphoreGive(stateMutex);
}

void checkAndExpireState()
{
  uint32_t now = (uint32_t)millis();
  if (stateMutex) xSemaphoreTake(stateMutex, portMAX_DELAY);
  if (pumpExpiryMs != 0 && now >= pumpExpiryMs)
  {
    pumpOn = false;
    pumpExpiryMs = 0;
  }
  if (stateMutex) xSemaphoreGive(stateMutex);
}

void getStateSnapshot(StateSnapshot &s)
{
  if (stateMutex) xSemaphoreTake(stateMutex, portMAX_DELAY);
  for (int i = 0; i < 3; ++i) s.soil[i] = soilPct[i];
  s.airTemp = airTemp;
  s.airHum = airHum;
  s.forecastTemp = forecastTemp;
  s.forecastHum = forecastHum;
  s.forecast3Temp = forecast3Temp;
  s.forecast3Hum = forecast3Hum;
  s.forecastLight = forecastLight;
  s.rainSoon = rainSoon;
  s.pumpOn = pumpOn;
  s.pumpOk = pumpOk;
  s.ledOk = ledOk;
  s.nextIrrigationMs = nextIrrigationMs;
  s.mode = systemMode;
  s.irrActive = irr.active;
  s.irrPlant = irr.plant;
  s.irrStartMs = irr.startMs;
  if (stateMutex) xSemaphoreGive(stateMutex);
}

void setNextIrrigationMs(uint64_t v)
{
  if (stateMutex) xSemaphoreTake(stateMutex, portMAX_DELAY);
  nextIrrigationMs = v;
  if (stateMutex) xSemaphoreGive(stateMutex);
}

// Utils
float mapSoilToPct(int raw)
{
  long pct = map(raw, ADC_WET, ADC_DRY, 100, 0);
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  return static_cast<float>(pct);
}

float readSoilPct(gpio_num_t pin)
{
  const int samples = 5;
  int vals[samples];
  for (int i = 0; i < samples; ++i)
  {
    vals[i] = analogRead(pin);
    delay(5);
  }
  for (int i = 0; i < samples; ++i)
  {
    for (int j = i + 1; j < samples; ++j)
    {
      if (vals[j] < vals[i])
      {
        int t = vals[i];
        vals[i] = vals[j];
        vals[j] = t;
      }
    }
  }
  int median = vals[samples / 2];
  return mapSoilToPct(median);
}

// Tasks
void SoilTask(void *)
{
  const gpio_num_t pins[3] = {static_cast<gpio_num_t>(PIN_SOIL1), static_cast<gpio_num_t>(PIN_SOIL2), static_cast<gpio_num_t>(PIN_SOIL3)};
  for (;;)
  {
    uint32_t t0 = millis();
    reportTaskStart();
    float tmp[3];
    for (int i = 0; i < 3; ++i) tmp[i] = readSoilPct(pins[i]);
    if (stateMutex) xSemaphoreTake(stateMutex, portMAX_DELAY);
    for (int i = 0; i < 3; ++i) soilPct[i] = tmp[i];
    if (stateMutex) xSemaphoreGive(stateMutex);
    uint32_t t1 = millis();
    logTask("SoilTask", t0, t1 - t0, DL_SOIL_MS);
    // 500ms period per task model
    vTaskDelay(pdMS_TO_TICKS(500));
  }
}

void DHTTask(void *)
{
  for (;;)
  {
    uint32_t t0 = millis();
    reportTaskStart();
    float h = dht.readHumidity();
    float t = dht.readTemperature();
    if (!isnan(h) && !isnan(t))
    {
      if (stateMutex) xSemaphoreTake(stateMutex, portMAX_DELAY);
      airHum = h;
      airTemp = t;
      if (stateMutex) xSemaphoreGive(stateMutex);
    }
    else
    {
      uint32_t t1 = millis();
      logTask("DHTTask", t0, t1 - t0, DL_DHT_MS);
      vTaskDelay(pdMS_TO_TICKS(500));
      continue;
    }
    uint32_t t1 = millis();
    logTask("DHTTask", t0, t1 - t0, DL_DHT_MS);
    vTaskDelay(pdMS_TO_TICKS(2000));
  }
}

void WeatherTask(void *)
{
  HTTPClient http;
  for (;;)
  {
    uint32_t t0 = millis();
    reportTaskStart();
    if (strlen(WEATHER_API_KEY_STR) == 0)
    {
      // No API key provided at compile time; skip real calls.
      uint32_t t1 = millis();
      logTask("WeatherTask-skip-key", t0, t1 - t0, DL_WEATHER_MS);
      vTaskDelay(pdMS_TO_TICKS(3600 * 1000));
      continue;
    }

    if (WiFi.status() == WL_CONNECTED)
    {
      String url = String("https://api.tomorrow.io/v4/weather/forecast?location=Hanoi&apikey=") + WEATHER_API_KEY_STR + String("&units=metric&timesteps=1");
      http.begin(url);
      int code = http.GET();
      String body = http.getString();
      Serial.printf("[WeatherTask] HTTP %d len=%u\n", code, (unsigned)body.length());
      if (code == 200)
      {
        // Parse JSON to extract forecast values
        // Using ArduinoJson
        const size_t cap = 64 * 1024; // adjust if needed
        DynamicJsonDocument doc(cap);
        DeserializationError err = deserializeJson(doc, body);
        if (!err)
        {
          JsonObject root = doc.as<JsonObject>();
          JsonObject timelines = root["timelines"];
          JsonArray arr;
          if (!timelines.isNull())
          {
            // prefer hourly, then minutely
            if (!timelines["hourly"].isNull()) arr = timelines["hourly"].as<JsonArray>();
            else if (!timelines["minutely"].isNull()) arr = timelines["minutely"].as<JsonArray>();
          }
          if (!arr.isNull() && arr.size() > 0)
          {
            JsonObject v = arr[0]["values"];
            if (!v.isNull())
            {
              // compute new values locally to avoid partial updates
              float newForecastTemp = forecastTemp;
              float newForecastHum = forecastHum;
              float newForecastLight = forecastLight;
              bool willRain = false;
              if (v.containsKey("temperature")) newForecastTemp = v["temperature"].as<float>();
              if (v.containsKey("humidity")) newForecastHum = v["humidity"].as<float>();
              if (v.containsKey("visibility")) newForecastLight = v["visibility"].as<float>();
              else if (v.containsKey("uvIndex")) newForecastLight = v["uvIndex"].as<float>();
              if (v.containsKey("precipitationProbability") && v["precipitationProbability"].as<int>() > 20) willRain = true;
              if (v.containsKey("rainIntensity") && v["rainIntensity"].as<float>() > 0.1f) willRain = true;
              if (v.containsKey("rainAccumulation") && v["rainAccumulation"].as<float>() > 0.0f) willRain = true;

              float newForecast3Temp = forecast3Temp;
              float newForecast3Hum = forecast3Hum;
              float newForecast3Light = forecast3Light;
              if (arr.size() > 1)
              {
                JsonObject v3 = arr[1]["values"];
                if (!v3.isNull())
                {
                  if (v3.containsKey("temperature")) newForecast3Temp = v3["temperature"].as<float>();
                  if (v3.containsKey("humidity")) newForecast3Hum = v3["humidity"].as<float>();
                  if (v3.containsKey("visibility")) newForecast3Light = v3["visibility"].as<float>();
                  else if (v3.containsKey("uvIndex")) newForecast3Light = v3["uvIndex"].as<float>();
                }
              }

              // commit atomically
              if (stateMutex) xSemaphoreTake(stateMutex, portMAX_DELAY);
              forecastTemp = newForecastTemp;
              forecastHum = newForecastHum;
              forecastLight = newForecastLight;
              rainSoon = willRain;
              forecast3Temp = newForecast3Temp;
              forecast3Hum = newForecast3Hum;
              forecast3Light = newForecast3Light;
              if (stateMutex) xSemaphoreGive(stateMutex);

              Serial.printf("[WeatherTask] forecastT=%.1f H=%.0f light=%.2f -> +3h T=%.1f H=%.0f L=%.2f rain=%d\n", newForecastTemp, newForecastHum, newForecastLight, newForecast3Temp, newForecast3Hum, newForecast3Light, willRain ? 1 : 0);
            }
          }
        }
        else
        {
          Serial.print("WeatherTask JSON parse error: ");
          Serial.println(err.c_str());
        }
      }
      else
      {
        // Log body for debugging (e.g., 401 Unauthorized)
        Serial.println(body);
      }
      http.end();
    }

    uint32_t t1 = millis();
    logTask("WeatherTask", t0, t1 - t0, DL_WEATHER_MS);
    // 60s period per task model
    vTaskDelay(pdMS_TO_TICKS(60000));
  }
}

void NetworkTask(void *)
{
  HTTPClient http;
  static uint32_t lastNetworkSend = 0;
  static int retries = 0;
  for (;;)
  {
    uint32_t t0 = millis();
    reportTaskStart();
    if (WiFi.status() == WL_CONNECTED)
    {
      // Admission control: ensure we don't send more often than allowed
      uint32_t now = millis();
      if (now - lastNetworkSend < NETWORK_MIN_SEND_INTERVAL_MS)
      {
        // skip this cycle
        uint32_t t1 = millis();
        logTask("NetworkTask-skip", t0, t1 - t0, DL_NETWORK_MS);
      }
      else
      {
           // Build payload from an atomic snapshot to avoid tearing
           StaticJsonDocument<512> doc;
           populateStatus(doc);
           // include valves placeholder
           doc.createNestedArray("valves");
           String payload;
           serializeJson(doc, payload);

        // Only send telemetry to Supabase. If not configured, skip sending.
        int code = 0;
        if (strlen(SUPABASE_URL_STR) > 0 && strlen(SUPABASE_KEY_STR) > 0)
        {
          String endpoint = String(SUPABASE_URL_STR) + String("/rest/v1/telemetry");
          http.begin(endpoint);
          http.addHeader("Content-Type", "application/json");
          http.addHeader("apikey", SUPABASE_KEY_STR);
          http.addHeader("Authorization", String("Bearer ") + SUPABASE_KEY_STR);
          http.addHeader("Prefer", "return=representation");
          code = http.POST(payload);
          String resp = http.getString();
          Serial.printf("[NetworkTask] Supabase %d len=%u\n", code, (unsigned)resp.length());
          http.end();
          lastNetworkSend = now;
          if (code != 200 && retries < NETWORK_MAX_RETRIES)
          {
            retries++;
          }
          else
          {
            retries = 0;
          }
        }
        else
        {
          Serial.println("[NetworkTask] Supabase not configured, skipping telemetry send");
          // consider as success for retry logic and advance last send time
          lastNetworkSend = now;
          retries = 0;
        }
        uint32_t t1 = millis();
        logTask("NetworkTask-send", t0, t1 - t0, DL_NETWORK_MS);
      }
    }
    // 1s period per task model (deadline 2s)
    vTaskDelay(pdMS_TO_TICKS(1000));
  }
}

void DisplayTask(void *)
{
  for (;;)
  {
    uint32_t t0 = millis();
    reportTaskStart();
    // Obtain atomic snapshot for display
    StaticJsonDocument<512> st;
    populateStatus(st);
    bool ledState = digitalRead(PIN_LED_WD) == HIGH;
    float dispAirT = st["airTemp"]; 
    float dispAirH = st["airHum"];
    float dispF3T = st["forecast3Temp"]; 
    float dispF3H = st["forecast3Hum"];
    float dispFL = st["forecastLight"];
    bool dispPump = st["pumpOn"]; 
    uint32_t dispNext = (uint32_t)st["nextIrrigationMs"];
    JsonArray sarr = st["soil"].as<JsonArray>();
    float s0 = sarr.size() > 0 ? sarr[0].as<float>() : 0;
    float s1 = sarr.size() > 1 ? sarr[1].as<float>() : 0;
    float s2 = sarr.size() > 2 ? sarr[2].as<float>() : 0;

    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("T:"); lcd.print(dispAirT, 1); lcd.print("C H:"); lcd.print(dispAirH, 0); lcd.print("%   ");
    lcd.setCursor(0, 1);
    lcd.print("+3h T:"); lcd.print(dispF3T, 1); lcd.print("C H:"); lcd.print((int)dispF3H); lcd.print("%   ");
    lcd.setCursor(0, 2);
    lcd.print("L:"); lcd.print((int)dispFL); lcd.print("   ");
    lcd.setCursor(0, 3);
    lcd.print("Pump:"); lcd.print(dispPump ? "ON" : "OFF"); lcd.print(" ");
    lcd.print("LED:"); lcd.print(ledState ? "ON" : "OFF");
    // Show first page ~0.5s
    vTaskDelay(pdMS_TO_TICKS(500));

    // show soil and active irrigation zone (use snapshot for soil and irr)
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("S1:"); lcd.print(s0, 0); lcd.print("% ");
    lcd.setCursor(10, 0);
    // irrigation info read directly (small window) - use snapshot fields
    lcd.print("Zone:"); lcd.print(st["mode"].as<int>() == 0 ? (st["mode"].as<int>() , -1) : -1);
    lcd.setCursor(0, 1);
    lcd.print("S2:"); lcd.print(s1, 0); lcd.print("% ");
    lcd.setCursor(0, 2);
    lcd.print("S3:"); lcd.print(s2, 0); lcd.print("% ");
    lcd.setCursor(0, 3);
    lcd.print("Next:"); lcd.print((uint32_t)dispNext); lcd.print("s");
    uint32_t t1 = millis();
    logTask("DisplayTask", t0, t1 - t0, DL_DISPLAY_MS);
    // Show second page ~0.5s -> overall ~1s period
    vTaskDelay(pdMS_TO_TICKS(500));
  }
}

// Background async logging task (soft RT, very low priority)
void LogTask(void *)
{
  for (;;)
  {
    uint32_t t0 = millis();
    reportTaskStart();
    // Simulate asynchronous log flush (~20ms worst case)
    delay(20);
    uint32_t t1 = millis();
    logTask("LogTask", t0, t1 - t0, DL_LOG_MS);
    vTaskDelay(pdMS_TO_TICKS(5000));
  }
}

// --- EDF scheduler support -------------------------------------------------
struct TaskInfo
{
  const char *name;
  TaskHandle_t handle;
  uint32_t periodMs; // relative deadline / period
  uint32_t lastStartMs; // last time the task began work
};

// Forward-declared task handles (filled in at creation)
static TaskHandle_t hSoil = nullptr;
static TaskHandle_t hDHT = nullptr;
static TaskHandle_t hSwitch = nullptr;
static TaskHandle_t hWeather = nullptr;
static TaskHandle_t hNetwork = nullptr;
static TaskHandle_t hDisplay = nullptr;
static TaskHandle_t hLog = nullptr;

// Small fixed array of managed tasks: exactly the 7 application tasks in the model
static TaskInfo managedTasks[7];
static const int managedTaskCount = 7;

// Called by tasks to report they started a new activation
static void reportTaskStart()
{
  TaskHandle_t self = xTaskGetCurrentTaskHandle();
  uint32_t now = millis();
  for (int i = 0; i < managedTaskCount; ++i)
  {
    if (managedTasks[i].handle == self)
    {
      managedTasks[i].lastStartMs = now;
      if (managedTasks[i].name)
      {
        Serial.printf("[EDF] task start: %s t=%u\\n", managedTasks[i].name, (unsigned)now);
      }
      break;
    }
  }
}

// Append formatted log to SPIFFS file
static void fileLog(const char *fmt, ...)
{
  char buf[256];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);

  // Mirror to Serial for immediate debugging
  Serial.print("[LOGFILE] ");
  Serial.println(buf);


  // Rotate if too large
  const size_t MAX_LOG = 64 * 1024;
  if (SPIFFS.exists("/edf_log.txt"))
  {
    File ff = SPIFFS.open("/edf_log.txt", FILE_READ);
    if (ff)
    {
      size_t sz = ff.size();
      ff.close();
      if (sz > MAX_LOG)
      {
        SPIFFS.remove("/edf_log.bak");
        SPIFFS.rename("/edf_log.txt", "/edf_log.bak");
      }
    }
  }

  File f = SPIFFS.open("/edf_log.txt", FILE_APPEND);
  if (!f)
  {
    Serial.println("[LOGFILE] open failed");
    return;
  }
  f.println(buf);
  f.close();
}

// Implement setSystemMode (declared in system_mode.h)
void setSystemMode(SystemMode m)
{
  if (systemMode == m) return;
  systemMode = m;
  if (m == MODE_SAFE)
  {
    nextIrrigationMs = millis() + SCHEDULE_MS; // push schedule
    fileLog("[SYS] entered SAFE mode, deferred irrigation");
  }
  else if (m == MODE_DEGRADED)
  {
    // when degraded, be conservative: delay next irrigation by 1 hour
    nextIrrigationMs = millis() + (60UL * 60UL * 1000UL);
    fileLog("[SYS] entered DEGRADED mode, delaying irrigation 1h");
  }
  else
  {
    fileLog("[SYS] back to NORMAL mode");
  }
}

// EDF scheduler task: periodically recomputes absolute deadlines and assigns
// dynamic FreeRTOS priorities so the task with the earliest deadline runs.
void EDFSchedulerTask(void *)
{
  (void)pvTaskGetThreadLocalStoragePointer(NULL, 0);
  for (;;)
  {
    uint32_t now = millis();
    // Simple selection-sort style ranking by absolute deadline
    // Create local copy of indices
    int idx[managedTaskCount];
    for (int i = 0; i < managedTaskCount; ++i) idx[i] = i;
    for (int i = 0; i < managedTaskCount - 1; ++i)
    {
      int best = i;
      uint32_t bestDeadline = managedTasks[idx[best]].lastStartMs + managedTasks[idx[best]].periodMs;
      for (int j = i + 1; j < managedTaskCount; ++j)
      {
        uint32_t d = managedTasks[idx[j]].lastStartMs + managedTasks[idx[j]].periodMs;
        if (d < bestDeadline)
        {
          best = j;
          bestDeadline = d;
        }
      }
      if (best != i) { int t = idx[i]; idx[i] = idx[best]; idx[best] = t; }
    }

    // Assign dynamic priorities: earlier deadline -> higher numeric priority
    // Keep priorities within a small range to avoid colliding with system tasks
    const UBaseType_t maxPrio = configMAX_PRIORITIES > 6 ? 6 : (configMAX_PRIORITIES - 1);
    for (int rank = 0; rank < managedTaskCount; ++rank)
    {
      int i = idx[rank];
      if (managedTasks[i].handle == nullptr) continue;
      // highest priority for rank 0
      UBaseType_t prio = (UBaseType_t)(maxPrio - rank);
      if (prio < 1) prio = 1;
      vTaskPrioritySet(managedTasks[i].handle, prio);
    }

    // Log EDF ordering and remaining times until deadline
    Serial.print("[EDF] schedule: ");
    for (int rank = 0; rank < managedTaskCount; ++rank)
    {
      int i = idx[rank];
      if (managedTasks[i].handle == nullptr) continue;
      uint32_t absDeadline = managedTasks[i].lastStartMs + managedTasks[i].periodMs;
      int32_t timeLeft = (int32_t)(absDeadline - now);
      Serial.printf("%s(rl=%ld) ", managedTasks[i].name ? managedTasks[i].name : "?", (long)timeLeft);
      // append to file buffer
      (void)0;
    }
    Serial.println();

    // Build single line and append to file
    char lbuf[256];
    size_t pos = 0;
    for (int rank = 0; rank < managedTaskCount; ++rank)
    {
      int i = idx[rank];
      if (managedTasks[i].handle == nullptr) continue;
      uint32_t absDeadline = managedTasks[i].lastStartMs + managedTasks[i].periodMs;
      int32_t timeLeft = (int32_t)(absDeadline - now);
      int n = snprintf(lbuf + pos, sizeof(lbuf) - pos, "%s(rl=%ld) ", managedTasks[i].name ? managedTasks[i].name : "?", (long)timeLeft);
      if (n > 0) pos += (size_t)n;
      if (pos >= sizeof(lbuf) - 32) break;
    }
    if (pos == 0) strcpy(lbuf, "(empty)");
    fileLog("[EDF] schedule: %s", lbuf);

    vTaskDelay(pdMS_TO_TICKS(500));
  }
}

static uint32_t irrDurationMs = IRRIG_MS;

void applyOutputs()
{
  // Only drive outputs if the device passed the last health check
  bool pOn;
  bool pOk;
  if (stateMutex) xSemaphoreTake(stateMutex, portMAX_DELAY);
  pOn = pumpOn;
  pOk = pumpOk;
  if (stateMutex) xSemaphoreGive(stateMutex);

  if (pOk)
    digitalWrite(PIN_RELAY_PUMP, pOn ? HIGH : LOW);
  else
    digitalWrite(PIN_RELAY_PUMP, LOW);
  // Valves removed: ensure valve outputs are off
  digitalWrite(PIN_RELAY_V1, LOW);
  digitalWrite(PIN_RELAY_V2, LOW);
  digitalWrite(PIN_RELAY_V3, LOW);
}

void stopIrrigation()
{
  if (stateMutex) xSemaphoreTake(stateMutex, portMAX_DELAY);
  pumpOn = false;
  irr.active = false;
  if (stateMutex) xSemaphoreGive(stateMutex);
  applyOutputs();
}

void startIrrigation(int plant, uint32_t durationMs)
{
  if (stateMutex) xSemaphoreTake(stateMutex, portMAX_DELAY);
  irr = {true, static_cast<uint32_t>(millis()), plant};
  irrDurationMs = durationMs;
  pumpOn = true;
  if (stateMutex) xSemaphoreGive(stateMutex);
  applyOutputs();
}

void SwitchTask(void *)
{
  auto computeSoilOnThreshold = []()->float {
    float thr = SOIL_ON; // base
    // increase threshold when hot and dry
    if (airTemp > 30.0f && airHum < 40.0f) thr += 8.0f;
    // if forecast 3h is predicted hotter and drier, increase further
    if (forecast3Temp > 32.0f && forecast3Hum < 40.0f) thr += 5.0f;
    // if forecast humidity is high, be more conservative (lower threshold)
    if (forecastHum > 80.0f) thr -= 6.0f;
    if (thr < 40.0f) thr = 40.0f;
    if (thr > 95.0f) thr = 95.0f;
    return thr;
  };

  for (;;)
  {
    uint32_t now = millis();
    reportTaskStart();

    StateSnapshot s;
    getStateSnapshot(s);
    if (s.nextIrrigationMs == 0) setNextIrrigationMs(now + SCHEDULE_MS);
    bool scheduleDue = now >= s.nextIrrigationMs;

    // If system is in SAFE mode, be conservative: skip any new irrigation cycles
    if (s.mode == MODE_SAFE)
    {
      if (!s.irrActive)
      {
        // defer schedule and skip
        setNextIrrigationMs(now + SCHEDULE_MS);
      }
      vTaskDelay(pdMS_TO_TICKS(1000));
      continue;
    }

    if (s.irrActive)
    {
      bool timeDone = (now - s.irrStartMs) >= irrDurationMs;
      bool soilDone = s.soil[s.irrPlant] >= SOIL_OFF;
      if (timeDone || soilDone) stopIrrigation();
    }
    else
    {
      // Use forecast and current conditions from snapshot to compute desired soil threshold
      const float desiredThreshold = [&s]()->float {
        float thr = SOIL_ON;
        if (s.airTemp > 30.0f && s.airHum < 40.0f) thr += 8.0f;
        if (s.forecast3Temp > 32.0f && s.forecast3Hum < 40.0f) thr += 5.0f;
        if (s.forecastHum > 80.0f) thr -= 6.0f;
        if (thr < 40.0f) thr = 40.0f;
        if (thr > 95.0f) thr = 95.0f;
        return thr;
      }();

      // Skip if rainSoon or forecast predicts high humidity
      if (scheduleDue && !s.rainSoon && s.forecastHum < 90.0f)
      {
        bool started = false;
        for (int i = 0; i < 3; ++i)
        {
          // only start if device health is OK
          if (!s.pumpOk)
          {
            Serial.println("[SwitchTask] pump not OK, skipping irrigation");
            break;
          }
          if (s.soil[i] < desiredThreshold)
          {
            uint32_t dur = IRRIG_MS;
            if (s.mode == MODE_DEGRADED)
            {
              dur = 5UL * 60UL * 1000UL; // 5 minutes
              Serial.printf("[SwitchTask] DEGRADED: using short irrigation %lu ms\n", (unsigned long)dur);
            }
            startIrrigation(i, dur);
            started = true;
            break;
          }
        }
        if (!started) setNextIrrigationMs(now + SCHEDULE_MS); // nothing to water, push schedule
      }
    }
    vTaskDelay(pdMS_TO_TICKS(1000));
  }
}

// WiFi connect helper
void wifiConnect()
{
  if (!WIFI_SSID || strlen(WIFI_SSID) == 0) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 10000)
  {
    delay(200);
  }
}

void setup()
{
  Serial.begin(115200);
  Wire.begin(PIN_SDA, PIN_SCL);
  lcd.init();
  lcd.backlight();

  // Mount SPIFFS for file logging
  if (!SPIFFS.begin(true))
  {
    Serial.println("[setup] SPIFFS mount failed");
  }
  else
  {
    Serial.println("[setup] SPIFFS mounted");
  }

  pinMode(PIN_RELAY_PUMP, OUTPUT);
  pinMode(PIN_RELAY_V1, OUTPUT);
  pinMode(PIN_RELAY_V2, OUTPUT);
  pinMode(PIN_RELAY_V3, OUTPUT);
  pinMode(PIN_LED_WD, OUTPUT);
  applyOutputs();

  analogReadResolution(12);
  dht.begin();
  wifiConnect();
  // start web UI
  // initialize state mutex before web server handlers use state API
  initStateLock();
  initWebServer();

  xTaskCreatePinnedToCore(SoilTask, "Soil", 4096, nullptr, 4, &hSoil, 1);
  xTaskCreatePinnedToCore(DHTTask, "DHT", 4096, nullptr, 3, &hDHT, 1);
  xTaskCreatePinnedToCore(SwitchTask, "Switch", 4096, nullptr, 5, &hSwitch, 1);
  xTaskCreatePinnedToCore(WeatherTask, "Weather", 4096, nullptr, 1, &hWeather, 0);
  xTaskCreatePinnedToCore(NetworkTask, "Net", 4096, nullptr, 2, &hNetwork, 0);
  xTaskCreatePinnedToCore(DisplayTask, "LCD", 4096, nullptr, 2, &hDisplay, 0);
  // Background async logging task (very low priority)
  xTaskCreatePinnedToCore(LogTask, "Log", 4096, nullptr, 1, &hLog, 0);

  // Populate managedTasks for EDF scheduler
  // Exactly the 7 application tasks from the task model
  managedTasks[0] = {"SwitchTask", hSwitch, DL_SWITCH_MS, millis()};
  managedTasks[1] = {"SoilTask",   hSoil,   DL_SOIL_MS,   millis()};
  managedTasks[2] = {"DHTTask",    hDHT,    DL_DHT_MS,    millis()};
  managedTasks[3] = {"NetworkTask",hNetwork,DL_NETWORK_MS,millis()};
  managedTasks[4] = {"DisplayTask",hDisplay,DL_DISPLAY_MS,millis()};
  managedTasks[5] = {"WeatherTask",hWeather,DL_WEATHER_MS,millis()};
  managedTasks[6] = {"LogTask",    hLog,    DL_LOG_MS,    millis()};

  // Start EDF scheduler task
  xTaskCreatePinnedToCore(EDFSchedulerTask, "EDF", 4096, nullptr, 4, nullptr, 0);
}

void loop()
{
  // Idle; work is in tasks
  vTaskDelay(pdMS_TO_TICKS(1000));
}
