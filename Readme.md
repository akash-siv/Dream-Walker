# Low-Cost Wearable Solution for Mitigating VR Motion Sickness

## Project Summary
This project presents a low-cost wearable leg device leveraging embedded Tiny Machine Learning (TinyML) to mitigate Virtual Reality (VR) motion sickness by enabling standing-based locomotion control.

## Main Contributions
- Custom IMU dataset collected from 4 participants.
- Preprocessing using frequency-domain (FFT) and statistical feature extraction.
- Lightweight Deep Neural Network (DNN) trained and optimized for microcontroller deployment.
- End-to-end system achieving ~85% macro F1 score with under 100ms latency.
- Custom SteamVR driver integration with Bluetooth HID communication.

## Folder Structure


Project Summary:
----------------
This project presents a low-cost wearable leg device leveraging embedded Tiny Machine Learning (TinyML) to mitigate Virtual Reality (VR) motion sickness by enabling standing-based locomotion control.

Main Contributions:
--------------------
- Custom IMU dataset collected from 4 participants.
- Preprocessing using frequency-domain (FFT) and statistical feature extraction.
- Lightweight Deep Neural Network (DNN) trained and optimized for microcontroller deployment.
- End-to-end system achieving ~85% macro F1 score with under 100ms latency.
- Custom SteamVR driver integration with Bluetooth HID communication.

Folder Structure:
-----------------
/code/
    - Source code files for data collection, preprocessing, model training, and embedded deployment.

\dataset\
    - IMU raw data files collected from participants (organized by activity).

/driver/
    - SteamVR driver source files for mapping wearable input to VR locomotion.

system_architecture.png
    - System architecture diagram used in the final report.

AI_project_report.pdf
    - Final IEEE-formatted project report.

Instructions:
-------------
1. To reproduce the model training:
    - Run the provided training scripts inside the `/code/` directory.
    - Model training was conducted using TensorFlow and converted to TensorFlow Lite Micro format.

2. To deploy the model:
    - Flash the exported `.tflite` model to a compatible microcontroller (e.g., ARM Cortex-M series).
    - Use the Bluetooth HID firmware to transmit classified activities.

3. To integrate with VR:
    - Build and install the SteamVR driver provided in the `/driver/` folder.
    - Ensure Bluetooth pairing between the wearable device and VR PC.

Authors:
--------
- Dhanush Balamurali (dhanushbalamurali@trentu.ca)
- Akash Sivasubramanian (akashsivasubramanian@trentu.ca)

Submission:
-----------
- This work is submitted as part of the AMOD Artificial Intelligence Project at Trent University, Peterborough, Canada.
- Submission includes all code, dataset, report, and driver files as required.


