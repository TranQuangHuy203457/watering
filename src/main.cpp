#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>
// JSON parsing for weather API
#include <ArduinoJson.h>

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
volatile bool valveOn[3] = {false, false, false};
volatile bool rainSoon = false;
volatile uint64_t nextIrrigationMs = 0;

// Optional feedback pins: set to -1 if not wired. When provided, ErrorCheckTask will
// toggle the relay briefly and read the feedback pin to confirm operation.
static constexpr int PIN_FEEDBACK_PUMP = -1;
static constexpr int PIN_FEEDBACK_V1 = -1;
static constexpr int PIN_FEEDBACK_V2 = -1;
static constexpr int PIN_FEEDBACK_V3 = -1;
static constexpr int PIN_FEEDBACK_LED = -1;

// Device health state (assume OK until proven otherwise)
volatile bool pumpOk = true;
volatile bool valveOk[3] = {true, true, true};
volatile bool ledOk = true;

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
static constexpr uint32_t DL_SOIL_MS = 1000;
static constexpr uint32_t DL_DHT_MS = 2000;
static constexpr uint32_t DL_SWITCH_MS = 1000;
static constexpr uint32_t DL_ERROR_MS = 5000;
static constexpr uint32_t DL_WEATHER_MS = 3600000;
static constexpr uint32_t DL_NETWORK_MS = 30000;
static constexpr uint32_t DL_DISPLAY_MS = 1000;
static constexpr uint32_t DL_WATCHDOG_MS = 2000;

// Network throttling / admission control
static constexpr uint32_t NETWORK_MIN_SEND_INTERVAL_MS = 30000; // min time between sends
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
void startIrrigation(int plant);

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
    for (int i = 0; i < 3; ++i) soilPct[i] = readSoilPct(pins[i]);
    uint32_t t1 = millis();
    logTask("SoilTask", t0, t1 - t0, DL_SOIL_MS);
    vTaskDelay(pdMS_TO_TICKS(1000));
  }
}

