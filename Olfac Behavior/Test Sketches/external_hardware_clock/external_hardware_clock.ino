/*
Author: Chase Johnston
Date: April 5th, 2026
Purpose:
  Tinkering with an idea that might solve our desync problem...
*/

/* Macros */
#define BF_START_SESSION 221
#define BF_END_SESSION 246

/* Constants */
const int baudRate                  =  115200;  // Baud rate for communication with MatLab via serial port
const int pollingRate               =  2;       // Polling rate for our IR sensors (in ms)

/* Global Variables */
bool sessionComplete                = false;    // Flag for end of session
volatile uint32_t t5_overflowCount  = 0;        // Timer5 overflow tracking (file scope)

// This interrupt fires every time Timer5's 16-bit counter wraps around.
// "volatile" tells the compiler that t5_overflowCount can change at any
// time (from inside this ISR), so it must always re-read it from RAM.
ISR(TIMER5_OVF_vect) {
  t5_overflowCount++;
}

/* Trial Timing */
struct TrialClock {
  uint32_t recStart = 0;                        // Tick count at session start
  uint32_t currentTS = 0;                       // Most recent tick count

  void initHardware() {
    noInterrupts();  // Disable all interrupts while we configure

    /* Clear Timer 5's control registers, setting it to "normal" mode */
    /* (counts up and overflows) */
    TCCR5A = 0;
    TCCR5B = 0;

    /* Zero the actual 16-bit counter register, starting from known state */
    TCNT5 = 0;

    /* Reset our overflow counter variable */
    t5_overflowCount = 0;

    // ---- Select the external clock source ----
    // The Clock Select bits CS52, CS51, CS50 in TCCR5B choose what
    // drives the counter. The options are:
    //
    //   CS52  CS51  CS50   Source
    //   ----  ----  ----   ------
    //    0     0     0     Stopped (no clock)          <-- reset state
    //    0     0     1     Internal clk (16 MHz)
    //    0     1     0     Internal clk / 8
    //    0     1     1     Internal clk / 64
    //    1     0     0     Internal clk / 256
    //    1     0     1     Internal clk / 1024
    //    1     1     0     External on T5, FALLING edge
    //    1     1     1     External on T5, RISING edge  <-- we want this
    //
    // We set all three bits to 1 for external clock, rising edge.
    // The T5 pin is PL2 on the ATmega2560, which is Arduino Mega pin 47.
    // From this moment, every rising edge of the Intan's 30 kHz clock-out
    // increments TCNT5 by 1.
    TCCR5B = (1 << CS52) | (1 << CS51) | (1 << CS50);

    // ---- Enable the overflow interrupt ----
    // TIMSK5 is the interrupt mask register for Timer5.
    // Setting the TOIE5 bit tells the chip to fire ISR(TIMER5_OVF_vect)
    // every time TCNT5 wraps from 65535 to 0.
    TIMSK5 = (1 << TOIE5);

    interrupts();  // Re-enable interrupts
  }

  /* Read the full 32-bit tick count from Timer 5, combining the 16-bit hardware 
      counter with our overflow counter to get a continuous count.
  */
  uint32_t readTicks() {
    noInterrupts();
    uint16_t count = TCNT5;           // Read hardware counter
    uint32_t ovf = t5_overflowCount;  // Read overflow counter

    // RACE CONDITION CHECK:
    // There's a subtle problem. What if the counter overflowed
    // *after* we read TCNT5 but *before* we read t5_overflowCount?
    // Then ovf would be one too high for the count we captured.
    //
    // Conversely, what if it overflowed *before* we read TCNT5 but
    // the ISR hasn't run yet? Then ovf is one too low.
    //
    // We detect the second case by checking TIFR5's TOV5 flag.
    // This flag is set by hardware the instant an overflow occurs,
    // even before the ISR runs. If it's set AND our count is small
    // (meaning we read TCNT5 *after* it wrapped), we need to add 1
    // to ovf.
    if ((TIFR5 & (1 << TOV5)) && count < 0x8000) {
      ovf++;
    }

    interrupts();

    return (ovf << 16) | count;
    // Bit-shift explanation:
    //   ovf << 16 moves the overflow count into the upper 16 bits
    //   | count   places the hardware counter in the lower 16 bits
    //   Together they form one continuous 32-bit tick count.
  }

  // Convert a tick count to milliseconds.
  // At 30 kHz, each tick = 1/30000 s = 0.03333... ms
  // So: ms = ticks * 1000 / 30000 = ticks / 30
  //
  // We use integer division, which truncates. This gives ~0.033 ms
  // resolution — well under 1 ms, so the result is the floor of
  // the true millisecond value.
  uint32_t ticksToMs(uint32_t ticks) {
    return ticks / 30;
  }

  void beginSession() {
    recStart = readTicks();
    currentTS = recStart;
  }

  // Returns elapsed time in milliseconds since beginSession()
  unsigned long elapsed() {
    uint32_t ticks = readTicks();
    currentTS = ticks;
    return ticksToMs(ticks - recStart);
  }
};

TrialClock trialClock;                         // Encapsulates the logic for trial timestamps

/*===================== Pin-mapping for Arduino =====================*/
/* Intan Mark-out Input Pin */
const int intanMarkOut  = 8;  // 5V Intan mark-out signal
const int intanTimeSync = 9;  // Digital output signal for time synchronization with Intan

/* Housekeeping for starting a new experiment session */
void beginNewSession() {
  sessionComplete = false;
  trialClock.beginSession();
  recordEvent(BF_START_SESSION);                  // Mark start of session in MatLab
}

/* Housekeeping for ending the current experiment session */
void endCurrentSession() {
  sessionComplete = true;
  recordEvent(BF_END_SESSION);
}

/*  void recordEvent(int eventCode) {...} ->
  Given an eventCode (an int), outputs the code in a standardized 3-digit format.

  Handles sending eventCode and a timestamp to MatLab.
  
  Also handles sending a short digital 5V pulse to a recording                         // [CNJ: 04/03/2026]
   controller (if you have one connected).  
*/
void recordEvent(int eventCode) {
  unsigned long timestamp = trialClock.elapsed();
  char buf[16];

  digitalWrite(intanTimeSync, HIGH);              // Pulse Intan recording controller
  delay(pollingRate);
  digitalWrite(intanTimeSync, LOW);

  sprintf(buf, "%03d\t%lu", eventCode, timestamp);// Store print line to MatLab in a buffer
  Serial.println(buf);                            // Print buffer to serial
}

void setup() {
  pinMode(intanMarkOut, INPUT);
  pinMode(intanTimeSync, OUTPUT);
  sessionComplete = true;                         // This causes our main loop to wait for Intan mark out to run behavior
  Serial.begin(baudRate);                         // Initialize serial com with baud rate 115200 (MatLab default)
  trialClock.initHardware();
}

void loop() {
   /* Wait for Intan mark-out to start session!
   * We set sessionComplete = true in the setup() to satisfy this conditional
   * for the first iteration of the main loop.
  */
  if (digitalRead(intanMarkOut) == HIGH && sessionComplete) beginNewSession();
  if (digitalRead(intanMarkOut) == LOW) endCurrentSession();
  if (sessionComplete) return;
  recordEvent(BF_START_SESSION);
  delay(1000);
}
