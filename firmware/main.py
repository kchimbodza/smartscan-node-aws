"""
SmartScan Node - ESP32 Firmware (MicroPython)
Reads HC-SR04 ultrasonic sensor, detects presence, publishes to AWS IoT Core via MQTT over TLS
"""

import machine
import time
import ujson
import ubinascii
from umqtt.simple import MQTTClient
import ussl

# ── Pin Configuration ─────────────────────────────────────────────────────────
TRIG_PIN = 5
ECHO_PIN = 18
LED_PIN  = 2          # onboard LED, blinks on presence detection

trig = machine.Pin(TRIG_PIN, machine.Pin.OUT)
echo = machine.Pin(ECHO_PIN, machine.Pin.IN)
led  = machine.Pin(LED_PIN, machine.Pin.OUT)

# ── AWS IoT Core Configuration ────────────────────────────────────────────────
# Replace with your AWS IoT endpoint and Thing name
AWS_ENDPOINT  = b"YOUR_ENDPOINT.iot.us-east-1.amazonaws.com"
THING_NAME    = b"smartscan-node-01"
MQTT_TOPIC    = b"smartscan/presence"
MQTT_PORT     = 8883
CLIENT_ID     = ubinascii.hexlify(machine.unique_id())

# Certs stored on ESP32 flash (upload via ampy or rshell)
CERT_DIR  = "/certs"
CA_CERT   = CERT_DIR + "/AmazonRootCA1.pem"
CERT_FILE = CERT_DIR + "/certificate.pem.crt"
KEY_FILE  = CERT_DIR + "/private.pem.key"

# ── Presence Detection Config ─────────────────────────────────────────────────
PRESENCE_THRESHOLD_CM = 150   # detect presence within 150 cm
SAMPLE_INTERVAL_S     = 5     # publish every 5 seconds
DEBOUNCE_COUNT        = 3     # consecutive reads before state change

# ── Ultrasonic Distance Measurement ──────────────────────────────────────────
def read_distance_cm():
    """Returns distance in cm from HC-SR04 sensor."""
    trig.off()
    time.sleep_us(2)
    trig.on()
    time.sleep_us(10)
    trig.off()

    timeout = time.ticks_us()
    while echo.value() == 0:
        if time.ticks_diff(time.ticks_us(), timeout) > 30000:
            return None   # timeout — no echo
    pulse_start = time.ticks_us()

    while echo.value() == 1:
        if time.ticks_diff(time.ticks_us(), pulse_start) > 30000:
            return None
    pulse_end = time.ticks_us()

    duration = time.ticks_diff(pulse_end, pulse_start)
    distance = (duration * 0.0343) / 2
    return round(distance, 1)

# ── MQTT Connection ───────────────────────────────────────────────────────────
def connect_mqtt():
    """Connect to AWS IoT Core over TLS/SSL."""
    print("Connecting to AWS IoT Core...")
    ssl_params = {
        "keyfile":  KEY_FILE,
        "certfile": CERT_FILE,
        "ca_certs": CA_CERT,
        "server_side": False
    }
    client = MQTTClient(
        client_id=CLIENT_ID,
        server=AWS_ENDPOINT,
        port=MQTT_PORT,
        ssl=True,
        ssl_params=ssl_params,
        keepalive=60
    )
    client.connect()
    print(f"Connected: {AWS_ENDPOINT.decode()}")
    return client

# ── Publish Payload ───────────────────────────────────────────────────────────
def publish_presence(client, distance, occupied):
    """Build and publish JSON payload to AWS IoT Core."""
    payload = ujson.dumps({
        "device_id":   THING_NAME.decode(),
        "distance_cm": distance,
        "occupied":    occupied,
        "timestamp":   time.time()
    })
    client.publish(MQTT_TOPIC, payload.encode())
    print(f"Published: {payload}")
    led.on() if occupied else led.off()

# ── Main Loop ─────────────────────────────────────────────────────────────────
def main():
    client = connect_mqtt()
    consecutive_occupied = 0
    consecutive_vacant   = 0
    current_state        = False

    while True:
        try:
            distance = read_distance_cm()

            if distance is None:
                print("Sensor timeout — skipping")
                time.sleep(SAMPLE_INTERVAL_S)
                continue

            # Debounce: require N consecutive same-direction reads
            if distance < PRESENCE_THRESHOLD_CM:
                consecutive_occupied += 1
                consecutive_vacant    = 0
            else:
                consecutive_vacant   += 1
                consecutive_occupied  = 0

            if consecutive_occupied >= DEBOUNCE_COUNT and not current_state:
                current_state = True
                publish_presence(client, distance, True)
            elif consecutive_vacant >= DEBOUNCE_COUNT and current_state:
                current_state = False
                publish_presence(client, distance, False)
            else:
                # Still publish telemetry every interval for CloudWatch monitoring
                publish_presence(client, distance, current_state)

            time.sleep(SAMPLE_INTERVAL_S)

        except OSError as e:
            print(f"MQTT error: {e} — reconnecting")
            time.sleep(5)
            client = connect_mqtt()

if __name__ == "__main__":
    main()
