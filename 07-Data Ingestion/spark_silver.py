"""
Databricks Spark Structured Streaming — Delta bronze → feature extraction → Delta silver.

Reads raw samples from the bronze layer, groups them into 4-second
tumbling windows per user, extracts spectral features (replicating
Edge Impulse's Spectral Analysis DSP block), and writes feature rows
to the silver layer.

Trigger mode: availableNow=True
  Processes all new bronze data since the last checkpoint, then exits.
  Schedule this job in Databricks to run periodically (e.g. every hour).
  This is safer than a continuous stream for training data collection
  because windows are always complete before features are computed.
"""

import os

import numpy as np
import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql.functions import col
from pyspark.sql.types import (
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
)

spark = SparkSession.builder.getOrCreate()

# ── Config ─────────────────────────────────────────────────────────────────
BRONZE_PATH       = os.getenv("DELTA_BRONZE_PATH",    "/mnt/dreamwalker/bronze")
SILVER_PATH       = os.getenv("DELTA_SILVER_PATH",    "/mnt/dreamwalker/silver")
CHECKPOINT_SILVER = os.getenv("DELTA_CHECKPOINT_SILVER", "/mnt/dreamwalker/checkpoints/silver")
SAMPLE_RATE       = int(os.getenv("SAMPLE_RATE_HZ",        "250"))
WINDOW_SECS       = int(os.getenv("WINDOW_SIZE_SECONDS",   "4"))
WINDOW_MS         = SAMPLE_RATE * WINDOW_SECS * (1000 // SAMPLE_RATE)  # 4000 ms
MIN_SAMPLES       = (SAMPLE_RATE * WINDOW_SECS) // 2  # drop windows < 50% full

SENSOR_COLS = [
    "r_accel_x", "r_accel_y", "r_accel_z",
    "r_gyro_x",  "r_gyro_y",  "r_gyro_z",
    "l_accel_x", "l_accel_y", "l_accel_z",
    "l_gyro_x",  "l_gyro_y",  "l_gyro_z",
]

# ── Output schema ──────────────────────────────────────────────────────────
# Each sensor column produces 11 features that mirror Edge Impulse's
# Spectral Analysis block: mean, std, rms, peak, p2p, skewness, kurtosis,
# spectral power in low/mid/high bands, and dominant frequency.
_STATS = ["mean", "std", "rms", "peak", "p2p", "skew", "kurt",
          "pwr_low", "pwr_mid", "pwr_high", "dom_freq"]

SILVER_SCHEMA = StructType(
    [
        StructField("user_id",      StringType(), False),
        StructField("label",        StringType(), True),
        StructField("session_id",   StringType(), True),
        StructField("window_id",    LongType(),   False),
        StructField("window_start", LongType(),   False),
        StructField("window_end",   LongType(),   False),
        StructField("n_samples",    LongType(),   False),
    ]
    + [
        StructField(f"{scol}__{stat}", DoubleType(), True)
        for scol in SENSOR_COLS
        for stat in _STATS
    ]
)


def _spectral_features(sig: np.ndarray, fs: int) -> dict:
    """
    Spectral Analysis features matching Edge Impulse's DSP block.
    Bands: low 0-5 Hz, mid 5-15 Hz, high 15-fs/2 Hz.
    """
    n    = len(sig)
    mag  = np.abs(np.fft.rfft(sig)) / n
    freq = np.fft.rfftfreq(n, 1.0 / fs)
    half = fs // 2

    bands = {"low": (0, 5), "mid": (5, 15), "high": (15, half)}
    pwr   = {
        k: float(np.sum(mag[(freq >= lo) & (freq < hi)] ** 2))
        for k, (lo, hi) in bands.items()
    }

    return {
        "mean":     float(np.mean(sig)),
        "std":      float(np.std(sig)),
        "rms":      float(np.sqrt(np.mean(sig ** 2))),
        "peak":     float(np.max(np.abs(sig))),
        "p2p":      float(np.max(sig) - np.min(sig)),
        "skew":     float(pd.Series(sig).skew()),
        "kurt":     float(pd.Series(sig).kurtosis()),
        "pwr_low":  pwr["low"],
        "pwr_mid":  pwr["mid"],
        "pwr_high": pwr["high"],
        "dom_freq": float(freq[np.argmax(mag)]),
    }


def extract_features(pdf: pd.DataFrame) -> pd.DataFrame:
    """
    Pandas UDF (grouped map) called once per (user_id, label, session_id, window_id).
    Sorts samples by device timestamp before computing features.
    Returns an empty DataFrame if the window is too sparse to be useful.
    """
    pdf = pdf.sort_values("timestamp_ms")

    if len(pdf) < MIN_SAMPLES:
        return pd.DataFrame(columns=[f.name for f in SILVER_SCHEMA])

    row: dict = {
        "user_id":      pdf["user_id"].iloc[0],
        "label":        pdf["label"].iloc[0],
        "session_id":   pdf["session_id"].iloc[0],
        "window_id":    int(pdf["window_id"].iloc[0]),
        "window_start": int(pdf["timestamp_ms"].min()),
        "window_end":   int(pdf["timestamp_ms"].max()),
        "n_samples":    len(pdf),
    }

    for scol in SENSOR_COLS:
        sig = pdf[scol].to_numpy(dtype=np.float64)
        for stat, val in _spectral_features(sig, SAMPLE_RATE).items():
            row[f"{scol}__{stat}"] = val

    return pd.DataFrame([row])


# ── Stream ─────────────────────────────────────────────────────────────────
bronze_stream = (
    spark.readStream
         .format("delta")
         .option("ignoreChanges", "true")
         .load(BRONZE_PATH)
)

# window_id = floor(timestamp_ms / WINDOW_MS) — aligns each user's
# samples into independent 4-second buckets using the device clock.
# No cross-user alignment needed; each user_id is grouped separately.
windowed = (
    bronze_stream
    .withColumn("window_id", (col("timestamp_ms") / WINDOW_MS).cast("long"))
    .groupBy("user_id", "label", "session_id", "window_id")
    .applyInPandas(extract_features, schema=SILVER_SCHEMA)
)

(
    windowed
    .writeStream
    .format("delta")
    .outputMode("append")
    .option("checkpointLocation", CHECKPOINT_SILVER)
    .partitionBy("user_id", "label")
    .trigger(availableNow=True)   # process all new bronze, then stop
    .start(SILVER_PATH)
    .awaitTermination()
)
