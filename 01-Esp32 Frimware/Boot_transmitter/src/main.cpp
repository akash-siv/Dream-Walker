#include <Arduino.h>
#include <MPU9250_asukiaaa.h>
#include <esp_now.h>
#include <WiFi.h>

#ifdef _ESP32_HAL_I2C_H_
#define SDA_PIN 21
#define SCL_PIN 22
#endif

// MAC Address of the receiver (edit with the correct address)
uint8_t receiverMAC[] = {0xA0, 0xB7, 0x65, 0x16, 0x55, 0x94};

// Define the data structure without gyroSqrt
typedef struct struct_message {
  float accelX;
  float accelY;
  float accelZ;
  float gyroX;
  float gyroY;
  float gyroZ;
} struct_message;

// Create a structured object
struct_message myData;

// Peer info
esp_now_peer_info_t peerInfo;

// Create an instance of the sensor
MPU9250_asukiaaa mySensor;

// Callback function called when data is sent
void OnDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
  // Only print status if you need to debug
  Serial.print("\r\nLast Packet Send Status:\t");
  Serial.println(status == ESP_NOW_SEND_SUCCESS ? "Success" : "Fail");
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);

  // Initialize the sensor
  #ifdef _ESP32_HAL_I2C_H_ // For ESP32
    Wire.begin(SDA_PIN, SCL_PIN);
    mySensor.setWire(&Wire);
  #endif

  mySensor.beginAccel(ACC_FULL_SCALE_4_G);
  mySensor.beginGyro();

  // Initialize ESP-NOW
  if (esp_now_init() != ESP_OK) {
    Serial.println("Error initializing ESP-NOW");
    return;
  }

  // Register the send callback
  esp_now_register_send_cb(OnDataSent);

  // Register peer
  memcpy(peerInfo.peer_addr, receiverMAC, 6);
  peerInfo.channel = 0;
  peerInfo.encrypt = false;

  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("Failed to add peer");
    return;
  }
}

void loop() {
  // Check if sensor updates are available
  if (mySensor.accelUpdate() != 0 || mySensor.gyroUpdate() != 0) {
    return;  // Skip iteration if data is unavailable
  }

  // Read sensor data
  myData.accelX = mySensor.accelX();
  myData.accelY = mySensor.accelY();
  myData.accelZ = mySensor.accelZ();
  myData.gyroX = mySensor.gyroX();
  myData.gyroY = mySensor.gyroY();
  myData.gyroZ = mySensor.gyroZ();

  // Send the structured data to the receiver via ESP-NOW
  esp_err_t result = esp_now_send(receiverMAC, (uint8_t *)&myData, sizeof(myData));

  if (result != ESP_OK) {
    // Avoid printing every failure, especially in production
    Serial.println("Sending error");
  }

  delay(10); // Send data every 500ms
  Serial.print(mySensor.accelX(), 3); Serial.print(",");
  Serial.print(mySensor.accelY(), 3); Serial.print(",");
  Serial.print(mySensor.accelZ(), 3); Serial.print(",");
  // Serial.print(" | Gyro: ");
  Serial.print(mySensor.gyroX(), 3); Serial.print(",");
  Serial.print(mySensor.gyroY(), 3); Serial.print(",");
  Serial.println(mySensor.gyroZ(), 3);
}
