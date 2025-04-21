#include <Arduino.h>
#include <MPU9250_asukiaaa.h>
#include <esp_now.h>
#include <WiFi.h>
#include <VR_Walk-in-place_controller_inferencing.h>
#include <BleKeyboard.h>

#ifdef _ESP32_HAL_I2C_H_
#define SDA_PIN 21
#define SCL_PIN 22
#endif

BleKeyboard bleKeyboard("Dream Walker");

// Data structure for sensor readings
typedef struct struct_message {
  float accelX, accelY, accelZ;
  float gyroX, gyroY, gyroZ;
} struct_message;

struct_message remoteData;
struct_message localData;

MPU9250_asukiaaa mySensor;

uint8_t senderMAC[] = {0x78, 0x42, 0x1C, 0x67, 0x34, 0xF0};

volatile bool remoteDataReceived = false;

#define TOTAL_FEATURES EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE
float feature_buffer[TOTAL_FEATURES];
size_t feature_idx = 0;

bool isWalking = false; // flag for tracking key state

void OnDataRecv(const uint8_t *mac, const uint8_t *incomingData, int len) {
  if (memcmp(mac, senderMAC, 6) != 0) return;
  memcpy(&remoteData, incomingData, sizeof(remoteData));
  remoteDataReceived = true;
}

int raw_feature_get_data(size_t offset, size_t length, float *out_ptr) {
  memcpy(out_ptr, feature_buffer + offset, length * sizeof(float));
  return 0;
}

void print_inference_result(ei_impulse_result_t result); // prototype

void setup() {
  Serial.begin(115200);
  while (!Serial);

  Serial.println("🚀 Edge Impulse BLE Keyboard Demo");

  bleKeyboard.begin();

  WiFi.mode(WIFI_STA);
  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init failed!");
    return;
  }
  esp_now_register_recv_cb(OnDataRecv);

#ifdef _ESP32_HAL_I2C_H_
  Wire.begin(SDA_PIN, SCL_PIN);
  mySensor.setWire(&Wire);
#endif

  mySensor.beginAccel(ACC_FULL_SCALE_4_G);
  mySensor.beginGyro();
}

void loop() {
  if (mySensor.accelUpdate() == 0 && mySensor.gyroUpdate() == 0) {
    localData.accelX = mySensor.accelX();
    localData.accelY = mySensor.accelY();
    localData.accelZ = mySensor.accelZ();
    localData.gyroX  = mySensor.gyroX();
    localData.gyroY  = mySensor.gyroY();
    localData.gyroZ  = mySensor.gyroZ();
  }

  if (remoteDataReceived) {
    remoteDataReceived = false;

    if (feature_idx + 12 <= TOTAL_FEATURES) {
      feature_buffer[feature_idx++] = remoteData.accelX;
      feature_buffer[feature_idx++] = remoteData.accelY;
      feature_buffer[feature_idx++] = remoteData.accelZ;
      feature_buffer[feature_idx++] = remoteData.gyroX;
      feature_buffer[feature_idx++] = remoteData.gyroY;
      feature_buffer[feature_idx++] = remoteData.gyroZ;

      feature_buffer[feature_idx++] = localData.accelX;
      feature_buffer[feature_idx++] = localData.accelY;
      feature_buffer[feature_idx++] = localData.accelZ;
      feature_buffer[feature_idx++] = localData.gyroX;
      feature_buffer[feature_idx++] = localData.gyroY;
      feature_buffer[feature_idx++] = localData.gyroZ;
    }

    if (feature_idx >= TOTAL_FEATURES) {
      ei_impulse_result_t result = {0};
      signal_t features_signal;
      features_signal.total_length = TOTAL_FEATURES;
      features_signal.get_data = &raw_feature_get_data;

      EI_IMPULSE_ERROR res = run_classifier(&features_signal, &result, false);
      if (res != EI_IMPULSE_OK) {
        Serial.println("❌ ERR: Classifier failed!");
        feature_idx = 0;
        return;
      }

      print_inference_result(result);

      float walkConfidence = 0;
      float otherMaxConfidence = 0;

      for (uint16_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
        String label = String(ei_classifier_inferencing_categories[i]);
        float value = result.classification[i].value * 100;

        if (label.equalsIgnoreCase("walk")) {
          walkConfidence = value;
        } else {
          otherMaxConfidence = max(otherMaxConfidence, value);
        }
      }

      // BLE Keyboard Logic
      if (bleKeyboard.isConnected()) {
        if (walkConfidence >= 90.0 && !isWalking) {
          Serial.println("🚶‍♂️ Walking detected! Sending 'W'...");
          bleKeyboard.press('w');
          isWalking = true;
        } else if (otherMaxConfidence >= 90.0 && isWalking) {
          Serial.println("🛑 Stop detected! Releasing 'W'...");
          bleKeyboard.release('w');
          isWalking = false;
        }
      } else {
        Serial.println("⚠️ BLE Keyboard not connected!");
      }

      feature_idx = 0;  // Reset buffer after inference
    }
  }
}

void print_inference_result(ei_impulse_result_t result) {
  Serial.printf("\n⏱️ DSP: %d ms | Inferencing: %d ms | Anomaly: %d ms\n",
                result.timing.dsp,
                result.timing.classification,
                result.timing.anomaly);

  Serial.println("✅ Predictions:");
  for (uint16_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
    Serial.printf(" • %s: %.5f\n",
                  ei_classifier_inferencing_categories[i],
                  result.classification[i].value);
  }

#if EI_CLASSIFIER_HAS_ANOMALY
  Serial.printf("⚠️ Anomaly: %.3f\n", result.anomaly);
#endif
}

// Todo 1: Add battery level monitoring for each device. send the least battery level of the two device as a hid native battery persentage.
// Todo 2: Reduce flash memory usage.
