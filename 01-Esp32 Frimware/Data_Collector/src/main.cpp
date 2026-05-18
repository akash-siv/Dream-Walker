#include <Arduino.h>
#include <MPU9250_asukiaaa.h>
#include <esp_now.h>
#include <WiFi.h>

#ifdef _ESP32_HAL_I2C_H_
#define SDA_PIN 21
#define SCL_PIN 22
#endif

// ── Identity ───────────────────────────────────────────────────────────────
// Change USER_ID before flashing each receiver. "user01", "user02", etc.
#define USER_ID "user01"

// ── Baud rate ──────────────────────────────────────────────────────────────
// At 250 Hz × ~125 bytes/line = ~31 kB/s → needs ≥ 460800 baud.
// 921600 is supported by ESP32 and the CP2102/CH340 USB bridges.
#define BAUD_RATE 921600

// Must match the MAC of the transmitter paired with this receiver.
uint8_t senderMAC[] = {0x78, 0x42, 0x1C, 0x67, 0x34, 0xF0};

typedef struct struct_message {
    float accelX, accelY, accelZ;
    float gyroX,  gyroY,  gyroZ;
} struct_message;

struct_message remoteData;
struct_message localData;

MPU9250_asukiaaa mySensor;

volatile bool remoteDataReceived = false;

void OnDataRecv(const uint8_t *mac, const uint8_t *incomingData, int len) {
    if (memcmp(mac, senderMAC, 6) != 0) return;
    memcpy(&remoteData, incomingData, sizeof(remoteData));
    remoteDataReceived = true;
}

void setup() {
    Serial.begin(BAUD_RATE);

    WiFi.mode(WIFI_STA);
    if (esp_now_init() != ESP_OK) {
        Serial.println("ERR:ESP-NOW init failed");
        return;
    }
    esp_now_register_recv_cb(OnDataRecv);

#ifdef _ESP32_HAL_I2C_H_
    Wire.begin(SDA_PIN, SCL_PIN);
    mySensor.setWire(&Wire);
#endif

    mySensor.beginAccel(ACC_FULL_SCALE_4_G);
    mySensor.beginGyro();

    // The Kafka producer skips lines starting with "HEADER:" but uses it
    // to verify the column order on startup.
    Serial.println(
        "HEADER:user_id,timestamp_ms,"
        "r_accel_x,r_accel_y,r_accel_z,r_gyro_x,r_gyro_y,r_gyro_z,"
        "l_accel_x,l_accel_y,l_accel_z,l_gyro_x,l_gyro_y,l_gyro_z"
    );
}

void loop() {
    // Always keep local IMU up to date so it is ready when remote arrives.
    if (mySensor.accelUpdate() == 0 && mySensor.gyroUpdate() == 0) {
        localData.accelX = mySensor.accelX();
        localData.accelY = mySensor.accelY();
        localData.accelZ = mySensor.accelZ();
        localData.gyroX  = mySensor.gyroX();
        localData.gyroY  = mySensor.gyroY();
        localData.gyroZ  = mySensor.gyroZ();
    }

    if (!remoteDataReceived) return;
    remoteDataReceived = false;

    // One CSV line per sample: remote leg first, then local leg.
    // Columns match the HEADER line above exactly.
    Serial.printf(
        "%s,%lu,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f\n",
        USER_ID,
        millis(),
        remoteData.accelX, remoteData.accelY, remoteData.accelZ,
        remoteData.gyroX,  remoteData.gyroY,  remoteData.gyroZ,
        localData.accelX,  localData.accelY,  localData.accelZ,
        localData.gyroX,   localData.gyroY,   localData.gyroZ
    );
}
