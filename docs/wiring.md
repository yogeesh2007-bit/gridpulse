# Wiring — GridPulse Station A (low-voltage demo, 12 V DC max)

> **This is a low-voltage logic demonstrator, not an EV charger.** Never connect mains. Keep the fuse in the 12 V
> positive line, verify polarity before powering, and never touch wiring while it is powered.

The pin map below is the one compiled into `firmware/esp32_station_a/esp32_station_a.ino` (the "CONFIG" block).
**It is an assumption** (your exact pin plan was not in the repo) — change the constants if your wiring differs.

| Function | ESP32 GPIO | Goes to | Note |
|---|---|---|---|
| I2C SDA | 21 | INA219 SDA | ESP32 default I2C pins |
| I2C SCL | 22 | INA219 SCL | |
| Button | 27 | one leg of the push button, other leg to GND | uses the internal pull-up, pressed = LOW |
| Output (PWM) | 25 | LR7843 MOSFET module **input/PWM** pin | only driven when `DRY_RUN = false` |
| Status LED | 2 | on-board LED | solid = talking to backend, slow blink = no backend |
| 3V3 / GND | 3V3, GND | INA219 VCC, GND | INA219 logic runs from 3.3 V |

## Power path (Stage B — when the parts arrive)

```
 12 V adapter (+) ── fuse (≥2 A, ≤ trip limit) ── INA219 VIN+ ──[shunt]── INA219 VIN− ── bulb (+)
                                                                                         bulb (−) ── MOSFET drain
 MOSFET source ── GND (12 V adapter −) ── ESP32 GND ── INA219 GND     (ONE common ground)
 ESP32 GPIO25 ──► MOSFET module input      (+ a 10 kΩ pull-down from gate/input to GND so it is OFF when the ESP32 resets)
```

* INA219 is wired **in series on the high side** (between the fuse and the bulb) so it measures bulb current and the
  bulb-side bus voltage. Its limits (26 V, ~3.2 A at 0.1 Ω) are fine for a 12 V bulb.
* The MOSFET switches the **low side** (bulb → drain, source → GND).
* The LR7843 module should accept a 3.3 V logic input — check your module's silkscreen/datasheet.
* A resistive bulb needs no flyback diode.

## Bring-up order (do not skip)

1. **Stage A — no power path:** ESP32 + INA219 (+ button) only, `DRY_RUN = true`. Flash, watch the serial monitor
   (115200). With the INA219 unplugged you should see `sensor=MISSING` and the dashboard shows placeholder values.
2. Plug the INA219 in: `sensor=ok`. Values read ~0 A until a load is connected.
3. **Stage B — with the MOSFET/bulb, still dry-run:** wire the power path but keep `DRY_RUN = true`; confirm the
   INA219 reads ~0 A and the bulb stays off whatever the dashboard commands.
4. **Stage C — live output:** set `DRY_RUN = false`, re-flash. Bulb brightness should follow the command
   (`NORMAL` bright, `REDUCE_LOAD` ~80%, `PAUSE_FLEX` off). The firmware clamps duty to `MAX_DUTY_PCT` (90%) and latches
   a fault above `CURRENT_TRIP_A` (1.8 A) — set that below your fuse rating.
5. Button: short press = local override (output held OFF); long press (2 s) = clear a latched fault.
