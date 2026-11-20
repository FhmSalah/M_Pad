#include <Arduino.h>
#include <cstring>

#include "hardware_config.h"
#include "input_scanner.h"

namespace {
constexpr size_t COMMAND_BUFFER_SIZE = 5;  // WHO + optional CR + terminator.
constexpr int SERIAL_BYTES_PER_LOOP = 16;
char commandBuffer[COMMAND_BUFFER_SIZE];
size_t commandLength = 0;
bool commandOverflow = false;

void pollSerialCommands() {
  // Bound work per loop so incoming traffic cannot starve input scanning.
  for (int count = 0;
       count < SERIAL_BYTES_PER_LOOP && Serial.available() > 0; ++count) {
    const int received = Serial.read();
    if (received < 0) {
      break;
    }
    const char character = static_cast<char>(received);

    if (character == '\n') {
      if (!commandOverflow) {
        // Remove only a trailing CR to accept CRLF as well as LF.
        if (commandLength > 0 && commandBuffer[commandLength - 1] == '\r') {
          --commandLength;
        }
        commandBuffer[commandLength] = '\0';
        if (commandLength == 3 && std::strcmp(commandBuffer, "WHO") == 0) {
          Serial.println("MACROPAD:V1");
        }
      }
      commandLength = 0;
      commandOverflow = false;
    } else if (!commandOverflow) {
      if (commandLength < sizeof(commandBuffer) - 1) {
        commandBuffer[commandLength++] = character;
      } else {
        // Discard the whole oversized line, including any command suffix.
        commandOverflow = true;
      }
    }
  }
}
}

void setup() {
  Serial.begin(Hardware::SERIAL_BAUD);
  delay(Hardware::SERIAL_STARTUP_MS);
  InputScanner::begin();
  Serial.println("READY");
}

void loop() {
  InputScanner::scan();
  pollSerialCommands();
}
