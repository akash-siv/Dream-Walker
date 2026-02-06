#include <Arduino.h>
#include <MPU9250_asukiaaa.h>
#include <esp_now.h>
#include <WiFi.h>
#include <VR_Walk-in-place_controller_inferencing.h>
#include <BleKeyboard.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

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

// Queue handle (global)
static QueueHandle_t dataQueue = NULL;
#define QUEUE_LENGTH 1   // keep only the latest packet
#define QUEUE_ITEM_SIZE sizeof(struct_message)

MPU9250_asukiaaa mySensor;

uint8_t senderMAC[] = {0x78, 0x42, 0x1C, 0x67, 0x34, 0xF0};

#define TOTAL_FEATURES EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE
float feature_buffer[TOTAL_FEATURES];
size_t feature_idx = 0;

bool isWalking = false; // flag for tracking key state

void print_inference_result(ei_impulse_result_t result);

// ESP-NOW receive callback (runs in WiFi task context)
void OnDataRecv(const uint8_t *mac, const uint8_t *incomingData, int len) {
  // quick checks
  if (memcmp(mac, senderMAC, 6) != 0) return;
  if (len < (int)sizeof(struct_message)) return;

  struct_message msg;
  memcpy(&msg, incomingData, sizeof(msg));

  // Since queue length == 1, overwrite keeps the latest sample.
  // xQueueOverwrite can only be used safely on a 1-item queue.
  if (dataQueue != NULL) {
    xQueueOverwrite(dataQueue, &msg);
  }
}

int raw_feature_get_data(size_t offset, size_t length, float *out_ptr) {
  memcpy(out_ptr, feature_buffer + offset, length * sizeof(float));
  return 0;
}

void setup() {
  Serial.begin(115200);
  while (!Serial);

  Serial.println("Edge Impulse BLE Keyboard Demo (Queue-enabled)");

  bleKeyboard.begin();

  // create queue BEFORE registering callback so callback can safely use it
  dataQueue = xQueueCreate(QUEUE_LENGTH, QUEUE_ITEM_SIZE);
  if (dataQueue == NULL) {
    Serial.println("ERROR: queue creation failed!");
    while (1) { delay(1000); } // fatal
  }

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
  struct_message remoteData; // local consumer buffer
  bool gotPacket = false;

  // Try to receive the latest packet (non-blocking)
  if (dataQueue != NULL) {
    if (xQueueReceive(dataQueue, &remoteData, 0) == pdTRUE) {
      gotPacket = true;
    }
  }

  // read local IMU 
  if (mySensor.accelUpdate() == 0 && mySensor.gyroUpdate() == 0) {
    // success
  } else {
    Serial.println("Failed to read from local IMU");
    return;
  }

  // read current local data into localData variables
  struct_message localData;
  localData.accelX = mySensor.accelX();
  localData.accelY = mySensor.accelY();
  localData.accelZ = mySensor.accelZ();
  localData.gyroX  = mySensor.gyroX();
  localData.gyroY  = mySensor.gyroY();
  localData.gyroZ  = mySensor.gyroZ();

  if (gotPacket) {
    // Append incoming + local features into feature_buffer exactly like before
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
        Serial.println("ERR: Classifier failed!");
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
          Serial.println("Walking detected! Sending 'W'...");
          bleKeyboard.press('w');
          isWalking = true;
        } else if (otherMaxConfidence >= 90.0 && isWalking) {
          Serial.println("Stop detected! Releasing 'W'...");
          bleKeyboard.release('w');
          isWalking = false;
        }
      } else {
        Serial.println("BLE Keyboard not connected!");
      }

      feature_idx = 0;  // Reset buffer after inference
    }
  }


}

void print_inference_result(ei_impulse_result_t result) {
  Serial.printf("\n DSP: %d ms | Inferencing: %d ms | Anomaly: %d ms\n",
                result.timing.dsp,
                result.timing.classification,
                result.timing.anomaly);

  Serial.println("Predictions:");
  for (uint16_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
    Serial.printf(" • %s: %.5f\n",
                  ei_classifier_inferencing_categories[i],
                  result.classification[i].value);
  }

#if EI_CLASSIFIER_HAS_ANOMALY
  Serial.printf("Anomaly: %.3f\n", result.anomaly);
#endif
}
