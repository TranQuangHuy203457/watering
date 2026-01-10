#!/usr/bin/env python3















































#!/usr/bin/env python3
"""
Host-side irrigation logic simulator (clean).

This script simulates 3 soil sensors, DHT-like readings and a simple
weather event generator. It runs the Switch logic and prints actions.

Run:
  python scripts/simulate_logic.py
"""

import time
import random

# Simulation parameters (shortened durations for demo)
SOIL_ON = 60.0
SOIL_OFF = 70.0
# Use short irrigation duration for demo (10s) instead of 2.3h
IRRIG_MS = 10 * 1000
SCHEDULE_S = 60  # 1 minute schedule for demo

# State
soil = [75.0, 65.0, 62.0]
airTemp = 25.0
airHum = 50.0
forecast3Temp = 26.0
forecast3Hum = 50.0
rainSoon = False
pumpOk = True
pumpOn = False
nextIrrigationTs = 0
irr = { 'active': False, 'start_ts': 0, 'plant': -1 }

now_ms = lambda: int(time.time() * 1000)
now_s = lambda: int(time.time())


def compute_soil_threshold():
    thr = SOIL_ON
    if airTemp > 30.0 and airHum < 40.0:
        thr += 8.0
    if forecast3Temp > 32.0 and forecast3Hum < 40.0:
        thr += 5.0
    if airHum > 80.0:
        thr -= 6.0
    thr = max(40.0, min(95.0, thr))
    return thr


def start_irrigation(plant, duration_ms):
    global irr, pumpOn
    irr['active'] = True
    irr['start_ts'] = now_ms()
    irr['plant'] = plant
    pumpOn = True
    print(f"[ACTION] START irrigation zone={plant} dur_ms={duration_ms} soil={soil[plant]:.1f}")


def stop_irrigation(reason):
    global irr, pumpOn
    print(f"[ACTION] STOP irrigation zone={irr['plant']} reason={reason}")
    irr['active'] = False
    irr['start_ts'] = 0
    irr['plant'] = -1
    pumpOn = False


def simulate_sensors_tick():
    # soil dries slowly; if pump on for a zone, that zone increases
    for i in range(3):
        if pumpOn and irr['active'] and irr['plant'] == i:
            soil[i] += 1.0  # wetting faster for demo
        else:
            soil[i] -= 0.2
        soil[i] = max(0.0, min(100.0, soil[i]))


def simulate_weather_event():
    global rainSoon, forecast3Hum
    # occasionally trigger rainSoon
    if random.random() < 0.05:
        rainSoon = True
        forecast3Hum = 95.0
        print('[WEATHER] rain predicted soon')
    elif random.random() < 0.05:
        rainSoon = False
        forecast3Hum = random.uniform(30.0, 70.0)


def maybe_stop_irrigation():
    if not irr['active']:
        return
    now = now_ms()
    timeDone = (now - irr['start_ts']) >= IRRIG_MS
    soilDone = soil[irr['plant']] >= SOIL_OFF
    if timeDone:
        stop_irrigation('time')
    elif soilDone:
        stop_irrigation('soil')


def maybe_start_irrigation():
    global nextIrrigationTs
    now = now_ms()
    if nextIrrigationTs == 0:
        nextIrrigationTs = now + 5000  # schedule due shortly for demo
    scheduleDue = now >= nextIrrigationTs
    if irr['active']:
        return
    if scheduleDue and (not rainSoon) and (forecast3Hum < 90.0):
        desired = compute_soil_threshold()
        for i in range(3):
            if not pumpOk:
                print('[SWITCH] pump not OK, skipping')
                break
            if soil[i] < desired:
                start_irrigation(i, IRRIG_MS)
                return
        # nothing to water, push schedule
        nextIrrigationTs = now + SCHEDULE_S * 1000


if __name__ == '__main__':
    print('Starting host-side irrigation logic simulator (Ctrl+C to stop)')
    start = now_s()
    last_display = 0
    try:
        while True:
            simulate_sensors_tick()
            simulate_weather_event()
            maybe_stop_irrigation()
            maybe_start_irrigation()

            if now_s() - last_display >= 5:
                last_display = now_s()
                print('--- STATE ---')
                print(f"uptime_s={now_s()-start} pumpOn={pumpOn} irr_active={irr['active']} zone={irr['plant']}")
                print(f"soil = {soil[0]:.1f}, {soil[1]:.1f}, {soil[2]:.1f}")
                print(f"airT={airTemp:.1f}C forecast3H={forecast3Hum:.0f}% rainSoon={rainSoon}")
                print(f"nextIrrSec={(nextIrrigationTs - now_ms())//1000}")

            time.sleep(0.5)
    except KeyboardInterrupt:
        print('\nSimulator stopped')
