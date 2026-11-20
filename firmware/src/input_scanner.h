#pragma once

namespace InputScanner {
// Initialize pins and capture encoder states after the serial startup wait.
void begin();
// Poll matrix keys, encoder clicks, then encoder rotation in tested order.
void scan();
}
