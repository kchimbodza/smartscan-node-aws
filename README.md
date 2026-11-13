# SmartScan Node

**Elder Care Occupancy Monitoring System using ESP32 and AWS IoT**

Semi-Finalist — Northeastern University Husky Pitch Summit 2025

Occupancy sensor for elder-care rooms: an ESP32 reads an ultrasonic sensor and sends the room state to a serverless AWS backend that stores it and emails staff.

---

## Architecture

<p align="center"><img src="docs/architecture.svg" width="100%" alt="Edge: an HC-SR04 ultrasonic sensor on GPIO 5 and 18 is read by an ESP32-S3 running MicroPython every 5 seconds with a 3-read debounce; present means closer than 150 cm. The ESP32 publishes JSON over MQTT with TLS on port 8883 to AWS IoT Core topic smartscan/presence. An IoT rule (SELECT *) invokes a Python 3.12 Lambda, presence_handler.py, which writes to DynamoDB table smartscan-occupancy (on-demand, 30-day TTL) and sends an SNS email to smartscan-alerts when occupied is true. Lambda logs go to CloudWatch Logs, kept 14 days. The AWS side is defined in terraform/main.tf."></p>

**Why this architecture**

| Choice | Why |
|---|---|
| Ultrasonic distance sensor (HC-SR04) | Passive and non-invasive: no camera in a resident's room, only a distance reading. |
| MQTT over TLS to AWS IoT Core with device certificates | The device proves who it is with its own X.509 certificate; no AWS keys are stored on it. |
| IoT rule → Lambda, no servers | Nothing runs between messages, which fits the "no continuous polling, minimal cost" goal. |
| DynamoDB on-demand, key `device_id` + `timestamp`, 30-day TTL | Pay per write; one Query gets a device's history; old rows expire on their own. |
| SNS email alerts | Staff get alerts without installing an app; the subscription is one Terraform resource. |
| Debounce on the device (3 reads in a row) | One stray echo does not flip the room state. |

## Results

No automated tests, CI runs, or recorded device/cloud logs are in this repo yet, so there are no measured numbers to report.
What exists:

| Check | Result | Source |
|---|---|---|
| Husky Pitch Summit 2025 | Semi-finalist | Northeastern University pitch event (stated above) |
| `terraform validate` | **Success! The configuration is valid.** | Re-run 13 Nov 2026: Terraform 1.14.0, AWS provider 5.100.0, archive 2.8.1, `init -backend=false`, no credentials, nothing created |
| `terraform fmt -check` | Fails on `main.tf` (alignment of one-line variables and outputs only) | Same run |
| Python syntax (`py_compile`) | Lambda and firmware both compile | Same day, CPython 3.14 (syntax only; not a MicroPython or AWS run) |

## What worked and what didn't

Found by reading the code; none of these were caught by tests because there are none yet.

| | What | Detail |
|---|---|---|
| ✅ | Full path defined as code | IoT thing, policy, rule, Lambda, DynamoDB, SNS and log group are all in `terraform/main.tf`, and it validates. |
| ✅ | Debounce | The device needs 3 matching reads before it changes state. |
| ❌ | Alert on every "occupied" message, not on change | The Lambda emails whenever `occupied` is true, and the device publishes every 5 s, so an occupied room sends an email every 5 s. It needs the previous state (e.g. a DynamoDB `GetItem`, already allowed by the IAM policy) to alert only on change. |
| ❌ | Device name mismatch | `firmware/main.py` sends `device_id` `smartscan-node-01`; Terraform and `config.example.py` use `smartscan-node-aws-01`. |
| ❌ | `config.py` is not used | `main.py` never imports it: the endpoint is hard-coded and there is no Wi-Fi connect code, so Wi-Fi must be set up separately (e.g. in `boot.py`). |
| ❌ | No clock sync | The firmware sends `time.time()` without NTP, so timestamps come from an unset clock; the stored time and the 30-day TTL (timestamp + 30 days) are then wrong, and rows can expire early. |
| ⚠️ | Manual certificates, broad IoT policy | Certificates are created in the console and not attached by Terraform; the IoT policy allows all actions on `Resource: "*"`. |
| ⚠️ | Missing tfvars example | Setup used to say `cp terraform.tfvars.example`, but that file is not in the repo; the step below now writes `terraform.tfvars` directly. |

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
    ├── architecture.svg    # Architecture diagram
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
echo 'alert_email = "you@example.com"' > terraform.tfvars
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
6. SNS email is sent for every message with `occupied: true` (see [What worked and what didn't](#what-worked-and-what-didnt))
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
