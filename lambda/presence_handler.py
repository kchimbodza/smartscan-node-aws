"""
SmartScan Node - AWS Lambda Function
Triggered by AWS IoT Core rule on topic: smartscan/presence
Writes occupancy data to DynamoDB, publishes alerts via SNS when the room's state changes
"""

import json
import boto3
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

dynamodb = boto3.resource("dynamodb")
sns      = boto3.client("sns")

TABLE_NAME   = os.environ.get("DYNAMODB_TABLE", "smartscan-occupancy")
SNS_TOPIC    = os.environ.get("SNS_TOPIC_ARN", "")
ALERT_ENABLE = os.environ.get("ALERT_ENABLED", "true").lower() == "true"

TTL_SECONDS   = 86400 * 30          # keep readings for 30 days
MIN_VALID_TS  = 1577836800          # 2020-01-01: anything earlier means the device clock isn't set
MAX_CLOCK_SKEW = 300                # device timestamps more than 5 min in the future are rejected

table = dynamodb.Table(TABLE_NAME)


def event_time(device_ts, now):
    """Use the device's timestamp if its clock looks right, otherwise the Lambda's own time."""
    if isinstance(device_ts, (int, float)) and MIN_VALID_TS <= device_ts <= now + MAX_CLOCK_SKEW:
        return int(device_ts), "device"
    return int(now), "lambda"


def lambda_handler(event, context):
    """
    Event payload from IoT Core rule:
    {
        "device_id":     "smartscan-node-aws-01",
        "distance_cm":   87.3,
        "occupied":      true,
        "state_changed": true,
        "timestamp":     1714204800
    }
    """
    print(f"Received event: {json.dumps(event)}")

    device_id     = event.get("device_id", "unknown")
    distance_cm   = Decimal(str(event.get("distance_cm", 0)))
    occupied      = bool(event.get("occupied", False))
    state_changed = bool(event.get("state_changed", False))
    ts, ts_source = event_time(event.get("timestamp"), time.time())

    iso_time = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    # ── Write to DynamoDB ─────────────────────────────────────────────────────
    item = {
        "device_id":     device_id,
        "timestamp":     iso_time,
        "epoch":         ts,
        "time_source":   ts_source,
        "distance_cm":   distance_cm,
        "occupied":      occupied,
        "state_changed": state_changed,
        "ttl":           ts + TTL_SECONDS,
    }

    table.put_item(Item=item)
    print(f"DynamoDB write: device={device_id}, occupied={occupied}, changed={state_changed}, "
          f"distance={distance_cm}cm, time from {ts_source}")

    # ── SNS Alert on Occupancy Change ─────────────────────────────────────────
    # The device sends a reading every 5 s; only the reading where the state flips is alerted.
    alerted = False
    if ALERT_ENABLE and SNS_TOPIC and state_changed:
        status = "OCCUPIED" if occupied else "VACANT"
        message = (
            f"SmartScan Alert\n"
            f"Device: {device_id}\n"
            f"Status: {status}\n"
            f"Distance: {distance_cm} cm\n"
            f"Time: {iso_time}"
        )
        sns.publish(
            TopicArn=SNS_TOPIC,
            Subject=f"SmartScan: Room {status.capitalize()}",
            Message=message
        )
        alerted = True
        print(f"SNS alert published for {device_id}: {status}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "device_id": device_id,
            "occupied":  occupied,
            "written":   True,
            "alerted":   alerted,
        })
    }
