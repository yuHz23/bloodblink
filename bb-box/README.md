# BB-Box — Cold Chain Monitoring Firmware

## Hardware
- **MCU**: ESP32-S3 (240 MHz dual-core, WiFi + BLE)
- **Temperature**: 2× TMP117 (I²C, ±0.1°C accuracy)
  - One for storage compartment (core)
  - One for outer shell (transport environment)
- **Door sensor**: Reed switch (GPIO interrupt)
- **Shock**: LIS3DH accelerometer (I²C, ±16g)
- **Storage**: W25Q128 flash (SPI, 16 MB)
- **RTC**: DS3231 (I²C, ±2 ppm accuracy)
- **LED**: RGB status indicator
- **Buzzer**: Piezo alarm

## Key Design Decisions

### Two Temperature Modes (Article 20 TT 26/2013/TT-BYT)
The BB-Box differentiates between STORAGE and TRANSPORT thresholds:

| Component | Storage | Transport |
|-----------|---------|-----------|
| WB       | 2–6°C   | 1–10°C    |
| RBC      | 2–6°C   | 1–10°C    |
| PLT      | 20–24°C | 20–24°C   |
| FFP      | ≤−25°C (24mo) / −18…−25°C (12mo) | ≤−18°C |

This is a **critical correction** — the original project description conflated storage and transport thresholds.

### Architecture
- FreeRTOS tasks for concurrent sensor reading, WiFi, and logging
- ShipmentReading struct matches BB-Core database schema
- Batch upload to BB-Core via REST API when WiFi available
- Local flash buffer when offline (up to 16 MB = ~100K readings)
- Watchdog timer for reliability

## Pin Mapping (ESP32-S3)

| Function | Pin | Notes |
|----------|-----|-------|
| TMP117 #1 (core) SDA | GPIO 8 | I²C bus 1 |
| TMP117 #1 (core) SCL | GPIO 9 | I²C bus 1 |
| TMP117 #2 (shell) SDA | GPIO 18 | I²C bus 0 |
| TMP117 #2 (shell) SCL | GPIO 17 | I²C bus 0 |
| Reed switch | GPIO 4 | Interrupt, pull-up |
| LIS3DH SDA | GPIO 8 | Shared I²C bus 1 |
| LIS3DH SCL | GPIO 9 | Shared I²C bus 1 |
| LIS3DH INT1 | GPIO 5 | Wake on shock |
| W25Q CS | GPIO 10 | SPI CS |
| W25Q CLK | GPIO 12 | SPI CLK |
| W25Q MOSI | GPIO 11 | SPI MOSI |
| W25Q MISO | GPIO 13 | SPI MISO |
| DS3231 SDA | GPIO 8 | Shared I²C bus 1 |
| DS3231 SCL | GPIO 9 | Shared I²C bus 1 |
| LED R | GPIO 2 | PWM |
| LED G | GPIO 15 | PWM |
| LED B | GPIO 16 | PWM |
| Buzzer | GPIO 21 | PWM tone |

## Build

```bash
# Using PlatformIO
cd bb-box
pio run -e esp32-s3

# Upload
pio run -e esp32-s3 -t upload

# Monitor
pio device monitor -b 115200
```

## Testing

```bash
pio test -e native
```