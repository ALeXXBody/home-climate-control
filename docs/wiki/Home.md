# Home Climate Control Wiki

**HA integration** for multi-zone gas heating control.

| | |
|---|---|
| Repo | https://github.com/ALeXXBody/home-climate-control |
| Companion firmware | [Home Climate System](https://github.com/ALeXXBody/home-climate-system) · [HCS docs](https://github.com/ALeXXBody/home-climate-system/blob/main/docs/wiki/Home.md) |
| Current version | v1.4.5 |

## Pages

- [Install](Install.md)
- [Options & settings](Options-and-settings.md)
- [Sidebar app](Sidebar-app.md)
- [Efficiency tiers](Efficiency-tiers.md)
- [FAQ](FAQ.md)

## What it does

Home Climate Control (HCC) creates climate entities per room, drives a boiler gateway over MQTT (HCS board), and minimises gas use with:

- Weather-compensated flow temperature  
- Learned setbacks, dead-time, and optimal-start pre-heat  
- Low-load duty cycling + CycleGuard  
- Optional schedule and phone occupancy  
- Estimated gas (modulation or flow/return ΔT)  

## Quick links

- [Releases](https://github.com/ALeXXBody/home-climate-control/releases)  
- [README](https://github.com/ALeXXBody/home-climate-control#readme)  
- [Architecture](https://github.com/ALeXXBody/home-climate-control/blob/main/docs/architecture.md)  
