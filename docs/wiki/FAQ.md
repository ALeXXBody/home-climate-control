# FAQ

### Board shows old firmware after HCC update  
HCC (integration) and HCS (ESP firmware) version separately. OTA the board from **Devices** or the [HCS release](https://github.com/ALeXXBody/home-climate-system/releases).

### Board pings but HTTP times out  
Power-cycle the ESP. Prefer firmware ≥ 1.4.0 (HTTP / OTA fixes).

### Outdoor is blank  
Check boiler outdoor on the HCS board, or set **Outdoor temperature fallback** in options.

### Rooms not pre-heating  
Need measured warm rate (calibration or setback cycles) and dead-time. Use **Calibrate** on the room card.

### Occupancy does nothing  
Must enable **Occupancy auto-setback** and select trackers. Default is off.

### Gas estimate looks wrong  
Set nameplate heat **input** kW and optional calibration against your meter. With OT flow/return, mode may show `ΔT estimate` or `modulating+ΔT`.
