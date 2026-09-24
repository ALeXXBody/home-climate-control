# Troubleshooting

## Boiler won't fire when rooms are cold

1. Check the panel **Home** tab: does **Total demand** show anything, and is any room's demand > 0?
2. Check **Diagnostics → cycle-guard**: if it says "resting", the boiler is in its anti-short-cycle rest window (up to ~15 min).
3. Check the board (Devices tab) is online and the OT link is valid.
4. If the integration was just reloaded, wait one control tick (≤60 s).

## Room isn't warming even though the boiler is on

- The room's **TRV valve** may be shut. Check the room card: is the valve open? If HCC *thinks* it should heat but the valve is closed, check the room's **heat-control mode** is **Smart**, and that the TRV target follows the room target.

## "Setback depth still learning"

Each room needs a few complete **Away/Eco → comfort** cycles before HCC trusts its recovery-speed estimate. It's working — just needs a few real setback nights. (It persists across restarts.)

## Boiler short-cycling

- Check **boiler minimum modulation** matches your boiler's nameplate (if set too high, duty-cycling never engages).

## Condensing / flow cap not active

- These need the board to report a **return temperature**. If the logs show *"No boiler return temperature available"*, your board/firmware isn't publishing `return_temp`.

## The firmware won't update (OTA)

- Check the board is online and the **Devices** tab shows the board.
- The board pulls the image over your LAN mirror. If it "stays on the old version", the mirror may have been stale — updating to the latest HCC fixes this.
- ESP32 images are **signed**; the signature (`.sig`) must sit next to the `.bin` on the mirror.

## Room disappears after renaming / editing

Reload the integration (Settings → Devices → HCC → ⋮ → Reload).

## Gas numbers look wrong

- Set the boiler's **rated heat input** and **minimum heat input** (kW) correctly — these convert modulation % into kWh.
- Use the **calibration factor** to match your real gas meter.

## Where to report bugs

Open an issue at [ALeXXBody/home-climate-control/issues](https://github.com/ALeXXBody/home-climate-control/issues) (integration) or [ALeXXBody/home-climate-system/issues](https://github.com/ALeXXBody/home-climate-system/issues) (firmware). Include the board version, HA version, and the relevant log lines.
