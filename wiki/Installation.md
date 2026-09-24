# Installation

Two things to install: the **HCC integration** (Home Assistant) and the **HCS firmware** (ESP32 + OpenTherm).

## 1. Home Assistant integration (HCC)

### Via HACS

1. Open HACS → **Integrations** → **⋮** → **Custom repositories**.
2. Add `https://github.com/ALeXXBody/home-climate-control` with category **Integration**.
3. Search for **Home Climate Control** → **Download**.
4. Restart Home Assistant.

### Add the integration

1. **Settings → Devices & services → Add integration → Home Climate Control**.
2. It auto-discovers the HCS board via MQTT and asks you to confirm the **node id** (e.g. `hcs-1c6920ce9104`).
3. Set the curve defaults (you can tune later): min/max flow, curve coefficient.
4. Add your **rooms** on the next screen (see [Configuration](Configuration)).

## 2. HCS firmware (ESP32 + OpenTherm)

### Hardware

- An ESP32 board (Wemos D1 mini ESP32, ESP32-C3, ESP32-S2 or ESP32-S3).
- An OpenTherm adapter wired to your boiler's OpenTherm port.

### Flash

- **PlatformIO**: clone [ALeXXBody/home-climate-system](https://github.com/ALeXXBody/home-climate-system), then `pio run -e <your_board> -t upload`.
- **Over-the-air (web)**: from the HCC panel **Firmware** tab, once an older version is already running.

### First boot

1. The board opens a **captive Wi-Fi portal** (AP `HCS-Recovery-xxxx` or similar).
2. Join it and enter your **Wi-Fi** and **MQTT broker** details (MQTT is usually your Home Assistant Mosquitto add-on at `192.168.x.x:1883`).
3. Reboot — the board connects to MQTT and announces itself to Home Assistant.

## 3. Wiring / OpenTherm notes

- The board acts as the **OpenTherm master**; your boiler is the slave.
- If the boiler has its own room thermostat wired to OpenTherm, the HCS can run in **gateway mode** (see the hardware repo's docs) to bridge both.

---

Next: [Configuration](Configuration).
