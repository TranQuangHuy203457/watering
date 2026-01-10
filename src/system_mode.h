#pragma once

#ifndef SYSTEM_MODE_H
#define SYSTEM_MODE_H

// System operational mode for fault handling
enum SystemMode { MODE_NORMAL = 0, MODE_DEGRADED = 1, MODE_SAFE = 2 };

// shared runtime variable (defined in main.cpp)
extern volatile SystemMode systemMode;

// setter implemented in main.cpp
void setSystemMode(SystemMode m);

#endif // SYSTEM_MODE_H
