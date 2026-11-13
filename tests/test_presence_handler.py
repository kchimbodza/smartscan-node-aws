"""Unit tests for the Lambda, with boto3 replaced by fakes (no AWS needed). Run: python -m pytest tests"""
import importlib
import sys
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda"))


class FakeTable:
    def __init__(self):
        self.items = []

    def put_item(self, Item):
        self.items.append(Item)


class FakeSns:
    def __init__(self):
        self.messages = []

    def publish(self, **kwargs):
        self.messages.append(kwargs)


@pytest.fixture
def handler(monkeypatch):
    table, sns = FakeTable(), FakeSns()
    fake_boto3 = types.SimpleNamespace(
        resource=lambda name: types.SimpleNamespace(Table=lambda _: table),
        client=lambda name: sns,
    )
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:smartscan-alerts")
    sys.modules.pop("presence_handler", None)
    module = importlib.import_module("presence_handler")
    return module, table, sns


def reading(occupied, changed, ts=None):
    return {"device_id": "smartscan-node-aws-01", "distance_cm": 87.3,
            "occupied": occupied, "state_changed": changed,
            "timestamp": int(time.time()) if ts is None else ts}


def test_one_alert_per_state_change_not_per_reading(handler):
    module, table, sns = handler
    # vacant -> occupied, 10 more occupied readings (50 s), then occupied -> vacant
    events = [reading(True, True)] + [reading(True, False)] * 10 + [reading(False, True)]
    for e in events:
        module.lambda_handler(e, None)
    assert len(table.items) == 12                     # every reading is stored
    assert [m["Subject"] for m in sns.messages] == ["SmartScan: Room Occupied", "SmartScan: Room Vacant"]


def test_device_clock_not_set_falls_back_to_lambda_time(handler):
    module, table, _ = handler
    module.lambda_handler(reading(True, False, ts=1234), None)   # ESP32 without NTP: seconds since boot
    item = table.items[0]
    assert item["time_source"] == "lambda"
    assert abs(item["epoch"] - time.time()) < 5
    assert item["ttl"] == item["epoch"] + 30 * 86400


def test_valid_device_time_is_kept(handler):
    module, table, _ = handler
    ts = int(time.time()) - 60
    module.lambda_handler(reading(False, False, ts=ts), None)
    assert table.items[0]["epoch"] == ts and table.items[0]["time_source"] == "device"


def test_old_payload_without_state_changed_does_not_alert(handler):
    module, _, sns = handler
    event = reading(True, False)
    del event["state_changed"]
    module.lambda_handler(event, None)
    assert sns.messages == []
