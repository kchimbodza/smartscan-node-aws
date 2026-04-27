"""
SmartScan Node - AWS Lambda Function
Triggered by AWS IoT Core rule on topic: smartscan/presence
Writes occupancy data to DynamoDB, publishes alerts via SNS
"""

import json
import boto3
import os
from datetime import datetime, timezone
from decimal import Decimal

dynamodb = boto3.resource("dynamodb")
sns      = boto3.client("sns")

TABLE_NAME   = os.environ.get("DYNAMODB_TABLE", "smartscan-occupancy")
SNS_TOPIC    = os.environ.get("SNS_TOPIC_ARN", "")
ALERT_ENABLE = os.environ.get("ALERT_ENABLED", "true").lower() == "true"

table = dynamodb.Table(TABLE_NAME)


def lambda_handler(event, context):
    """
    Event payload from IoT Core rule:
    {
        "device_id":   "smartscan-node-01",
        "distance_cm": 87.3,
        "occupied":    true,
        "timestamp":   1714204800
    }
    """
    print(f"Received event: {json.dumps(event)}")

    device_id   = event.get("device_id", "unknown")
    distance_cm = Decimal(str(event.get("distance_cm", 0)))
    occupied    = event.get("occupied", False)
    ts          = event.get("timestamp", 0)

    # ISO timestamp for readability
    iso_time = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else datetime.now(timezone.utc).isoformat()

    # ── Write to DynamoDB ─────────────────────────────────────────────────────
    item = {
        "device_id":   device_id,
        "timestamp":   iso_time,
        "epoch":       ts,
        "distance_cm": distance_cm,
        "occupied":    occupied,
        "ttl":         ts + 86400 * 30   # 30-day TTL
    }

    table.put_item(Item=item)
    print(f"DynamoDB write: device={device_id}, occupied={occupied}, distance={distance_cm}cm")

    # ── SNS Alert on Occupancy Change ─────────────────────────────────────────
    if ALERT_ENABLE and SNS_TOPIC and occupied:
        message = (
            f"SmartScan Alert\n"
            f"Device: {device_id}\n"
            f"Status: {'OCCUPIED' if occupied else 'VACANT'}\n"
            f"Distance: {distance_cm} cm\n"
            f"Time: {iso_time}"
        )
        sns.publish(
            TopicArn=SNS_TOPIC,
            Subject=f"SmartScan: Room {'Occupied' if occupied else 'Vacant'}",
            Message=message
        )
        print(f"SNS alert published for {device_id}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "device_id": device_id,
            "occupied":  occupied,
            "written":   True
        })
    }
