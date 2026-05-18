"""
Databricks Spark Structured Streaming — Kafka → Delta Lake bronze layer.

Reads raw JSON messages from the Kafka raw topic and appends them to
Delta bronze, partitioned by user_id and label. Runs continuously.

Deploy as a Databricks Job with cluster type "Job Cluster" or attach
to an existing cluster. Environment variables are read from the job's
environment config; for secrets use dbutils.secrets.get() instead.
"""

import os

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, current_timestamp, from_json
from pyspark.sql.types import (
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
)

spark = SparkSession.builder.getOrCreate()

# ── Config ─────────────────────────────────────────────────────────────────
KAFKA_SERVERS      = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
KAFKA_TOPIC_RAW    = os.getenv("KAFKA_TOPIC_RAW",   "dreamwalker.sensor.raw")
BRONZE_PATH        = os.getenv("DELTA_BRONZE_PATH", "/mnt/dreamwalker/bronze")
CHECKPOINT_BRONZE  = os.getenv("DELTA_CHECKPOINT_BRONZE", "/mnt/dreamwalker/checkpoints/bronze")

# ── Message schema (must match kafka_producer.py exactly) ──────────────────
MESSAGE_SCHEMA = StructType([
    StructField("user_id",      StringType(),  False),
    StructField("timestamp_ms", LongType(),    False),
    StructField("r_accel_x",    DoubleType(),  False),
    StructField("r_accel_y",    DoubleType(),  False),
    StructField("r_accel_z",    DoubleType(),  False),
    StructField("r_gyro_x",     DoubleType(),  False),
    StructField("r_gyro_y",     DoubleType(),  False),
    StructField("r_gyro_z",     DoubleType(),  False),
    StructField("l_accel_x",    DoubleType(),  False),
    StructField("l_accel_y",    DoubleType(),  False),
    StructField("l_accel_z",    DoubleType(),  False),
    StructField("l_gyro_x",     DoubleType(),  False),
    StructField("l_gyro_y",     DoubleType(),  False),
    StructField("l_gyro_z",     DoubleType(),  False),
    StructField("session_id",   StringType(),  True),
    StructField("label",        StringType(),  True),
    StructField("ingest_ts",    LongType(),    True),
])

# ── Kafka reader options ───────────────────────────────────────────────────
kafka_opts = {
    "kafka.bootstrap.servers": KAFKA_SERVERS,
    "subscribe":                KAFKA_TOPIC_RAW,
    "startingOffsets":          "latest",
    "failOnDataLoss":           "false",
}

protocol = os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
if protocol != "PLAINTEXT":
    kafka_opts["kafka.security.protocol"] = protocol
    kafka_opts["kafka.sasl.mechanism"]    = os.getenv("KAFKA_SASL_MECHANISM", "PLAIN")
    kafka_opts["kafka.sasl.jaas.config"]  = (
        "org.apache.kafka.common.security.plain.PlainLoginModule required "
        f"username=\"{os.getenv('KAFKA_SASL_USERNAME')}\" "
        f"password=\"{os.getenv('KAFKA_SASL_PASSWORD')}\";"
    )

# ── Stream ─────────────────────────────────────────────────────────────────
raw_stream = (
    spark.readStream
         .format("kafka")
         .options(**kafka_opts)
         .load()
)

bronze_df = (
    raw_stream
    .select(from_json(col("value").cast("string"), MESSAGE_SCHEMA).alias("d"))
    .select("d.*")
    .withColumn("arrived_at", current_timestamp())
)

(
    bronze_df
    .writeStream
    .format("delta")
    .outputMode("append")
    .option("checkpointLocation", CHECKPOINT_BRONZE)
    .partitionBy("user_id", "label")
    .trigger(processingTime="10 seconds")
    .start(BRONZE_PATH)
    .awaitTermination()
)
