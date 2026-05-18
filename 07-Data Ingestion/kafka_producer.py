"""
Reads raw IMU CSV lines from one or more ESP32 receivers over serial
and publishes each sample as a JSON message to the Kafka raw topic.

Each receiver maps to one serial port. Run one process per receiver,
or pass multiple ports via --ports COM3 COM4 COM5 ... to fan them out
in parallel threads within a single process.

Usage:
    python kafka_producer.py                        # uses .env defaults
    python kafka_producer.py --ports COM3 COM4      # two users in parallel
"""

import argparse
import json
import os
import threading
import time
from typing import Optional

import serial
from dotenv import load_dotenv
from kafka import KafkaProducer
from kafka.errors import KafkaError

load_dotenv()

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC_RAW         = os.getenv("KAFKA_TOPIC_RAW",  "dreamwalker.sensor.raw")
SERIAL_PORT             = os.getenv("SERIAL_PORT",      "COM3")
SERIAL_BAUD_RATE        = int(os.getenv("SERIAL_BAUD_RATE", "921600"))
SESSION_LABEL           = os.getenv("SESSION_LABEL",    "idle")
SESSION_ID              = os.getenv("SESSION_ID",       "session_001")

COLUMNS = [
    "user_id", "timestamp_ms",
    "r_accel_x", "r_accel_y", "r_accel_z",
    "r_gyro_x",  "r_gyro_y",  "r_gyro_z",
    "l_accel_x", "l_accel_y", "l_accel_z",
    "l_gyro_x",  "l_gyro_y",  "l_gyro_z",
]


def build_producer() -> KafkaProducer:
    kwargs = dict(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
        acks=1,
        linger_ms=5,       # micro-batch up to 5 ms to ease broker load at 250 Hz
        batch_size=16384,
        retries=3,
    )
    protocol = os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
    if protocol != "PLAINTEXT":
        kwargs["security_protocol"] = protocol
        kwargs["sasl_mechanism"]    = os.getenv("KAFKA_SASL_MECHANISM", "PLAIN")
        kwargs["sasl_plain_username"] = os.getenv("KAFKA_SASL_USERNAME", "")
        kwargs["sasl_plain_password"] = os.getenv("KAFKA_SASL_PASSWORD", "")
    return KafkaProducer(**kwargs)


def parse_line(line: str) -> Optional[dict]:
    line = line.strip()
    if not line or line.startswith("HEADER:") or line.startswith("ERR:"):
        return None
    parts = line.split(",")
    if len(parts) != len(COLUMNS):
        return None
    try:
        row = dict(zip(COLUMNS, parts))
        row["timestamp_ms"] = int(row["timestamp_ms"])
        for col in COLUMNS[2:]:
            row[col] = float(row[col])
        row["session_id"] = SESSION_ID
        row["label"]      = SESSION_LABEL
        row["ingest_ts"]  = int(time.time() * 1000)
        return row
    except (ValueError, KeyError):
        return None


def stream_port(port: str, producer: KafkaProducer, stop_event: threading.Event) -> None:
    print(f"[{port}] opening at {SERIAL_BAUD_RATE} baud → topic {KAFKA_TOPIC_RAW}")
    dropped = 0
    published = 0

    try:
        ser = serial.Serial(port, SERIAL_BAUD_RATE, timeout=1)
    except serial.SerialException as e:
        print(f"[{port}] ERROR: {e}")
        return

    try:
        while not stop_event.is_set():
            raw = ser.readline().decode("utf-8", errors="ignore")
            msg = parse_line(raw)
            if msg is None:
                dropped += 1
                continue
            try:
                producer.send(
                    KAFKA_TOPIC_RAW,
                    key=msg["user_id"],   # partition key preserves per-user order
                    value=msg,
                )
                published += 1
                if published % 2500 == 0:   # log every ~10 s at 250 Hz
                    print(f"[{port}] user={msg['user_id']} published={published} dropped={dropped}")
            except KafkaError as e:
                print(f"[{port}] Kafka send error: {e}")
    finally:
        ser.close()
        print(f"[{port}] closed — published={published} dropped={dropped}")


def main() -> None:
    parser = argparse.ArgumentParser(description="ESP32 → Kafka producer")
    parser.add_argument(
        "--ports", nargs="+", default=[SERIAL_PORT],
        help="Serial ports, one per user (e.g. COM3 COM4)"
    )
    args = parser.parse_args()

    producer    = build_producer()
    stop_event  = threading.Event()
    threads     = []

    for port in args.ports:
        t = threading.Thread(
            target=stream_port, args=(port, producer, stop_event), daemon=True
        )
        t.start()
        threads.append(t)

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\nStopping...")
        stop_event.set()
    finally:
        producer.flush()
        producer.close()


if __name__ == "__main__":
    main()
