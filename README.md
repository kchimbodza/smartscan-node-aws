# SmartScan Node

**Elder Care Occupancy Monitoring System using ESP32 and AWS IoT**

Semi-Finalist — Northeastern University Husky Pitch Summit 2025

---

## Architecture

```
ESP32 (HC-SR04 Sensor)
        |
        | MQTT over TLS/SSL (port 8883)
        v
AWS IoT Core
  - Thing: smartscan-node-aws-01
  - Topic: smartscan/presence
  - Rule: SELECT * FROM 'smartscan/presence'
        |
        v
AWS Lambda (presence_handler.py)
  - Parses occupancy payload
  - Derives data-driven insights on occupancy patterns
        |
        |---> DynamoDB (smartscan-occupancy)
        |       - device_id (PK), timestamp (SK)
        |       - distance_cm, occupied, TTL (30 days)
        |
        |---> SNS (smartscan-alerts)
                - Email alert on occupancy change
        |
CloudWatch
  - Lambda execution logs
  - IoT message throughput metrics
```

---

## Project Structure

```
smartscan-node-aws/
├── firmware/
│   ├── main.py              # ESP32 MicroPython - sensor read + MQTT publish
│   └── config.example.py   # WiFi + AWS endpoint config template
├── lambda/
│   └── presence_handler.py # Lambda - DynamoDB write + SNS alert
├── terraform/
│   └── main.tf             # IaC - IoT Core, Lambda, DynamoDB, SNS, CloudWatch
└── docs/
    └── wiring.md           # ESP32 wiring guide
```

---

## Hardware

| Component | Model | Purpose |
|---|---|---|
| Microcontroller | ESP32-S3 | WiFi, MQTT, sensor control |
| Presence sensor | HC-SR04 | Ultrasonic distance (0-400cm) |
| LED | Onboard GPIO2 | Visual presence indicator |

**Wiring:**
- TRIG → GPIO 5
- ECHO → GPIO 18
- VCC → 5V
- GND → GND

---

## AWS Setup

### 1. Provision infrastructure
```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Fill in alert_email
terraform init
terraform apply
```

### 2. Create IoT certificates
```bash
# In AWS Console → IoT Core → Security → Certificates
# Download: certificate.pem.crt, private.pem.key, AmazonRootCA1.pem
# Upload to ESP32 flash under /certs/
```

### 3. Flash firmware
```bash
# Install MicroPython on ESP32, then:
pip install ampy
cp firmware/config.example.py firmware/config.py
# Edit config.py with your WiFi + AWS endpoint
ampy --port /dev/ttyUSB0 put firmware/main.py
ampy --port /dev/ttyUSB0 put firmware/config.py
ampy --port /dev/ttyUSB0 mkdir /certs
ampy --port /dev/ttyUSB0 put certs/AmazonRootCA1.pem /certs/AmazonRootCA1.pem
ampy --port /dev/ttyUSB0 put certs/certificate.pem.crt /certs/certificate.pem.crt
ampy --port /dev/ttyUSB0 put certs/private.pem.key /certs/private.pem.key
```

---

## Data Flow

1. ESP32 reads HC-SR04 every 5 seconds
2. Debounce logic (3 consecutive reads) prevents false triggers
3. Presence payload published to `smartscan/presence` via MQTT over TLS
4. IoT Core rule triggers Lambda on every message
5. Lambda writes to DynamoDB with 30-day TTL
6. SNS alert fires on occupancy state change
7. CloudWatch logs Lambda execution and IoT message throughput

---

## Payload Schema

```json
{
  "device_id":   "smartscan-node-aws-01",
  "distance_cm": 87.3,
  "occupied":    true,
  "timestamp":   1714204800
}
```

---

## Motivation

Designed for elder care facilities where passive, non-invasive room occupancy monitoring can improve staff response times and resident safety. The system runs entirely on edge hardware with a serverless cloud backend — no continuous cloud polling, minimal cost.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Edge | ESP32-S3, MicroPython, FreeRTOS |
| Connectivity | MQTT over TLS/SSL (port 8883) |
| Cloud ingestion | AWS IoT Core |
| Processing | AWS Lambda (Python 3.12) |
| Storage | AWS DynamoDB (PAY_PER_REQUEST) |
| Alerting | AWS SNS (email) |
| Monitoring | AWS CloudWatch |
| IaC | Terraform |

---

## License

MIT
