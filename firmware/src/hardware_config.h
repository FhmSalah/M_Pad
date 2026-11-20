#pragma once

namespace Hardware {
constexpr int KEY_ROW_COUNT = 3;
constexpr int COLUMN_COUNT = 4;
constexpr int ENCODER_COUNT = 2;
constexpr int KEY_ROWS[KEY_ROW_COUNT] = {10, 20, 21};
constexpr int COLUMNS[COLUMN_COUNT] = {8, 2, 1, 0};
constexpr int CLICK_ROW = 7;
constexpr int LEFT_CLICK_COLUMN = 0;
constexpr int RIGHT_CLICK_COLUMN = 3;

struct EncoderPins {
  int a;
  int b;
};
// Left/front encoder first, right/front encoder second.
constexpr EncoderPins ENCODERS[ENCODER_COUNT] = {{5, 6}, {3, 4}};

constexpr unsigned long SERIAL_BAUD = 115200;
constexpr unsigned long SERIAL_STARTUP_MS = 1500;
constexpr unsigned long SWITCH_DEBOUNCE_MS = 15;
constexpr unsigned int MATRIX_SETTLE_US = 50;
constexpr int ENCODER_TRANSITIONS_PER_DETENT = 4;
}
