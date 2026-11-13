"""
SmartScan Node - ESP32 Firmware (MicroPython)
Reads HC-SR04 ultrasonic sensor, detects presence, publishes to AWS IoT Core via MQTT over TLS
"""

import machine
import network
import ntptime
import time
import ujson
from umqtt.simple import MQTTClient

import config   # config.py (copy of config.example.py): Wi-Fi, AWS endpoint, Thing name

# ── Pin Configuration ─────────────────────────────────────────────────────────
TRIG_PIN = 5
ECHO_PIN = 18
LED_PIN  = 2          # onboard LED, on while the room is occupied

trig = machine.Pin(TRIG_PIN, machine.Pin.OUT)
echo = machine.Pin(ECHO_PIN, machine.Pin.IN)
led  = machine.Pin(LED_PIN, machine.Pin.OUT)

# ── AWS IoT Core Configuration ────────────────────────────────────────────────
# Endpoint and Thing name come from config.py, so they match terraform's thing_name.
# The client ID is the Thing name: the IoT policy only allows that client ID to connect.
AWS_ENDPOINT = config.AWS_ENDPOINT.encode()
THING_NAME   = config.THING_NAME
CLIENT_ID    = THING_NAME.encode()
MQTT_TOPIC   = b"smartscan/presence"
MQTT_PORT    = 8883

# Certs stored on ESP32 flash (upload via ampy or rshell)
CERT_DIR  = "/certs"
CA_CERT   = CERT_DIR + "/AmazonRootCA1.pem"
CERT_FILE = CERT_DIR + "/certificate.pem.crt"
KEY_FILE  = CERT_DIR + "/private.pem.key"

# ── Presence Detection Config ─────────────────────────────────────────────────
PRESENCE_THRESHOLD_CM = 150   # detect presence within 150 cm
SAMPLE_INTERVAL_S     = 5     # publish every 5 seconds
DEBOUNCE_COUNT        = 3     # consecutive reads before state change

# MicroPython's embedded ports may count time from 2000-01-01 instead of 1970-01-01
UNIX_OFFSET = 946684800 if time.gmtime(0)[0] == 2000 else 0

wlan = network.WLAN(network.STA_IF)

# ── Wi-Fi and Clock ───────────────────────────────────────────────────────────
def connect_wifi(timeout_s=20):
    """Join the Wi-Fi network from config.py; raises OSError if it doesn't connect in time."""
    wlan.active(True)
    if wlan.isconnected():
        return
    print("Connecting to Wi-Fi:", config.WIFI_SSID)
    wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    start = time.time()
    while not wlan.isconnected():
        if time.time() - start > timeout_s:
            raise OSError("Wi-Fi connect timed out")
        time.sleep(1)
    print("Wi-Fi connected:", wlan.ifconfig()[0])

def sync_clock(attempts=5):
    """Set the RTC from NTP so timestamps (and the 30-day DynamoDB TTL) are real dates."""
    for _ in range(attempts):
        try:
            ntptime.settime()
            print("Clock synced (UTC):", time.gmtime())
            return True
        except OSError:
            time.sleep(2)
    print("NTP sync failed; the Lambda will use its own time for this data")
    return False

def unix_time():
    return time.time() + UNIX_OFFSET

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
def publish_presence(client, distance, occupied, state_changed):
    """Build and publish JSON payload to AWS IoT Core.

    state_changed is True only on the reading where the debounced state flips,
    so the Lambda alerts once per change instead of on every 5-second reading.
    """
    payload = ujson.dumps({
        "device_id":     THING_NAME,
        "distance_cm":   distance,
        "occupied":      occupied,
        "state_changed": state_changed,
        "timestamp":     unix_time()
    })
    client.publish(MQTT_TOPIC, payload.encode())
    print(f"Published: {payload}")
    led.on() if occupied else led.off()

# ── Main Loop ─────────────────────────────────────────────────────────────────
def main():
    connect_wifi()
    sync_clock()
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

            changed = False
            if consecutive_occupied >= DEBOUNCE_COUNT and not current_state:
                current_state, changed = True, True
            elif consecutive_vacant >= DEBOUNCE_COUNT and current_state:
                current_state, changed = False, True

            # Publish every interval (telemetry for DynamoDB/CloudWatch); only changes trigger alerts
            publish_presence(client, distance, current_state, changed)

            time.sleep(SAMPLE_INTERVAL_S)

        except OSError as e:
            print(f"Network error: {e} — reconnecting")
            time.sleep(5)
            try:
                connect_wifi()
                client = connect_mqtt()
            except OSError as e2:
                print(f"Reconnect failed: {e2}")

if __name__ == "__main__":
    main()
