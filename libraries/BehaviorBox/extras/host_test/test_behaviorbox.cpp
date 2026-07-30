#include "Arduino.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include "BehaviorBox.h"

/*  parseStartCommand() parses IN PLACE (it strtok's the caller's buffer), which
    is what collapsed the old double length cap. Tests hand it string literals,
    so copy into a scratch buffer of the real firmware size first. */
static void parseStart(const char *line, TaskParams &p) {
  char buf[START_LINE_MAX];
  strncpy(buf, line, sizeof(buf) - 1);
  buf[sizeof(buf) - 1] = '\0';
  parseStartCommand(buf, p);
}

int main() {

  // --- parseStartCommand: defaults, full, order-independent, tolerant ---
  { TaskParams c; parseStart("START", c);
    assert(c.correctionLeft==0 && c.correctionRight==0 && c.lazyEscalationEnabled); }
  { TaskParams c; parseStart("START CL=2 CR=3 LAZY=0", c);
    assert(c.correctionLeft==2 && c.correctionRight==3 && !c.lazyEscalationEnabled); }
  { TaskParams c; parseStart("START LAZY=0 CR=5 CL=1", c);   // order-independent
    assert(c.correctionLeft==1 && c.correctionRight==5 && !c.lazyEscalationEnabled); }
  { TaskParams c; parseStart("START CR=4 FOO=9", c);          // missing + unknown
    assert(c.correctionLeft==0 && c.correctionRight==4 && c.lazyEscalationEnabled); }
  { TaskParams c; parseStart("START CL=-3", c);               // negative clamps
    assert(c.correctionLeft==0); }

  // --- SEED: the host-drawn trial seed rides the same START line ---
  { TaskParams c; parseStart("START", c);
    assert(c.trialSeed==0UL); }                                         // absent -> "none sent"
  { TaskParams c; parseStart("START CL=2 SEED=2147483646 LAZY=0", c);
    // Full 31-bit range, parsed alongside everything else. atoi() would have
    // wrapped this to garbage on a 16-bit int -- that is why it is strtoul.
    assert(c.trialSeed==2147483646UL);
    assert(c.correctionLeft==2 && !c.lazyEscalationEnabled); }
  { TaskParams c; parseStart("START SEED=1", c);
    assert(c.trialSeed==1UL); }

  // --- beginSessionRng: announces exactly the state it seeded ---
  { TaskParams c; parseStart("START SEED=123456789", c);
    assert(beginSessionRng(c)==123456789UL); }                          // host seed used verbatim
  { TaskParams c;                                                    // no SEED -> clock fallback,
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
    TaskParams c; parseStart("START SEED=42", c); beginSessionRng(c);
    generateTrials(trials, N, 30, pool, 2);
    int r=0,l=0; for(int i=0;i<N;i++){ if(trials[i]==&goR) r++; else if(trials[i]==&goL) l++; }
    assert(r+l==N);                 // every slot filled
    assert(r > l); }                // 3:1 weighting favors right

  // --- generateTrials draws from the seeded stream, so the seed decides the
  //     sequence. Two different seeds must not produce the same trial order:
  //     that equality is exactly what the shaping sketches used to guarantee.
  { TrialWeight pool[] = { {goR, 1}, {goL, 1} };
    const int N = 120; const TrialType* a[N]; const TrialType* b[N];
    TaskParams c1; parseStart("START SEED=1", c1);
    beginSessionRng(c1); generateTrials(a, N, 30, pool, 2);
    TaskParams c2; parseStart("START SEED=987654321", c2);
    beginSessionRng(c2); generateTrials(b, N, 30, pool, 2);
    assert(memcmp(a, b, sizeof(a)) != 0); }
  { TrialWeight pool[] = { {goR, 1}, {goL, 1} };   // and the same seed still replays
    const int N = 120; const TrialType* a[N]; const TrialType* b[N];
    TaskParams c; parseStart("START SEED=555", c);
    beginSessionRng(c); generateTrials(a, N, 30, pool, 2);
    beginSessionRng(c); generateTrials(b, N, 30, pool, 2);
    assert(memcmp(a, b, sizeof(a)) == 0); }


  // --- TaskParams: every tunable rides the START line, defaults are full-task ---
  { TaskParams p; parseStart("START", p);                               // bare START
    assert(p.odorPokeHold==500 && p.fluidWellHold==200);
    assert(p.fluidWellPoll==2000 && p.odorPortTimeout==4000);
    assert(p.errorDelay==20000 && p.standardITI==4000 && p.pollingRate==5); }
  { TaskParams p; parseStart("START ERR=9000 ITI=1500 POL=3 PRM=750 NWP=800", p);
    assert(p.errorDelay==9000 && p.standardITI==1500);
    assert(p.pollingRate==3 && p.primingDelay==750 && p.nogoWellPoll==800); }
  { TaskParams p; parseStart("START FL1=80 FL2=90 FL3=110 FL4=120", p); // reward volumes
    assert(p.fluidPinTimes[0]==80 && p.fluidPinTimes[1]==90);
    assert(p.fluidPinTimes[2]==110 && p.fluidPinTimes[3]==120); }
  { TaskParams p; parseStart("START DBS=0.75 PMN=0.1 PMX=0.9 BW=12 MCS=4", p);
    assert(p.debiasStrength>0.74f && p.debiasStrength<0.76f);
    assert(p.pSideMin>0.09f && p.pSideMin<0.11f);
    assert(p.biasWindow==12 && p.maxConsecutiveSide==4); }
  { TaskParams p; parseStart("START PW1=3 PW2=0 PW3=1 PW4=0 NT=240 BS=24", p);
    assert(p.poolWeights[0]==3 && p.poolWeights[2]==1);
    assert(p.numTrials==240 && p.blockSize==24); }

  // --- clampTaskParams: operator-typed values can no longer hang the runner ---
  { TaskParams p; parseStart("START POL=0 NT=0 BS=-5 BW=999 MCS=0 FL1=-20", p);
    assert(p.pollingRate==1 && p.numTrials==1 && p.blockSize==1);
    assert(p.biasWindow==BEHAVIOR_MAX_BIAS_WINDOW && p.maxConsecutiveSide==1);
    assert(p.fluidPinTimes[0]==0); }
  { TaskParams p; parseStart("START PMN=-1 PMX=5", p);                  // probabilities held to [0,1]
    assert(p.pSideMin==0.0f && p.pSideMax==1.0f); }
  { TaskParams p; parseStart("START LZG=99", p);                        // stage index held in range
    assert(p.lazyEscalationStage==NUM_STAGES-1); }

  // --- the ramp: rows arrive over the wire and engage by completed-trial count ---
  { TaskParams p;
    parseStart("START S0T=0 S0P=10 S0H=10 S0W=10000 S0O=8000 "
               "S1T=15 S1P=100 S1H=50 S1W=10000 S1O=8000 "
               "S4T=80 S4P=500 S4H=200 S4W=2000 S4O=4000", p);
    assert(p.odorPokeHold==10 && p.fluidWellPoll==10000);   // row 0 live before trial 1
    applyStage(p, 14); assert(p.odorPokeHold==10);          // still row 0
    applyStage(p, 15); assert(p.odorPokeHold==100 && p.fluidWellHold==50);
    applyStage(p, 79); assert(p.odorPokeHold==100);         // rows 2/3 unset -> never engage
    applyStage(p, 80); assert(p.odorPokeHold==500 && p.fluidWellHold==200);
    applyStage(p, 5000); assert(p.odorPokeHold==500); }     // idempotent past the last row
  { TaskParams p; parseStart("START", p);                   // no ramp declared -> never moves
    applyStage(p, 100000); assert(p.odorPokeHold==500 && p.odorPortTimeout==4000); }
  { TaskParams p;                                           // >= scan, so a SKIPPED count
    parseStart("START S1T=20 S1P=123", p);                  // still lands on the right row --
    applyStage(p, 37); assert(p.odorPokeHold==123); }       // the old switch fired only on ==

  // --- lazyEscalationStage: an eased task holds escalation until its last row ---
  { TaskParams p; parseStart("START LZG=0", p);                         // full task: armed at once
    assert(escalationArmed(p, 0)); }
  { TaskParams p; parseStart("START LZG=4 S1T=15 S2T=30 S3T=50 S4T=80", p);
    assert(!escalationArmed(p, 0) && !escalationArmed(p, 79));
    assert(escalationArmed(p, 80)); }

  // --- applyShapingDefaults: the shaping bare-START baseline + its schedule ---
  { TaskParams p; applyShapingDefaults(p);
    assert(p.pollingRate==2 && p.lazyRatDelay==4000 && p.noPokeHoldTimeout==5000);
    assert(p.odorPokeHold==10 && p.odorPortTimeout==8000);
    applyStage(p, 20);  assert(p.odorPokeHold==100 && p.fluidWellHold==50);
    applyStage(p, 25);  assert(p.odorPokeHold==125 && p.fluidWellPoll==5000);
    applyStage(p, 50);  assert(p.odorPokeHold==250 && p.odorPortTimeout==4000);
    applyStage(p, 100); assert(p.odorPokeHold==500); }

  // --- outcomeDelay: the outcome is now carried, not inferred from the delay.
  //     These three values are operator-typed and may legally collide; that used
  //     to make every error read back as a correct trial.
  { TaskParams p; parseStart("START ERR=4000 ITI=4000 NPH=4000", p);
    assert(outcomeDelay(OUTCOME_CORRECT, p)==4000);
    assert(outcomeDelay(OUTCOME_ERROR, p)==4000);
    assert(OUTCOME_CORRECT != OUTCOME_ERROR); }             // still distinguishable

  // --- a fully-declared eased task must fit the shared line cap ---
  { char line[START_LINE_MAX];
    int n = snprintf(line, sizeof(line),
      "START ERR=20000 NWP=2000 LZD=6000 LZS=6000 LZM=30000 NPH=10000 ITI=4000 "
      "PRM=1000 POL=5 FL1=100 FL2=100 FL3=100 FL4=100 CL=0 CR=0 LZG=4 NT=1000 "
      "BS=30 PW1=1 PW2=0 PW3=0 PW4=0 BW=20 MCS=6 DBS=0.5 PMN=0.05 PMX=0.95 LAZY=1 "
      "S0T=0 S0P=10 S0H=10 S0W=10000 S0O=8000 S1T=15 S1P=100 S1H=50 S1W=10000 S1O=8000 "
      "S2T=30 S2P=200 S2H=200 S2W=5000 S2O=6000 S3T=50 S3P=350 S3H=350 S3W=3000 S3O=4000 "
      "S4T=80 S4P=500 S4H=200 S4W=2000 S4O=4000 SEED=2147483646");
    assert(n > 0 && (size_t)n < sizeof(line));   // fits, un-truncated
    TaskParams p; parseStartCommand(line, p);    // and every token lands
    assert(p.lazyEscalationStage==4 && p.trialSeed==2147483646UL);
    assert(p.stage[2].fluidWellPoll==5000 && p.stage[4].odorPokeHold==500);
    assert(p.maxConsecutiveSide==6 && p.fluidPinTimes[3]==100); }

  printf("ALL HEADER LOGIC TESTS PASSED\n");
  return 0;
}
