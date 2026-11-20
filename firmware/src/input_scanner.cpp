#include <Arduino.h>

#include "hardware_config.h"
#include "input_scanner.h"

namespace {
struct DebouncedSwitch {
  bool rawState = false;
  bool stableState = false;
  unsigned long changedAt = 0;
};

struct EncoderState {
  int lastState = 0;
  int accumulator = 0;
};

DebouncedSwitch keys[Hardware::KEY_ROW_COUNT][Hardware::COLUMN_COUNT];
DebouncedSwitch encoderClicks[Hardware::ENCODER_COUNT];
EncoderState encoders[Hardware::ENCODER_COUNT];

constexpr int8_t TRANSITION_TABLE[16] = {
   0, -1,  1,  0,
   1,  0,  0, -1,
  -1,  0,  0,  1,
   0,  1, -1,  0
};
constexpr const char* CLICK_EVENTS[Hardware::ENCODER_COUNT] = {
  "ENC1:PRESS", "ENC2:PRESS"
};
constexpr const char* CLOCKWISE_EVENTS[Hardware::ENCODER_COUNT] = {
  "ENC1:CW", "ENC2:CW"
};
constexpr const char* COUNTERCLOCKWISE_EVENTS[Hardware::ENCODER_COUNT] = {
  "ENC1:CCW", "ENC2:CCW"
};

bool updateSwitch(DebouncedSwitch& sw, bool newRawState) {
  const unsigned long now = millis();
  if (newRawState != sw.rawState) {
    sw.rawState = newRawState;
    sw.changedAt = now;
  }
  if (sw.stableState != sw.rawState &&
      now - sw.changedAt >= Hardware::SWITCH_DEBOUNCE_MS) {
    sw.stableState = sw.rawState;
    // Emit only the debounced press, never the release.
    if (sw.stableState) {
      return true;
    }
  }
  return false;
}

void scanMatrix() {
  for (int row = 0; row < Hardware::KEY_ROW_COUNT; ++row) {
    digitalWrite(Hardware::KEY_ROWS[row], LOW);
    pinMode(Hardware::KEY_ROWS[row], OUTPUT);
    delayMicroseconds(Hardware::MATRIX_SETTLE_US);
    for (int column = 0; column < Hardware::COLUMN_COUNT; ++column) {
      const bool pressed = digitalRead(Hardware::COLUMNS[column]) == LOW;
      if (updateSwitch(keys[row][column], pressed)) {
        const int keyNumber = row * Hardware::COLUMN_COUNT + column + 1;
        Serial.print("KEY:");
        Serial.println(keyNumber);
      }
    }
    // Inactive rows float, matching the tested matrix scan.
    pinMode(Hardware::KEY_ROWS[row], INPUT);
  }

  digitalWrite(Hardware::CLICK_ROW, LOW);
  pinMode(Hardware::CLICK_ROW, OUTPUT);
  delayMicroseconds(Hardware::MATRIX_SETTLE_US);
  const bool leftPressed =
      digitalRead(Hardware::COLUMNS[Hardware::LEFT_CLICK_COLUMN]) == LOW;
  const bool rightPressed =
      digitalRead(Hardware::COLUMNS[Hardware::RIGHT_CLICK_COLUMN]) == LOW;
  if (updateSwitch(encoderClicks[0], leftPressed)) {
    Serial.println(CLICK_EVENTS[0]);
  }
  if (updateSwitch(encoderClicks[1], rightPressed)) {
    Serial.println(CLICK_EVENTS[1]);
  }
  pinMode(Hardware::CLICK_ROW, INPUT);
}

int readEncoderState(const Hardware::EncoderPins& pins) {
  return (digitalRead(pins.a) << 1) | digitalRead(pins.b);
}

void scanEncoder(int index) {
  EncoderState& encoder = encoders[index];
  const int currentState = readEncoderState(Hardware::ENCODERS[index]);
  if (currentState == encoder.lastState) {
    return;
  }
  const int transition = (encoder.lastState << 2) | currentState;
  encoder.accumulator += TRANSITION_TABLE[transition];
  encoder.lastState = currentState;
  // Physically confirmed for both encoders: negative means clockwise.
  if (encoder.accumulator <= -Hardware::ENCODER_TRANSITIONS_PER_DETENT) {
    Serial.println(CLOCKWISE_EVENTS[index]);
    encoder.accumulator = 0;
  } else if (encoder.accumulator >= Hardware::ENCODER_TRANSITIONS_PER_DETENT) {
    Serial.println(COUNTERCLOCKWISE_EVENTS[index]);
    encoder.accumulator = 0;
  }
}
}

namespace InputScanner {
void begin() {
  for (int column = 0; column < Hardware::COLUMN_COUNT; ++column) {
    pinMode(Hardware::COLUMNS[column], INPUT_PULLUP);
  }
  for (int row = 0; row < Hardware::KEY_ROW_COUNT; ++row) {
    pinMode(Hardware::KEY_ROWS[row], INPUT);
  }
  pinMode(Hardware::CLICK_ROW, INPUT);
  for (int index = 0; index < Hardware::ENCODER_COUNT; ++index) {
    pinMode(Hardware::ENCODERS[index].a, INPUT_PULLUP);
    pinMode(Hardware::ENCODERS[index].b, INPUT_PULLUP);
  }
  for (int index = 0; index < Hardware::ENCODER_COUNT; ++index) {
    encoders[index].lastState = readEncoderState(Hardware::ENCODERS[index]);
  }
}

void scan() {
  scanMatrix();
  scanEncoder(0);
  scanEncoder(1);
}
}
