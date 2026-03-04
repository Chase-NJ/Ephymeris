/* 
  A simple Arduino sketch that facilitates testing a 12-odor olfactometer for leaks/
  overall functionality.

  While testing, be sure to check:
    1. No air leaks from olfactometer
    2. L.E.D.'s are working and correspond to the correct logic
    3. No fire hazards (check the soldering joints)
    4. Ensure good air flow through flowmeters!!
    5. Pretend your a rat!
*/

const int Odors[] = 
{ 
  22,   // Odor 1
  24,   // Odor 2
  26,   // Odor 3
  28,   // Odor 4
  30,   // Odor 5
  32,   // Odor 6
  23,   // Odor 7
  25,   // Odor 8
  27,   // Odor 9
  29,   // Odor 10
  31,   // Odor 11
  33    // Odor 12
};      // Solenoid pins

void setup() {
  // Outputs
  for (int i = 0; i < 12; i++) {
    pinMode(Odors[i], OUTPUT);
  }

  // Make sure everything is chill...
  for (int odor = 0; odor < 8; odor++) {
    digitalWrite(Odors[odor], LOW);
  }
}
  
int curr_odor = 0;
void loop() {
  if (curr_odor > 11) {
    curr_odor = 0;
  }
  digitalWrite(Odors[curr_odor], HIGH);
  delay(5000);
  digitalWrite(Odors[curr_odor], LOW);
  delay(5000);
  curr_odor++;
}
