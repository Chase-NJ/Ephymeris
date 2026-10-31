#include "Arduino.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include "strobe_fixture.h"  // arbitrary codes; the real ones are generated
#include "BehaviorBox.h"

/*  parseStartCommand() parses IN PLACE (it strtok's the caller's buffer), which
    is what collapsed the old double length cap. Tests hand it string literals,
    so copy into a scratch buffer of the real firmware size first. */
static void parseStart(const char *line, TaskParams &p) {
  char buf[1024];  // a hand-typed START may be long; only a SET line is capped
  strncpy(buf, line, sizeof(buf) - 1);
  buf[sizeof(buf) - 1] = '\0';
  parseStartCommand(buf, p);
}

/*  applySetLine() parses IN PLACE too, and prints its reply to Serial. Hand it a
    buffer of the real firmware size and reset the capture first, so a test reads
    exactly the lines that one SET produced. */
static void setLine(const char *line, TaskParams &p, ParamAudit &a) {
  char buf[SET_LINE_MAX];
  strncpy(buf, line, sizeof(buf) - 1);
  buf[sizeof(buf) - 1] = '\0';
  _serialOutLen = 0; _serialOut[0] = '\0';
  applySetLine(buf, p, a);
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
  //     `rightWell`/`leftWell` rather than raw pins: the selector splits the
  //     table by comparing correctWell against them, which is what lets it stop
  //     knowing a pin number.
  TrialType goR(true,1,rightWell,2,101,253,357,100), goL(true,3,leftWell,0,103,252,369,100);
  const TrialType twoSided[] = { goR, goL };
  { AntiBiasSelector s(twoSided,2,20,0.5,0.05,0.95,6);
    const TrialType* t = s.selectNext(); assert(t==&twoSided[0] || t==&twoSided[1]);
    // Feed 20 RIGHT choices -> estimator should now favor LEFT selections.
    for(int i=0;i<20;i++) s.recordChoice(true);
    int left=0; for(int i=0;i<200;i++){ if(s.selectNext()==&twoSided[1]) left++; }
    assert(left > 120); }   // strong (not absolute) push to the under-chosen side

  // --- ...and with two types per side it still de-biases the SIDE, presenting
  //     both of that side's odors. This is the case the two-pointer selector
  //     could not express at all.
  { TrialType r2(true,5,rightWell,2,102,253,357,100), l2(true,7,leftWell,0,104,252,369,100);
    const TrialType four[] = { goR, r2, goL, l2 };
    AntiBiasSelector s(four,4,20,0.5,0.05,0.95,32);
    int right=0, seenR0=0, seenR1=0;
    for(int i=0;i<400;i++){
      const TrialType* t = s.selectNext();
      if(t->correctWell==rightWell){ right++; if(t==&four[0]) seenR0++; else seenR1++; }
    }
    assert(right > 150 && right < 250);      // no side bias with no history
    assert(seenR0 > 0 && seenR1 > 0); }      // both right-hand odors presented

  // --- a one-sided table is legal and must not fault: every draw falls through
  //     to the only side there is.
  { const TrialType oneSided[] = { goR };
    AntiBiasSelector s(oneSided,1);
    for(int i=0;i<50;i++) assert(s.selectNext()==&oneSided[0]); }

  // --- a no-go type has no side, so the selector never presents it ---
  { TrialType nogo(false,9,SENTINEL,SENTINEL,105,0,0,0);
    const TrialType mixed[] = { goR, goL, nogo };
    AntiBiasSelector s(mixed,3);
    for(int i=0;i<200;i++) assert(s.selectNext() != &mixed[2]); }

  // --- WeightedAntiBiasSelector: the same side draw, a weighted pick within it ---
  //     Slots: 0 goR, 1 r2, 2 goL, 3 l2. Weights 3:1 on each side.
  { TrialType r2(true,5,rightWell,2,102,253,357,100), l2(true,7,leftWell,0,104,252,369,100);
    const TrialType four[] = { goR, r2, goL, l2 };
    TaskParams c; parseStart("START PW1=3 PW2=1 PW3=3 PW4=1 SEED=7 BW=20 MCS=32", c);
    beginSessionRng(c);
    WeightedAntiBiasSelector s(four,4); s.configure(c);
    int right=0, n0=0, n1=0, n2=0, n3=0;
    for(int i=0;i<800;i++){
      const TrialType* t = s.selectNext();
      if(t==&four[0]) n0++; else if(t==&four[1]) n1++; else if(t==&four[2]) n2++; else n3++;
      if(t->correctWell==rightWell) right++;
    }
    assert(right > 300 && right < 500);   // the weights do not move the SIDE balance
    assert(n0 > 2*n1 && n2 > 2*n3);       // ~3:1 within each side
    assert(n1 > 0 && n3 > 0); }           // the light types are still presented

  // --- ...and it still pushes against an expressed side bias, like the base ---
  { TrialType r2(true,5,rightWell,2,102,253,357,100), l2(true,7,leftWell,0,104,252,369,100);
    const TrialType four[] = { goR, r2, goL, l2 };
    TaskParams c; parseStart("START PW1=3 PW2=1 PW3=3 PW4=1 DBS=0.5 PMN=0.05 PMX=0.95 MCS=6", c);
    WeightedAntiBiasSelector s(four,4); s.configure(c);
    for(int i=0;i<20;i++) s.recordChoice(true);
    int left=0; for(int i=0;i<200;i++){ if(s.selectNext()->correctWell==leftWell) left++; }
    assert(left > 120); }

  // --- a zero weight parks a type; all-zero on a side falls back to uniform ---
  { TrialType r2(true,5,rightWell,2,102,253,357,100), l2(true,7,leftWell,0,104,252,369,100);
    const TrialType four[] = { goR, r2, goL, l2 };
    TaskParams c; parseStart("START PW1=1 PW2=0 PW3=0 PW4=0", c);
    WeightedAntiBiasSelector s(four,4); s.configure(c);
    int n1=0, n2=0, n3=0;
    for(int i=0;i<400;i++){
      const TrialType* t = s.selectNext();
      if(t==&four[1]) n1++; else if(t==&four[2]) n2++; else if(t==&four[3]) n3++;
    }
    assert(n1 == 0);                      // weighted 0 -> never drawn
    assert(n2 > 0 && n3 > 0); }           // left side all-zero -> uniform, both seen

  // --- a one-sided table must not fault under the weighted draw either ---
  { const TrialType oneSided[] = { goR };
    TaskParams c; parseStart("START PW1=0", c);
    WeightedAntiBiasSelector s(oneSided,1); s.configure(c);
    for(int i=0;i<50;i++) assert(s.selectNext()==&oneSided[0]); }

  // --- the runner's view of it is the base pointer, and that is enough ---
  { TrialType r2(true,5,rightWell,2,102,253,357,100);
    const TrialType two[] = { goR, r2 };
    WeightedAntiBiasSelector s(two,2);
    TrialPolicy policy; policy.selector = &s;   // what runTrial() is handed
    policy.selector->recordChoice(true);        // base methods, resolved on the base
    policy.selector->recordAbstention(false); }

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
  { TaskParams p; parseStart("START RW1=80 RW2=90 RW3=110 RW4=120", p); // per-type reward volumes
    assert(p.rewardTimes[0]==80 && p.rewardTimes[1]==90);
    assert(p.rewardTimes[2]==110 && p.rewardTimes[3]==120); }
  { TaskParams p; parseStart("START RW2=250", p);                         // unsent slots read "not sent"
    assert(p.rewardTimes[0]==-1 && p.rewardTimes[1]==250 && p.rewardTimes[3]==-1); }
  { TaskParams p;                                                          // every slot, not just slot 0:
    for (int i = 0; i < BOX_MAX_TRIAL_TYPES; i++) assert(p.rewardTimes[i]==-1); } // a {-1} initialiser zero-fills the tail

  // --- applyRewardTimes: the line overrides the table, silence keeps it, 0 is a value ---
  { TrialType t[] = { TrialType(true,1,rightWell,2,101,253,357,100),
                      TrialType(true,3,leftWell,0,103,252,369,150) };
    TaskParams p; parseStart("START RW2=250", p);
    applyRewardTimes(p, t, 2);
    assert(t[0].rewardTime==100 && t[1].rewardTime==250); }   // slot 1 sent, slot 0 kept
  { TrialType t[] = { TrialType(true,1,rightWell,2,101,253,357,100) };
    TaskParams p; parseStart("START RW1=0", p);
    applyRewardTimes(p, t, 1);
    assert(t[0].rewardTime==0); }                                 // a sent 0 ms is honoured
  { TrialType t[] = { TrialType(true,1,rightWell,2,101,253,357,100) };
    TaskParams p; parseStart("START", p);
    applyRewardTimes(p, t, 1);
    assert(t[0].rewardTime==100); }                               // bare START -> compiled default
  { TaskParams p; parseStart("START DBS=0.75 PMN=0.1 PMX=0.9 BW=12 MCS=4", p);
    assert(p.debiasStrength>0.74f && p.debiasStrength<0.76f);
    assert(p.pSideMin>0.09f && p.pSideMin<0.11f);
    assert(p.biasWindow==12 && p.maxConsecutiveSide==4); }
  { TaskParams p; parseStart("START PW1=3 PW2=0 PW3=1 PW4=0 NT=240 BS=24", p);
    assert(p.poolWeights[0]==3 && p.poolWeights[2]==1);
    assert(p.numTrials==240 && p.blockSize==24); }

  // --- clampTaskParams: operator-typed values can no longer hang the runner ---
  { TaskParams p; parseStart("START POL=0 NT=0 BS=-5 BW=999 MCS=0 RW1=-20", p);
    assert(p.pollingRate==1 && p.numTrials==1 && p.blockSize==1);
    assert(p.biasWindow==BEHAVIOR_MAX_BIAS_WINDOW && p.maxConsecutiveSide==1);
    assert(p.rewardTimes[0]==-1); }                                     // a negative reads as "not sent"
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

  // --- the shaping schedule now arrives on the wire, not from a compiled-in
  //     defaults function. Same numbers the retired applyShapingDefaults() set,
  //     walked the same way -- what changed is who supplies them.
  { TaskParams p; parseStart("START POL=2 LZD=4000 NPH=5000 "
      "S0T=0 S0P=10 S0H=10 S0W=10000 S0O=8000 S1T=20 S1P=100 S1H=50 S1W=10000 S1O=8000 "
      "S2T=25 S2P=125 S2H=250 S2W=5000 S2O=8000 S3T=50 S3P=250 S3H=500 S3W=2000 S3O=4000 "
      "S4T=100 S4P=500 S4H=500 S4W=2000 S4O=4000", p);
    assert(p.pollingRate==2 && p.lazyRatDelay==4000 && p.noPokeHoldTimeout==5000);
    assert(p.odorPokeHold==10 && p.odorPortTimeout==8000);
    applyStage(p, 20);  assert(p.odorPokeHold==100 && p.fluidWellHold==50);
    applyStage(p, 25);  assert(p.odorPokeHold==125 && p.fluidWellPoll==5000);
    applyStage(p, 50);  assert(p.odorPokeHold==250 && p.odorPortTimeout==4000);
    applyStage(p, 100); assert(p.odorPokeHold==500); }

  // --- an un-parsed TaskParams is already a valid one-row ramp. The rows above
  //     row 0 carry a count no session reaches, so nothing engages them; this is
  //     what the constructor replaced a five-row brace initialiser to guarantee,
  //     and getting it wrong reads as a ramp that never advanced.
  { TaskParams p;
    assert(p.stage[0].trials == 0);
    for (int i = 1; i < NUM_STAGES; i++) assert(p.stage[i].trials == STAGE_UNREACHABLE);
    applyStage(p, 0);      assert(p.odorPokeHold==500 && p.fluidWellHold==200);
    applyStage(p, 100000); assert(p.odorPokeHold==500); }

  // --- outcomeDelay: the outcome is now carried, not inferred from the delay.
  //     These three values are operator-typed and may legally collide; that used
  //     to make every error read back as a correct trial.
  { TaskParams p; parseStart("START ERR=4000 ITI=4000 NPH=4000", p);
    assert(outcomeDelay(OUTCOME_CORRECT, p)==4000);
    assert(outcomeDelay(OUTCOME_ERROR, p)==4000);
    assert(OUTCOME_CORRECT != OUTCOME_ERROR); }             // still distinguishable

  // --- SET / PARAMS: the host sends capped SET lines, the board answers with
  //     what it accepted, and the host refuses the start on a disagreement
  //     (docs/TASKS.md#the-length-cap). The CRC is the standard CRC-32 -- the
  //     one Python's zlib.crc32 computes -- over the accepted tokens exactly as
  //     received, joined by single spaces. The literals below come from zlib,
  //     not from this code; sidecar/tests/test_start_command.py pins the same ones.
  { ParamAudit a; crc32Feed(a, "123456789", 9);
    assert(a.finalCrc() == 0xCBF43926UL); }                           // the CRC-32 check value
  { ParamAudit a;
    assert(a.accepted == 0 && a.finalCrc() == 0UL); }                 // nothing accepted: crc of ""

  { TaskParams p; ParamAudit a;
    setLine("SET ITI=4000 PRM=1000", p, a);
    assert(strcmp(_serialOut, "PARAMS 2 3324716134\r\n") == 0);
    assert(p.standardITI==4000 && p.primingDelay==1000); }            // and the values landed

  { TaskParams p; ParamAudit a;                                       // a bare SET: zero keys
    setLine("SET", p, a);
    assert(strcmp(_serialOut, "PARAMS 0 0\r\n") == 0); }

  { TaskParams p; ParamAudit a;                                       // the running total, across lines
    setLine("SET ITI=4000", p, a);
    assert(strcmp(_serialOut, "PARAMS 1 1462853793\r\n") == 0);
    setLine("SET PRM=1000", p, a);
    assert(strcmp(_serialOut, "PARAMS 2 3324716134\r\n") == 0); }

  { TaskParams p; ParamAudit a;                                       // a key it does not parse is
    setLine("SET ITI=4000 FOO=9 PRM=1000", p, a);                     // neither counted nor hashed, so
    assert(strcmp(_serialOut, "PARAMS 2 3324716134\r\n") == 0); }     // the host's count disagrees

  { TaskParams p; ParamAudit a;                                       // a truncated value: counted, but
    setLine("SET ITI=4000 PRM=10", p, a);                             // the CRC is over what arrived
    assert(strncmp(_serialOut, "PARAMS 2 ", 9) == 0);
    assert(strcmp(_serialOut, "PARAMS 2 3324716134\r\n") != 0); }

  { TaskParams p; ParamAudit a;                                       // a clamped value is named, before the
    setLine("SET POL=0", p, a);                                       // reply that carries it
    assert(strncmp(_serialOut, "CLAMPED POL\r\nPARAMS 1 ", 22) == 0);
    assert(p.pollingRate==0);                                         // the SET itself changes nothing...
    parseStart("START", p);
    assert(p.pollingRate==1); }                                       // ...the clamp lands at START

  { TaskParams p; ParamAudit a;                                       // clamps are judged on the state so far:
    setLine("SET PMN=0.99", p, a);                                    // PMX (0.98 default) would be pulled up
    assert(strstr(_serialOut, "CLAMPED PMX") != NULL);
    setLine("SET PMX=0.995", p, a);                                   // ...and is not once the next line sets it
    assert(strstr(_serialOut, "CLAMPED") == NULL);
    assert(strncmp(_serialOut, "PARAMS 2 ", 9) == 0); }

  // --- a value the board's int cannot hold is a clamp, not a wrap. The CRC is
  //     over the text, so it matches whatever the board makes of the digits; the
  //     only thing that stops ITI=40000 running as -25536 on a 16-bit int is the
  //     board saying it could not hold it. The limit is the AVR's, on every host.
  { TaskParams p; ParamAudit a;
    setLine("SET ITI=40000", p, a);
    assert(strncmp(_serialOut, "CLAMPED ITI\r\nPARAMS 1 ", 22) == 0);
    assert(p.standardITI == 32767); }                                 // held, never wrapped
  { TaskParams p; ParamAudit a;
    setLine("SET ITI=32767 ERR=-32768", p, a);                        // the edges fit
    assert(strstr(_serialOut, "CLAMPED") == NULL); }
  { TaskParams p; ParamAudit a;
    setLine("SET ITI=32768", p, a);                                   // one past
    assert(strstr(_serialOut, "CLAMPED ITI") != NULL);
    setLine("SET ERR=-32769", p, a);                                  // and one below
    assert(strstr(_serialOut, "CLAMPED ITI") != NULL && strstr(_serialOut, "CLAMPED ERR") != NULL);
    assert(p.errorDelay == -32768); }
  { TaskParams p; ParamAudit a;                                       // a later line that sets it right
    setLine("SET ITI=70000", p, a);                                   // clears it, and nothing else does
    setLine("SET ITI=4000", p, a);
    assert(strstr(_serialOut, "CLAMPED") == NULL);
    assert(p.standardITI == 4000); }
  { TaskParams p; ParamAudit a;                                       // moved by the clamp AND too wide: once
    setLine("SET POL=-40000", p, a);
    const char *first = strstr(_serialOut, "CLAMPED POL");
    assert(first != NULL && strstr(first + 1, "CLAMPED POL") == NULL); }
  { TaskParams p; ParamAudit a;                                       // more keys than the audit can name:
    setLine("SET ERR=99999 ITI=99999 NPH=99999 NWP=99999 PRM=99999 POL=99999", p, a);
    setLine("SET LZD=99999 LZS=99999 LZM=99999 CL=99999 CR=99999 LZG=99999", p, a);
    setLine("SET NT=99999 BS=99999 BW=99999 MCS=99999 S0T=99999 S0P=99999", p, a);
    assert(strstr(_serialOut, "CLAMPED") != NULL); }                  // still refused, whatever it is called
  { TaskParams p; ParamAudit a;                                       // a flag is not a number to wrap to zero
    setLine("SET LAZY=65536", p, a);
    assert(strstr(_serialOut, "CLAMPED LAZY") != NULL); }

  // --- a value the board parses differently from how the host wrote it is a
  //     clamp too. The CRC is over the text, so it matches whatever the board
  //     makes of it: ITI=4.9 is held as 4, ITI=abc as 0, LAZY=true as 0 and
  //     DBS=1e40 as infinity, and none of it would otherwise be noticed.
  { const char *bad[] = {
      "SET ITI=4.9", "SET ITI=abc", "SET ITI=12abc", "SET ITI=", "SET ITI=1e3",
      "SET LAZY=true", "SET LAZY=0.5",
      "SET DBS=1e40", "SET DBS=-1e40", "SET DBS=abc", "SET DBS=0.5x", "SET DBS=",
    };
    const char *keys[] = {
      "ITI", "ITI", "ITI", "ITI", "ITI", "LAZY", "LAZY", "DBS", "DBS", "DBS", "DBS", "DBS",
    };
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
      TaskParams p; ParamAudit a;
      setLine(bad[i], p, a);
      char want[24];
      snprintf(want, sizeof(want), "CLAMPED %s", keys[i]);
      if (strstr(_serialOut, want) == NULL) { printf("not refused: %s -> %s\n", bad[i], _serialOut); assert(false); }
      assert(a.accepted == 1);                                        // still counted and hashed as sent
    } }
  { TaskParams p; ParamAudit a;                                       // what they are held as
    setLine("SET ITI=4.9", p, a);   assert(p.standardITI == 4);
    setLine("SET ITI=abc", p, a);   assert(p.standardITI == 0);
    setLine("SET LAZY=true", p, a); assert(!p.lazyEscalationEnabled); }
  { const char *good[] = {
      "SET ITI=4000", "SET ITI=-5", "SET ITI=+7", "SET DBS=0.5", "SET DBS=1e-3", "SET DBS=2", "SET DBS=-0.25",
      "SET LAZY=1", "SET LAZY=0",
    };
    for (size_t i = 0; i < sizeof(good) / sizeof(good[0]); i++) {
      TaskParams p; ParamAudit a;
      setLine(good[i], p, a);
      if (strstr(_serialOut, "CLAMPED") != NULL) { printf("refused: %s -> %s\n", good[i], _serialOut); assert(false); }
    } }
  { TaskParams p; ParamAudit a;                                       // fixed by a later line, it is fine
    setLine("SET ITI=abc", p, a);
    setLine("SET ITI=4000", p, a);
    assert(strstr(_serialOut, "CLAMPED") == NULL && p.standardITI == 4000); }

  // --- awaitStart: the one SET/START loop both sketches run. A block opens with
  //     BEGIN, which forgets any earlier one -- the audit, and the values -- so a
  //     refused Send START from Debug Mode can be corrected and sent again on the
  //     same open console. Without it the retry's PARAMS counts the first block
  //     too and every retry is refused as a count mismatch.
  { TaskParams p; p.numTrials = 200;                                  // a sketch's own fallback
    _serialOutLen = 0; _serialOut[0] = '\0';
    _serialIn = "BEGIN\nSET ITI=40000 RW1=7 NT=50\n"                   // refused: ITI cannot be held
                "BEGIN\nSET ITI=4000\n"                              // corrected, sent again
                "START SEED=5\n";
    awaitStart(p);
    // The second reply is for the second block alone: one key, ITI=4000.
    assert(strstr(_serialOut, "CLAMPED ITI\r\nPARAMS 3 ") != NULL);     // the first, with its three keys
    const char *second = strstr(_serialOut, "PARAMS 1 1462853793\r\n");
    assert(second != NULL && strstr(second, "CLAMPED") == NULL);
    assert(p.standardITI == 4000 && p.trialSeed == 5UL);
    assert(p.rewardTimes[0] == -1);                                   // RW1=7 of the first block is gone
    assert(p.numTrials == 200); }                                     // and the sketch's own fallback is back
  { TaskParams p;                                                     // no BEGIN: a hand-typed console works
    _serialOutLen = 0; _serialOut[0] = '\0';
    _serialIn = "SET ITI=4000\nSTART SEED=9\n";
    awaitStart(p);
    assert(p.standardITI == 4000 && p.trialSeed == 9UL); }
  { TaskParams p;                                                     // a bare START keeps every default
    _serialIn = "STARTUP\nSTART\n";                                  // and a word that merely begins with it is ignored
    awaitStart(p);
    assert(p.standardITI == 4000); }

  { TaskParams p; ParamAudit a;                                       // START SEED=<n> is not a parameter
    setLine("SET ITI=4000", p, a);
    parseStart("START SEED=77", p);
    assert(p.trialSeed==77UL && p.standardITI==4000 && a.accepted==1); }

  { assert(lineIsCommand("SET", "SET") && lineIsCommand("SET A=1", "SET"));
    assert(!lineIsCommand("SETUP", "SET") && !lineIsCommand("START", "SET"));
    assert(lineIsCommand("START SEED=1", "START") && !lineIsCommand("STARTED", "START")); }

  // --- THE CROSS-REPO CHECK: the exact SET lines Ephymeris builds for the
  //     shipped GRGL profile, taken by the parser that will receive them, and
  //     the PARAMS reply the host will hold against its own count and CRC.
  //
  //     These two sides agree by convention and nothing else enforces it: the
  //     app reads wire keys out of task.json, this parser reads them out of
  //     TASK_PARAM_LIST, and SET_LINE_MAX is written down twice. A key the app
  //     sends and the firmware does not know is not counted, so the host would
  //     refuse every start -- which is the right outcome, and this is the
  //     cheapest thing that notices it before a rig does.
  //
  //     Regenerate after editing GRGL/task.json, which the sidecar's
  //     test_the_firmware_confirms_the_set_lines_the_app_builds_for_grgl fails
  //     until you do:
  //       build_start_command(load_profile(<GRGL>), {})   -> .set_lines, .count, .crc32
  { static const char *const kGrglSetLines[] = {
      "SET ERR=20000 ITI=4000 NPH=10000 NWP=2000 PRM=1000 POL=5 LZD=6000 LAZY=1 LZS=6000 LZM=30000 LZG=0 RW1=100 RW2=100 NT=1000 PW1=1",
      "SET PW2=1 BS=30 CL=0 CR=0 BW=20 MCS=10 DBS=0.5 PMN=0.02 PMX=0.98 S0P=500 S0H=200 S0W=2000 S0O=4000",
    };
    static const char kGrglParams[] = "PARAMS 28 2184481299\r\n";
    TaskParams p; ParamAudit a;
    for (size_t i = 0; i < sizeof(kGrglSetLines) / sizeof(kGrglSetLines[0]); i++) {
      assert(strlen(kGrglSetLines[i]) < SET_LINE_MAX);   // each fits the buffer, whole
      setLine(kGrglSetLines[i], p, a);
    }
    assert(strcmp(_serialOut, kGrglParams) == 0);        // 28 keys, none clamped, same CRC
    parseStart("START SEED=2147483646", p);
    // One assertion per group, so a dropped token names which one went.
    assert(p.errorDelay==20000 && p.standardITI==4000);          // trial timing
    assert(p.lazyRatDelay==6000 && p.lazyEscalationEnabled);     // abstention
    assert(p.rewardTimes[0]==100 && p.rewardTimes[1]==100);      // reward volume, per type
    assert(p.numTrials==1000 && p.blockSize==30);                // session
    assert(p.poolWeights[0]==1 && p.poolWeights[1]==1);          // trial pool
    assert(p.correctionLeft==0 && p.correctionRight==0);         // correction
    assert(p.biasWindow==20 && p.maxConsecutiveSide==10);        // anti-bias
    assert(p.odorPokeHold==500 && p.fluidWellPoll==2000);        // holds, via row 0
    assert(p.trialSeed==2147483646UL); }                         // and START carried only the seed

  // --- INTERP and FREE_RAM: announced before READY, so the run can record which
  //     interpreter it ran under and the RAM its build left free. This firmware
  //     is interpreter 1; a host build has no RAM to measure and reports 0.
  { assert(BOX_INTERP == 1);
    _serialOutLen = 0; _serialOut[0] = '\0';
    announceReady();
    assert(strcmp(_serialOut, "INTERP=1\r\nFREE_RAM=0\r\nREADY\r\n") == 0);
    _serialOutLen = 0; _serialOut[0] = '\0';
    announceReadyAs(7);
    assert(strncmp(_serialOut, "INTERP=7\r\n", 10) == 0); }

  // --- readLineInto: what a sketch's char cmd[SET_LINE_MAX] keeps whole ---
  //
  //     One byte goes to the terminator, so SET_LINE_MAX - 1 characters is the
  //     longest SET line read intact, and the host never builds a longer one
  //     (sidecar test_start_command.py). A line of exactly SET_LINE_MAX loses its
  //     last character, which the CRC then reports.
  { static char sent[SET_LINE_MAX + 2];
    char cmd[SET_LINE_MAX];
    memset(sent, '7', SET_LINE_MAX - 1);
    sent[SET_LINE_MAX - 1] = '\n'; sent[SET_LINE_MAX] = '\0';
    _serialIn = sent;
    assert(readLineInto(cmd, sizeof(cmd)));
    assert(strlen(cmd) == SET_LINE_MAX - 1);                // whole
    assert(*_serialIn == '\0');                             // terminator consumed

    memset(sent, '7', SET_LINE_MAX - 1);
    sent[SET_LINE_MAX - 1] = '9';                            // one more: the last digit
    sent[SET_LINE_MAX] = '\n'; sent[SET_LINE_MAX + 1] = '\0';
    _serialIn = sent;
    assert(readLineInto(cmd, sizeof(cmd)));
    assert(strlen(cmd) == SET_LINE_MAX - 1);                // truncated...
    assert(cmd[SET_LINE_MAX - 2] == '7');                    // ...and the '9' is gone
    assert(*_serialIn == '\0'); }                           // tail drained, not left queued

  // --- a truncated SET line is caught end to end: the board reads the capped
  //     line and answers for what survived, so its answer cannot match the
  //     host's. Here the cut lands inside the second token's value.
  { static char sent[SET_LINE_MAX + 16];
    int n = snprintf(sent, sizeof(sent), "SET ITI=4000 PRM=");
    while (n < SET_LINE_MAX + 4) sent[n++] = '1';            // a value running past the cap
    sent[n++] = '\n'; sent[n] = '\0';
    _serialIn = sent;
    char cmd[SET_LINE_MAX];
    assert(readLineInto(cmd, sizeof(cmd)));
    assert(strlen(cmd) == SET_LINE_MAX - 1);
    TaskParams p; ParamAudit a;
    _serialOutLen = 0; _serialOut[0] = '\0';
    applySetLine(cmd, p, a);
    assert(a.accepted == 2);                                 // both keys counted...
    assert(strstr(_serialOut, "PARAMS 2 ") != NULL);
    assert(strcmp(_serialOut, "PARAMS 2 3324716134\r\n") != 0); }  // ...but not the host's CRC

  // --- emitStrobe: one sync pulse per strobe, and never two fused into one ---
  //
  // The recording controller sees only edges, and the host matches the Nth edge
  // to the Nth serial strobe. So the two properties that matter are that every
  // strobe rises exactly once, and that back-to-back strobes are separated by a
  // real LOW -- a fused pair is one edge, and every later event is then matched
  // one strobe late, which looks like data rather than like a failure.
  { TrialClock clock; clock.beginSession();
    _pinLogCount = 0;
    emitStrobe(clock, BF_END_SESSION);
    emitStrobe(clock, BF_END_SESSION);   // immediately: the worst case
    assert(_pinLogCount == 4);
    for (int i = 0; i < 4; i++) assert(_pinLog[i].pin == syncOut);
    assert(_pinLog[0].level == HIGH && _pinLog[1].level == LOW);
    assert(_pinLog[2].level == HIGH && _pinLog[3].level == LOW);
    assert(_pinLog[1].us - _pinLog[0].us >= (unsigned long)BOX_SYNC_PULSE_US);  // width
    assert(_pinLog[2].us - _pinLog[1].us >= (unsigned long)BOX_SYNC_GAP_US);    // the LOW between
    assert(_pinLog[3].us - _pinLog[2].us >= (unsigned long)BOX_SYNC_PULSE_US); }

  // --- emitStrobe: the line the app parses (^\d{1,3}\t\d+$), code zero-padded
  //     to three digits, then the ms since beginSession(). 7 is no vocabulary
  //     code; it is the smallest input that shows the padding.
  { _ms = 0; TrialClock clock; clock.beginSession();
    _ms = 1500;
    _serialOutLen = 0; _serialOut[0] = '\0';
    emitStrobe(clock, 7);
    assert(strcmp(_serialOut, "007\t1500\r\n") == 0); }

  // initBoxHardware() claims the line and parks it LOW: a floating input on the
  // controller reads as noise, i.e. as events.
  { _pinLogCount = 0;
    initBoxHardware();
    bool parked = false;
    for (int i = 0; i < _pinLogCount; i++)
      if (_pinLog[i].pin == syncOut) { assert(_pinLog[i].level == LOW); parked = true; }
    assert(parked); }

  printf("ALL HEADER LOGIC TESTS PASSED\n");
  return 0;
}
