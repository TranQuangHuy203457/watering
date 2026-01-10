#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include "system_mode.h"

// Initialize internal mutex; call from setup()
void initStateLock();

// Populate a JSON document atomically with current telemetry/state snapshot
void populateStatus(JsonDocument &doc);

// Set pump state with optional expiry (expiryMs = 0 to clear)
void setPumpWithExpiry(bool on, uint32_t expiryMs);

// Check and expire any manual control expirations (to be called by web handler)
void checkAndExpireState();

// Snapshot of state for safe local decision-making
struct StateSnapshot {
	float soil[3];
	float airTemp;
	float airHum;
	float forecastTemp;
	float forecastHum;
	float forecast3Temp;
	float forecast3Hum;
	float forecastLight;
	bool rainSoon;
	bool pumpOn;
	bool pumpOk;
	bool ledOk;
	uint64_t nextIrrigationMs;
	SystemMode mode;
	// irrigation runtime
	bool irrActive;
	int irrPlant;
	uint32_t irrStartMs;
};

void getStateSnapshot(StateSnapshot &s);
void setNextIrrigationMs(uint64_t v);