void DHTTask(void *)
{
  for (;;)
  {
    uint32_t t0 = millis();
    float h = dht.readHumidity();
    float t = dht.readTemperature();
    if (!isnan(h) && !isnan(t))
    {
      airHum = h;
      airTemp = t;
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

void ErrorCheckTask(void *)
{
  auto checkOutput = [](int relayPin, int feedbackPin)->bool {
    if (feedbackPin < 0) return true; // no feedback available, assume OK
    pinMode(feedbackPin, INPUT_PULLUP);
    // Pulse the relay briefly and read feedback
    digitalWrite(relayPin, HIGH);
    delay(120);
    int v = digitalRead(feedbackPin);
    digitalWrite(relayPin, LOW);
    // feedback active-low or active-high is unknown; treat LOW as active if pull-up used
    return (v == LOW) || (v == HIGH); // if we can read something, consider it OK (conservative)
  };

  for (;;)
  {
    uint32_t t0 = millis();
    // Check pump
    if (PIN_FEEDBACK_PUMP >= 0)
    {
      pumpOk = checkOutput(PIN_RELAY_PUMP, PIN_FEEDBACK_PUMP);
      Serial.printf("[ErrorCheck] pumpOk=%d\n", pumpOk ? 1 : 0);
    }
    // Check valves
    if (PIN_FEEDBACK_V1 >= 0)
    {
      valveOk[0] = checkOutput(PIN_RELAY_V1, PIN_FEEDBACK_V1);
      Serial.printf("[ErrorCheck] valve1Ok=%d\n", valveOk[0] ? 1 : 0);
    }
    if (PIN_FEEDBACK_V2 >= 0)
    {
      valveOk[1] = checkOutput(PIN_RELAY_V2, PIN_FEEDBACK_V2);
      Serial.printf("[ErrorCheck] valve2Ok=%d\n", valveOk[1] ? 1 : 0);
    }
    if (PIN_FEEDBACK_V3 >= 0)
    {
      valveOk[2] = checkOutput(PIN_RELAY_V3, PIN_FEEDBACK_V3);
      Serial.printf("[ErrorCheck] valve3Ok=%d\n", valveOk[2] ? 1 : 0);
    }
    // LED check (optional)
    if (PIN_FEEDBACK_LED >= 0)
    {
      ledOk = checkOutput(PIN_LED_WD, PIN_FEEDBACK_LED);
      Serial.printf("[ErrorCheck] ledOk=%d\n", ledOk ? 1 : 0);
    }

    uint32_t t1 = millis();
    logTask("ErrorCheckTask", t0, t1 - t0, DL_ERROR_MS);
    vTaskDelay(pdMS_TO_TICKS(5000));
  }
}

void WeatherTask(void *)
{
  HTTPClient http;
  for (;;)
  {
    uint32_t t0 = millis();
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
              if (v.containsKey("temperature")) forecastTemp = v["temperature"].as<float>();
              if (v.containsKey("humidity")) forecastHum = v["humidity"].as<float>();
              // choose light proxy: visibility else uvIndex
              if (v.containsKey("visibility")) forecastLight = v["visibility"].as<float>();
              else if (v.containsKey("uvIndex")) forecastLight = v["uvIndex"].as<float>();
              // decide rainSoon based on precipitationProbability or rainIntensity
              bool willRain = false;
              if (v.containsKey("precipitationProbability") && v["precipitationProbability"].as<int>() > 20) willRain = true;
              if (v.containsKey("rainIntensity") && v["rainIntensity"].as<float>() > 0.1f) willRain = true;
              if (v.containsKey("rainAccumulation") && v["rainAccumulation"].as<float>() > 0.0f) willRain = true;
              rainSoon = willRain;
              // also capture 3-hour ahead (if available as next element)
              if (arr.size() > 1)
              {
                JsonObject v3 = arr[1]["values"];
                if (!v3.isNull())
                {
                  if (v3.containsKey("temperature")) forecast3Temp = v3["temperature"].as<float>();
                  if (v3.containsKey("humidity")) forecast3Hum = v3["humidity"].as<float>();
                  if (v3.containsKey("visibility")) forecast3Light = v3["visibility"].as<float>();
                  else if (v3.containsKey("uvIndex")) forecast3Light = v3["uvIndex"].as<float>();
                }
              }
              Serial.printf("[WeatherTask] forecastT=%.1f H=%.0f light=%.2f -> +3h T=%.1f H=%.0f L=%.2f rain=%d\n", forecastTemp, forecastHum, forecastLight, forecast3Temp, forecast3Hum, forecast3Light, rainSoon ? 1 : 0);
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
    vTaskDelay(pdMS_TO_TICKS(3600 * 1000));
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
        String payload = "{";
        payload += "\"airTemp\":" + String(airTemp, 1) + ",";
        payload += "\"airHum\":" + String(airHum, 1) + ",";
        payload += "\"forecastTemp\":" + String(forecastTemp, 1) + ",";
        payload += "\"forecastHum\":" + String(forecastHum, 1) + ",";
        payload += "\"forecastLight\":" + String(forecastLight, 1) + ",";
        payload += "\"pumpOn\":" + String(pumpOn ? 1 : 0) + ",";
        payload += "\"rainSoon\":" + String(rainSoon ? 1 : 0) + ",";
        payload += "\"nextIrrigationMs\":" + String((uint32_t)nextIrrigationMs) + ",";
        payload += "\"soil\":[" + String(soilPct[0], 1) + "," + String(soilPct[1], 1) + "," + String(soilPct[2], 1) + "],";
        payload += "\"valves\":[" + String(valveOn[0] ? 1 : 0) + "," + String(valveOn[1] ? 1 : 0) + "," + String(valveOn[2] ? 1 : 0) + "]";
        payload += "}";

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
    vTaskDelay(pdMS_TO_TICKS(30000));
  }
}

void DisplayTask(void *)
{
  for (;;)
  {
    uint32_t t0 = millis();
    // Show: current air temp/hum, 3h forecast (temp/hum/light), pump/LED, and valve states
    bool ledState = digitalRead(PIN_LED_WD) == HIGH;
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("T:"); lcd.print(airTemp, 1); lcd.print("C H:"); lcd.print(airHum, 0); lcd.print("%   ");
    lcd.setCursor(0, 1);
    lcd.print("+3h T:"); lcd.print(forecast3Temp, 1); lcd.print("C H:"); lcd.print((int)forecast3Hum); lcd.print("%   ");
    lcd.setCursor(0, 2);
    lcd.print("L:"); lcd.print((int)forecastLight); lcd.print(" fL:"); lcd.print((int)forecast3Light); lcd.print("   ");
    lcd.setCursor(0, 3);
    lcd.print("Pump:"); lcd.print(pumpOn ? "ON" : "OFF"); lcd.print(" ");
    lcd.print("LED:"); lcd.print(ledState ? "ON" : "OFF");
    // Small delay to let user read; also show valve states on next refresh
    vTaskDelay(pdMS_TO_TICKS(2000));
    // show valves and soil
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("S1:"); lcd.print(soilPct[0], 0); lcd.print("% V1:"); lcd.print(valveOn[0] ? "ON" : "OFF");
    lcd.setCursor(0, 1);
    lcd.print("S2:"); lcd.print(soilPct[1], 0); lcd.print("% V2:"); lcd.print(valveOn[1] ? "ON" : "OFF");
    lcd.setCursor(0, 2);
    lcd.print("S3:"); lcd.print(soilPct[2], 0); lcd.print("% V3:"); lcd.print(valveOn[2] ? "ON" : "OFF");
    lcd.setCursor(0, 3);
    lcd.print("Next:"); lcd.print((uint32_t)(nextIrrigationMs / 1000)); lcd.print("s");
    uint32_t t1 = millis();
    logTask("DisplayTask", t0, t1 - t0, DL_DISPLAY_MS);
    vTaskDelay(pdMS_TO_TICKS(1000));
  }
}

void WatchdogTask(void *)
{
  for (;;)
  {
    uint32_t t0 = millis();
    digitalWrite(PIN_LED_WD, !digitalRead(PIN_LED_WD));
    uint32_t t1 = millis();
    logTask("WatchdogTask", t0, t1 - t0, DL_WATCHDOG_MS);
    vTaskDelay(pdMS_TO_TICKS(2000));
  }
}

struct IrrState { bool active; uint32_t startMs; int plant; };
static IrrState irr = {false, 0, 0};

void applyOutputs()
{
  // Only drive outputs if the device passed the last health check
  if (pumpOk)
    digitalWrite(PIN_RELAY_PUMP, pumpOn ? HIGH : LOW);
  else
    digitalWrite(PIN_RELAY_PUMP, LOW);

  if (valveOk[0]) digitalWrite(PIN_RELAY_V1, valveOn[0] ? HIGH : LOW);
  else digitalWrite(PIN_RELAY_V1, LOW);

  if (valveOk[1]) digitalWrite(PIN_RELAY_V2, valveOn[1] ? HIGH : LOW);
  else digitalWrite(PIN_RELAY_V2, LOW);

  if (valveOk[2]) digitalWrite(PIN_RELAY_V3, valveOn[2] ? HIGH : LOW);
  else digitalWrite(PIN_RELAY_V3, LOW);
}

void stopIrrigation()
{
  pumpOn = false;
  valveOn[0] = valveOn[1] = valveOn[2] = false;
  irr.active = false;
  applyOutputs();
}

void startIrrigation(int plant)
{
  irr = {true, static_cast<uint32_t>(millis()), plant};
  pumpOn = true;
  valveOn[plant] = true;
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
    if (nextIrrigationMs == 0) nextIrrigationMs = now + SCHEDULE_MS;
    bool scheduleDue = now >= nextIrrigationMs;

    if (irr.active)
    {
      bool timeDone = (now - irr.startMs) >= IRRIG_MS;
      bool soilDone = soilPct[irr.plant] >= SOIL_OFF;
      if (timeDone || soilDone) stopIrrigation();
    }
    else
    {
      // Use forecast and current conditions to compute desired soil threshold
      const float desiredThreshold = computeSoilOnThreshold();
      // Skip if rainSoon or forecast predicts high humidity
      if (scheduleDue && !rainSoon && forecastHum < 90.0f)
      {
        bool started = false;
        for (int i = 0; i < 3; ++i)
        {
          // only start if device health is OK
          if (!pumpOk)
          {
            Serial.println("[SwitchTask] pump not OK, skipping irrigation");
            break;
          }
          if (!valveOk[i])
          {
            Serial.printf("[SwitchTask] valve %d not OK, skipping this zone\n", i);
            continue;
          }
          if (soilPct[i] < desiredThreshold)
          {
            startIrrigation(i);
            started = true;
            break;
          }
        }
        if (!started) nextIrrigationMs = now + SCHEDULE_MS; // nothing to water, push schedule
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

  pinMode(PIN_RELAY_PUMP, OUTPUT);
  pinMode(PIN_RELAY_V1, OUTPUT);
  pinMode(PIN_RELAY_V2, OUTPUT);
  pinMode(PIN_RELAY_V3, OUTPUT);
  pinMode(PIN_LED_WD, OUTPUT);
  applyOutputs();

  analogReadResolution(12);
  dht.begin();
  wifiConnect();

  xTaskCreatePinnedToCore(SoilTask, "Soil", 4096, nullptr, 2, nullptr, 1);
  xTaskCreatePinnedToCore(DHTTask, "DHT", 4096, nullptr, 2, nullptr, 1);
  xTaskCreatePinnedToCore(SwitchTask, "Switch", 4096, nullptr, 3, nullptr, 1);
  xTaskCreatePinnedToCore(ErrorCheckTask, "Err", 2048, nullptr, 2, nullptr, 0);
  xTaskCreatePinnedToCore(WeatherTask, "Weather", 4096, nullptr, 1, nullptr, 0);
  xTaskCreatePinnedToCore(NetworkTask, "Net", 4096, nullptr, 1, nullptr, 0);
  xTaskCreatePinnedToCore(DisplayTask, "LCD", 4096, nullptr, 1, nullptr, 0);
  xTaskCreatePinnedToCore(WatchdogTask, "WD", 2048, nullptr, 3, nullptr, 0);
}

void loop()
{
  // Idle; work is in tasks
  vTaskDelay(pdMS_TO_TICKS(1000));
}
