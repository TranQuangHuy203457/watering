# RTOS_watering

Firmware and experiment scaffolding for RTS watering project.

Quick start for collaborators

- Install PlatformIO (recommended via Python venv):
  ```powershell
  python -m pip install --upgrade pip
  python -m pip install -U platformio
  ```

- Clone the repo and create a venv (optional):
  ```powershell
  git clone <your-repo-url>
  cd RTOS_watering
  python -m venv .venv
  .\.venv\Scripts\activate
  pip install -r requirements.txt  # optional: or pip install platformio
  ```

- Build (do NOT commit keys). Provide keys at build time:
  ```powershell
  C:/path/to/.venv/Scripts/python.exe -m platformio run -e baseline -DSUPABASE_URL="https://<proj>.supabase.co" -DSUPABASE_KEY="<your_key>" -DWEATHER_API_KEY="<your_key>"
  ```

- Upload and monitor:
  ```powershell
  C:/path/to/.venv/Scripts/python.exe -m platformio run -e baseline -t upload
  C:/path/to/.venv/Scripts/python.exe -m platformio device monitor -p COM3 -e baseline
  ```

Security note
- Do NOT commit API keys or service keys. Use build flags or a local `platformio.ini.local` (gitignored) to store keys for local builds.

Supabase
- The firmware posts telemetry to a Supabase `telemetry` table. Create the table in Supabase SQL editor with the schema suggested in the project README or use the SQL snippet in project notes.

If you want, I can create a GitHub repository for you and provide the git commands to push this project there (you'll need to provide the repo name and whether it's private/public).# He thong tuoi ho tieu ESP32 RTOS (1-3 goc)

## Phan cung
- Board: ESP32 DevKit v1 (CP2102, LuaNode32)
- Cam bien: DHT11 (nhiet do/ do am khong khi), 2-3 cam bien am dat kieu dien dung (analog, 3.3V)
- Relay/van: bom tai GPIO25, van1 GPIO26, van2 GPIO27, van3 GPIO14
- ADC do dat: GPIO34/35/32 (chi input)
- LCD: I2C dia chi 0x27, SDA=21, SCL=22
- LED (nhap nhay watchdog): GPIO33

## Muc tieu tuoi nuoc
- Nho giot: 2 dau x 4 L/h = 8 L/h moi goc
- The tich: 15-20 L moi goc -> ~2.3 gio chay; cat som neu do am dat >=70%
- Lich: moi 5 tuan (co the keo toi 7), chi tuoi neu am dat <60% va khong co du bao mua 24h toi

## Task va chu ky
- SoilTask: 1 s, firm
- DHTTask: 2 s, firm
- SwitchTask: 1 s, hard (xu ly bom/van, lich tuoi)
- ErrorCheck: 5 s, firm
- WeatherTask: 1 h, soft (stub)
- NetworkTask: 30 s, soft/firm (gui REST Firebase)
- DisplayTask: 1 s, soft
- WatchdogTask: 2 s, hard (chi nhap nhay; them WDT reset neu can)

## Cai dat
1) Cai PlatformIO trong VS Code.
2) Dien Wi-Fi va endpoint trong src/main.cpp: WIFI_SSID, WIFI_PASS, WEATHER_URL, FIREBASE_URL (REST).
3) Can chinh ADC cho cam bien dat: ADC_WET, ADC_DRY.
4) Build & upload: pio run --target upload (hoac VS Code "Upload").
5) Mo serial monitor 115200.

## Ghi chu
- WeatherTask va NetworkTask dang de trong; them API/Firebase auth thuc te.
- ErrorCheckTask nen doc cam bien dong hoac chan feedback de cat khi loi.
- Neu cap nguon cam bien dat qua GPIO/MOSFET de giam an mon, them tre khoi dong truoc khi doc.
- Tranh dung GPIO0/2/15/12 cho relay (chan boot); so do pin o tren da tranh.
