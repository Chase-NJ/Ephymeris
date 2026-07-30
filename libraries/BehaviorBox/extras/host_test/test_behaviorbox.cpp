#include "Arduino.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include "BehaviorBox.h"

int main() {
  // --- parseStartCommand: defaults, full, order-independent, tolerant ---
  { SessionConfig c; parseStartCommand("START", c);
    assert(c.correctionLeft==0 && c.correctionRight==0 && c.lazyEscalationEnabled); }
  { SessionConfig c; parseStartCommand("START CL=2 CR=3 LAZY=0", c);
    assert(c.correctionLeft==2 && c.correctionRight==3 && !c.lazyEscalationEnabled); }
  { SessionConfig c; parseStartCommand("START LAZY=0 CR=5 CL=1", c);   // order-independent
    assert(c.correctionLeft==1 && c.correctionRight==5 && !c.lazyEscalationEnabled); }
  { SessionConfig c; parseStartCommand("START CR=4 FOO=9", c);          // missing + unknown
    assert(c.correctionLeft==0 && c.correctionRight==4 && c.lazyEscalationEnabled); }
  { SessionConfig c; parseStartCommand("START CL=-3", c);               // negative clamps
    assert(c.correctionLeft==0); }

  // --- SEED: the host-drawn trial seed rides the same START line ---
  { SessionConfig c; parseStartCommand("START", c);
    assert(c.trialSeed==0UL); }                                         // absent -> "none sent"
  { SessionConfig c; parseStartCommand("START CL=2 SEED=2147483646 LAZY=0", c);
    // Full 31-bit range, parsed alongside everything else. atoi() would have
    // wrapped this to garbage on a 16-bit int -- that is why it is strtoul.
    assert(c.trialSeed==2147483646UL);
    assert(c.correctionLeft==2 && !c.lazyEscalationEnabled); }
  { SessionConfig c; parseStartCommand("START SEED=1", c);
    assert(c.trialSeed==1UL); }

  // --- beginSessionRng: announces exactly the state it seeded ---
  { SessionConfig c; parseStartCommand("START SEED=123456789", c);
    assert(beginSessionRng(c)==123456789UL); }                          // host seed used verbatim
  { SessionConfig c;                                                    // no SEED -> clock fallback,
    unsigned long s = beginSessionRng(c);                               // still never 0 and in range
    assert(s >= 1UL && s <= 2147483646UL); }

  // --- CorrectionPolicy: per-side budgets, consumed by advances, not repeats ---
  { CorrectionPolicy p; p.configure(0,0);
    assert(!p.shouldRepeat(true) && !p.shouldRepeat(false)); }          // CL=CR=0 -> never repeat
  { CorrectionPolicy p; p.configure(1,2);
    // RIGHT side, budget 2: repeats until 2 right advances consumed.
    assert(p.shouldRepeat(true));  p.onAdvance(true);   // 1 right advance
    assert(p.shouldRepeat(true));  p.onAdvance(true);   // 2 right advances
    assert(!p.shouldRepeat(true));                      // budget reached -> advance on error
    // LEFT side, budget 1, independent of right.
    assert(p.shouldRepeat(false)); p.onAdvance(false);
    assert(!p.shouldRepeat(false)); }

  // --- AbstentionPenalty: ON escalates+grows; OFF flat, no growth; stage gate ---
  { AbstentionPenalty a(6000,6000,30000); a.setEnabled(true);
    assert(a.nextDelay(true)==6000);    // consec 0
    assert(a.nextDelay(true)==12000);   // consec 1
    assert(a.nextDelay(true)==18000);   // consec 2
    a.reset();
    assert(a.nextDelay(true)==6000); }  // reset clears growth
  { AbstentionPenalty a(6000,6000,30000); a.setEnabled(true);          // clamp to max
    for(int i=0;i<10;i++) a.nextDelay(true);
    assert(a.nextDelay(true)==30000); }
  { AbstentionPenalty a(6000,6000,30000); a.setEnabled(false);          // OFF -> flat, no growth
    assert(a.nextDelay(true)==6000);
    assert(a.nextDelay(true)==6000); }
  { AbstentionPenalty a(6000,6000,30000); a.setEnabled(true);           // stage gate (EZ): flat pre-ramp
    assert(a.nextDelay(false)==6000);
    assert(a.nextDelay(false)==6000);   // no growth while stage disallows
    assert(a.nextDelay(true)==6000);    // first escalating call still consec 0
    assert(a.nextDelay(true)==12000); }

  // --- AntiBiasSelector: returns a valid pointer; pushes against expressed bias ---
  TrialType goR(true,1,3,2,101,253,357), goL(true,3,4,0,103,252,369);
  { AntiBiasSelector s(&goR,&goL,20,0.5,0.05,0.95,6);
    const TrialType* t = s.selectNext(); assert(t==&goR || t==&goL);
    // Feed 20 RIGHT choices -> estimator should now favor LEFT selections.
    for(int i=0;i<20;i++) s.recordChoice(true);
    int left=0; for(int i=0;i<200;i++){ if(s.selectNext()==&goL) left++; }
    assert(left > 120); }   // strong (not absolute) push to the under-chosen side

  // --- generateTrials: honors weights, fills exactly numTrials ---
  { TrialWeight pool[] = { {goR, 3}, {goL, 1} };
    const int N = 120; const TrialType* trials[N];
    SessionConfig c; parseStartCommand("START SEED=42", c); beginSessionRng(c);
    generateTrials(trials, N, 30, pool, 2);
    int r=0,l=0; for(int i=0;i<N;i++){ if(trials[i]==&goR) r++; else if(trials[i]==&goL) l++; }
    assert(r+l==N);                 // every slot filled
    assert(r > l); }                // 3:1 weighting favors right

  // --- generateTrials draws from the seeded stream, so the seed decides the
  //     sequence. Two different seeds must not produce the same trial order:
  //     that equality is exactly what the shaping sketches used to guarantee.
  { TrialWeight pool[] = { {goR, 1}, {goL, 1} };
    const int N = 120; const TrialType* a[N]; const TrialType* b[N];
    SessionConfig c1; parseStartCommand("START SEED=1", c1);
    beginSessionRng(c1); generateTrials(a, N, 30, pool, 2);
    SessionConfig c2; parseStartCommand("START SEED=987654321", c2);
    beginSessionRng(c2); generateTrials(b, N, 30, pool, 2);
    assert(memcmp(a, b, sizeof(a)) != 0); }
  { TrialWeight pool[] = { {goR, 1}, {goL, 1} };   // and the same seed still replays
    const int N = 120; const TrialType* a[N]; const TrialType* b[N];
    SessionConfig c; parseStartCommand("START SEED=555", c);
    beginSessionRng(c); generateTrials(a, N, 30, pool, 2);
    beginSessionRng(c); generateTrials(b, N, 30, pool, 2);
    assert(memcmp(a, b, sizeof(a)) == 0); }

  printf("ALL HEADER LOGIC TESTS PASSED\n");
  return 0;
}
