# ESP32 Wiring Guide — HC-SR04 Ultrasonic Sensor

## Pin Connections

| HC-SR04 Pin | ESP32 Pin | Notes |
|---|---|---|
| VCC | 5V (VIN) | Sensor needs 5V supply |
| GND | GND | Common ground |
| TRIG | GPIO 5 | Output — trigger pulse |
| ECHO | GPIO 18 | Input — echo return |

> **Note:** HC-SR04 ECHO output is 5V. ESP32 GPIO is 3.3V tolerant.
> Use a voltage divider (1kΩ + 2kΩ) on the ECHO line to protect the ESP32.

## Voltage Divider (ECHO line protection)

```
HC-SR04 ECHO (5V) ──┬── 1kΩ ──┬── ESP32 GPIO 18
                    │          │
                   GND        2kΩ
                               │
                              GND
```

## Power

Power the ESP32 via USB during development.
For deployment, use a 5V/2A USB power supply or LiPo battery with boost converter.
