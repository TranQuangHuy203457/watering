#!/usr/bin/env python3
import http.server
import socketserver
import json
import threading
import math
import time
import random
import os
from urllib.parse import urlparse

PORT = 8000
WWW_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'www')

# Shared state for mock
state = {
    'airTemp': 25.0,
    'airHum': 55.0,
    'forecast3Temp': 26.0,
    'forecast3Hum': 60.0,
    'forecastLight': 1000,
    'soil': [45.0, 50.0, 48.0],
    'pumpOn': 0,
    'valves': [0,0,0],
    'rainSoon': 0,
    'nextIrrigationMs': 3600,
    'light': 0,
    'pumpOffTime': 0,  # Timestamp when pump should auto-off
    'lightOffTime': 0  # Timestamp when light should auto-off
}

# Simulation parameters
DAY_SECONDS = 24.0 * 3600.0
PUMP_FLOW_PER_SEC = 0.8 / 60.0  # percent per second when pump on (~0.8%/s => ~48%/min unrealistic fast; tune as needed)
VALVE_FLOW_PER_SEC = 0.5 / 60.0
EVAP_BASE_PER_SEC = 0.02 / 60.0  # base evaporation percent per second
RAIN_PROB_HOURLY = 0.05  # 5% chance per hour

def background_update():
    start = time.time()
    last_rain = 0
    while True:
        now = time.time()
        # diurnal cycle: temperature follows a sine wave (peak mid-afternoon)
        t_of_day = now % DAY_SECONDS
        # peak at 15:00 local -> phase shift
        phase = (15*3600)
        amp = 6.0  # degrees amplitude
        base = 24.0
        temp = base + amp * math.sin(2*math.pi*(t_of_day - phase)/DAY_SECONDS)
        # small noise
        temp += random.uniform(-0.3, 0.3)

        # humidity inversely correlated with temperature, plus noise
        hum_base = 65.0 - (temp - base) * 1.5
        hum = hum_base + random.uniform(-2.0, 2.0)

        # Forecasts: simple shift ahead by 3 hours
        future_t = (now + 3*3600) % DAY_SECONDS
        forecastTemp = base + amp * math.sin(2*math.pi*(future_t - phase)/DAY_SECONDS)
        forecastHum = 65.0 - (forecastTemp - base) * 1.5

        state['airTemp'] = round(temp, 2)
        state['airHum'] = round(max(5.0, min(100.0, hum)), 1)
        state['forecast3Temp'] = round(forecastTemp, 2)
        state['forecast3Hum'] = round(max(5.0, min(100.0, forecastHum)), 1)
        # simple light proxy: daylight intensity
        day_fraction = max(0.0, math.cos(2*math.pi*(t_of_day - 12*3600)/DAY_SECONDS) * -1)
        state['forecastLight'] = int(1000 + 3000 * day_fraction)

        # Rain event: random chance per hour, when raining increase soil quickly
        # Convert hourly prob to per-second
        rain_prob_per_sec = RAIN_PROB_HOURLY / 3600.0
        is_raining = False
        if random.random() < rain_prob_per_sec:
            is_raining = True
            last_rain = now
            state['rainSoon'] = 1
        # keep rainSoon true for a short while after rain
        if now - last_rain > 3600:
            state['rainSoon'] = 0

        # Soil dynamics: evaporation reduces moisture; pump/valve increase moisture
        evap = EVAP_BASE_PER_SEC * (1.0 + max(0.0, (state['airTemp'] - 25.0)/10.0))
        for i in range(3):
            # pump increases all zones slightly if pumpOn, valves increase individual zone
            gain = 0.0
            if state.get('pumpOn', 0):
                gain += PUMP_FLOW_PER_SEC
            if state['valves'][i]:
                gain += VALVE_FLOW_PER_SEC
            # rain gives a larger temporary gain
            if is_raining:
                gain += 0.6 / 60.0  # 0.6%/s during rain
            # update soil
            newv = state['soil'][i] + gain - evap
            # clamp
            newv = max(0.0, min(100.0, newv))
            state['soil'][i] = round(newv, 2)

        # Auto-off timers for pump and light (manual mode with duration)
        now_ts = time.time()
        if state.get('pumpOffTime', 0) > 0 and now_ts >= state['pumpOffTime']:
            state['pumpOn'] = 0
            state['pumpOffTime'] = 0
            print('[preview] Pump auto-off after duration')
        
        if state.get('lightOffTime', 0) > 0 and now_ts >= state['lightOffTime']:
            state['light'] = 0
            state['lightOffTime'] = 0
            print('[preview] Light auto-off after duration')

        time.sleep(1)

class PreviewHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            # ensure numeric types
            out = {
                'airTemp': round(state['airTemp'],1),
                'airHum': round(state['airHum'],0),
                'forecast3Temp': round(state['forecast3Temp'],1),
                'forecast3Hum': round(state['forecast3Hum'],0),
                'forecastLight': state['forecastLight'],
                'soil': [round(s,1) for s in state['soil']],
                'pumpOn': state['pumpOn'],
                'light': state.get('light', 0),
                'rainSoon': state['rainSoon'],
                'nextIrrigationMs': state['nextIrrigationMs'],
                'mode': 0
            }
            self.wfile.write(json.dumps(out).encode('utf-8'))
            return
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/control':
            length = int(self.headers.get('Content-Length', '0'))
            body = self.rfile.read(length) if length>0 else b''
            try:
                obj = json.loads(body.decode('utf-8'))
                now_ts = time.time()
                
                # Handle pump control
                if 'pump' in obj:
                    pump_val = 1 if int(obj['pump']) else 0
                    state['pumpOn'] = pump_val
                    
                    # If turning on pump in manual mode with duration, set auto-off timer
                    if pump_val and obj.get('mode') == 'manual' and 'durationPump' in obj:
                        duration = int(obj['durationPump'])
                        if duration > 0:
                            state['pumpOffTime'] = now_ts + duration
                            print(f'[preview] Pump ON for {duration}s (will auto-off)')
                        else:
                            state['pumpOffTime'] = 0
                    else:
                        state['pumpOffTime'] = 0
                
                # Handle light control
                if 'light' in obj:
                    light_val = 1 if int(obj['light']) else 0
                    state['light'] = light_val
                    
                    # If turning on light in manual mode with duration, set auto-off timer
                    if light_val and obj.get('mode') == 'manual' and 'durationLight' in obj:
                        duration = int(obj['durationLight'])
                        if duration > 0:
                            state['lightOffTime'] = now_ts + duration
                            print(f'[preview] Light ON for {duration}s (will auto-off)')
                        else:
                            state['lightOffTime'] = 0
                    else:
                        state['lightOffTime'] = 0
                
                # Store control mode
                if 'mode' in obj:
                    state['controlMode'] = obj['mode']
                
                print('[preview] control ->', obj)
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.end_headers()
                self.wfile.write(b'{"ok":1}')
            except Exception as e:
                print('Error parsing control:', e)
                self.send_response(400)
                self.end_headers()
            return
        return super().do_POST()

def run():
    os.chdir(WWW_DIR)
    handler = PreviewHandler
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print(f"Serving preview at http://localhost:{PORT}/ (serving {WWW_DIR})")
        httpd.serve_forever()

if __name__ == '__main__':
    t = threading.Thread(target=background_update, daemon=True)
    t.start()
    run()
