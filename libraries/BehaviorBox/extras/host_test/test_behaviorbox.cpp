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
    generateTrials(trials, N, 30, 42, pool, 2);
    int r=0,l=0; for(int i=0;i<N;i++){ if(trials[i]==&goR) r++; else if(trials[i]==&goL) l++; }
    assert(r+l==N);                 // every slot filled
    assert(r > l); }                // 3:1 weighting favors right

  printf("ALL HEADER LOGIC TESTS PASSED\n");
  return 0;
}
