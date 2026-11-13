# SmartScan Node

**Elder Care Occupancy Monitoring System using ESP32 and AWS IoT**

Semi-Finalist — Northeastern University Husky Pitch Summit 2025

Occupancy sensor for elder-care rooms: an ESP32 reads an ultrasonic sensor and sends the room state to a serverless AWS backend that stores it and emails staff.

---

## Architecture

<p align="center"><img src="docs/architecture.svg" width="100%" alt="Edge: an HC-SR04 ultrasonic sensor on GPIO 5 and 18 is read by an ESP32-S3 running MicroPython every 5 seconds with a 3-read debounce; present means closer than 150 cm. The ESP32 publishes JSON over MQTT with TLS on port 8883 to AWS IoT Core topic smartscan/presence. An IoT rule (SELECT *) invokes a Python 3.12 Lambda, presence_handler.py, which writes to DynamoDB table smartscan-occupancy (on-demand, 30-day TTL) and sends an SNS email to smartscan-alerts when the room changes between occupied and vacant. Lambda logs go to CloudWatch Logs, kept 14 days. The AWS side is defined in terraform/main.tf."></p>

**Why this architecture**

| Choice | Why |
|---|---|
| Ultrasonic distance sensor (HC-SR04) | Passive and non-invasive: no camera in a resident's room, only a distance reading. |
| MQTT over TLS to AWS IoT Core with device certificates | The device proves who it is with its own X.509 certificate; no AWS keys are stored on it. The certificate is issued from a CSR, so the private key never leaves the machine that made it. |
| Alert decision on the device (`state_changed`) | The device already debounces and knows when the state flips, so the Lambda stays stateless and needs no extra DynamoDB read per message. |
| IoT rule → Lambda, no servers | Nothing runs between messages, which fits the "no continuous polling, minimal cost" goal. |
| DynamoDB on-demand, key `device_id` + `timestamp`, 30-day TTL | Pay per write; one Query gets a device's history; old rows expire on their own. |
| SNS email alerts | Staff get alerts without installing an app; the subscription is one Terraform resource. |
| Debounce on the device (3 reads in a row) | One stray echo does not flip the room state. |

## Results

There are no recorded device/cloud logs in this repo, so there are no field measurements to report. What exists:

| Check | Result | Source |
|---|---|---|
| Husky Pitch Summit 2025 | Semi-finalist | Northeastern University pitch event (stated above) |
| Lambda unit tests (`tests/`, fake DynamoDB/SNS) | **4 passed**: one email per state change (not per reading), clock fallback, valid device time kept, old payloads don't alert | `python -m pytest tests`, 13 Nov 2026, CPython 3.14 |
| `terraform validate` | **Success! The configuration is valid.** | 13 Nov 2026: Terraform 1.14, AWS provider 5.x, archive provider, `init -backend=false`, no credentials, nothing created |
| `terraform fmt -check` | Clean | Same run |
| Firmware | Compiles (`py_compile`) | Syntax only; not yet run on MicroPython hardware after the fixes below |

## What worked and what didn't

The ❌ items were found by reading the code and fixed on 13 Nov 2026 (the Lambda fix is covered by `tests/`; the firmware changes are not yet tested on hardware).

| | What | Detail |
|---|---|---|
| ✅ | Full path defined as code | IoT thing, policy, rule, Lambda, DynamoDB, SNS and log group are all in `terraform/main.tf`, and it validates. |
| ✅ | Debounce | The device needs 3 matching reads before it changes state. |
| ❌ fixed | Alert on every "occupied" message, not on change | The Lambda emailed whenever `occupied` was true, and the device publishes every 5 s, so an occupied room sent an email every 5 s. The device now sends `state_changed: true` only on the reading where the debounced state flips, and the Lambda alerts only then (both occupied and vacant). |
| ❌ fixed | Device name mismatch | `firmware/main.py` sent `smartscan-node-01`; Terraform and `config.example.py` use `smartscan-node-aws-01`. The firmware now reads `THING_NAME` from `config.py` and uses it as `device_id` and MQTT client ID. |
| ❌ fixed | `config.py` was not used | `main.py` never imported it and had no Wi-Fi code. It now imports `config.py` for Wi-Fi, endpoint and Thing name, connects to Wi-Fi at boot, and reconnects Wi-Fi and MQTT after network errors. |
| ❌ fixed | No clock sync | The firmware sent `time.time()` without NTP, so stored times and the 30-day TTL were wrong. It now syncs over NTP at boot and sends Unix time (correcting MicroPython's 2000 epoch). If a timestamp is still implausible, the Lambda uses its own time and records `time_source`. |
| ❌ fixed | Manual certificates, broad IoT policy | Certificates were made in the console and not attached, and the policy allowed Connect/Publish/Subscribe/Receive on `Resource: "*"`. Terraform now issues the certificate from a CSR, attaches it to the Thing and policy, and the policy only allows connecting as this Thing and publishing to `smartscan/presence`. |
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
│   └── main.tf             # IaC - IoT Core (thing, cert, policy), Lambda, DynamoDB, SNS, CloudWatch
├── tests/
│   └── test_presence_handler.py  # Lambda unit tests with fake DynamoDB/SNS
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

### 1. Make the device key and CSR (on your machine)
```bash
mkdir -p certs
openssl req -new -newkey rsa:2048 -nodes -keyout certs/private.pem.key \
  -subj "/CN=smartscan-node-aws-01" -out certs/device.csr
curl -o certs/AmazonRootCA1.pem https://www.amazontrust.com/repository/AmazonRootCA1.pem
```
The private key stays in `certs/` (git-ignored); only the CSR goes to AWS.

### 2. Provision infrastructure
```bash
cd terraform
echo 'alert_email = "you@example.com"' > terraform.tfvars
terraform init
terraform apply
terraform output -raw device_certificate_pem > ../certs/certificate.pem.crt
terraform output iot_endpoint     # put this in config.py
```
Confirm the SNS subscription email AWS sends you.

### 3. Flash firmware
```bash
# Install MicroPython on ESP32, then:
pip install ampy
cp firmware/config.example.py firmware/config.py
# Edit config.py: Wi-Fi, AWS_ENDPOINT (from terraform output), THING_NAME (same as terraform thing_name)
ampy --port /dev/ttyUSB0 put firmware/main.py
ampy --port /dev/ttyUSB0 put firmware/config.py
ampy --port /dev/ttyUSB0 mkdir /certs
ampy --port /dev/ttyUSB0 put certs/AmazonRootCA1.pem /certs/AmazonRootCA1.pem
ampy --port /dev/ttyUSB0 put certs/certificate.pem.crt /certs/certificate.pem.crt
ampy --port /dev/ttyUSB0 put certs/private.pem.key /certs/private.pem.key
```

### Run the tests
```bash
pip install pytest
python -m pytest tests
```

---

## Data Flow

1. ESP32 reads HC-SR04 every 5 seconds
2. Debounce logic (3 consecutive reads) prevents false triggers
3. Presence payload published to `smartscan/presence` via MQTT over TLS
4. IoT Core rule triggers Lambda on every message
5. Lambda writes to DynamoDB with 30-day TTL
6. SNS email is sent only when `state_changed` is true: once when the room becomes occupied and once when it becomes vacant
7. CloudWatch logs Lambda execution and IoT message throughput

---

## Payload Schema

```json
{
  "device_id":     "smartscan-node-aws-01",
  "distance_cm":   87.3,
  "occupied":      true,
  "state_changed": true,
  "timestamp":     1714204800
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
