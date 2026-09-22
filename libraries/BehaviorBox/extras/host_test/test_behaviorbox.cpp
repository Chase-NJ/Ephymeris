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

  // --- a fully-declared eased task must fit the shared line cap ---
  { char line[START_LINE_MAX];
    int n = snprintf(line, sizeof(line),
      "START ERR=20000 NWP=2000 LZD=6000 LZS=6000 LZM=30000 NPH=10000 ITI=4000 "
      "PRM=1000 POL=5 RW1=100 RW2=100 RW3=100 RW4=100 CL=0 CR=0 LZG=4 NT=1000 "
      "BS=30 PW1=1 PW2=0 PW3=0 PW4=0 BW=20 MCS=6 DBS=0.5 PMN=0.05 PMX=0.95 LAZY=1 "
      "S0T=0 S0P=10 S0H=10 S0W=10000 S0O=8000 S1T=15 S1P=100 S1H=50 S1W=10000 S1O=8000 "
      "S2T=30 S2P=200 S2H=200 S2W=5000 S2O=6000 S3T=50 S3P=350 S3H=350 S3W=3000 S3O=4000 "
      "S4T=80 S4P=500 S4H=200 S4W=2000 S4O=4000 SEED=2147483646");
    assert(n > 0 && (size_t)n < sizeof(line));   // fits, un-truncated
    TaskParams p; parseStartCommand(line, p);    // and every token lands
    assert(p.lazyEscalationStage==4 && p.trialSeed==2147483646UL);
    assert(p.stage[2].fluidWellPoll==5000 && p.stage[4].odorPokeHold==500);
    assert(p.maxConsecutiveSide==6 && p.rewardTimes[3]==100); }

  // --- THE CROSS-REPO CHECK: the exact line Ephymeris builds for the shipped
  //     GRGL profile, parsed by the parser that will receive it.
  //
  //     These two repos agree by convention and nothing enforces it: the app
  //     reads wire keys out of task.json, this parser reads them out of
  //     TASK_PARAM_LIST, and START_LINE_MAX is written down twice. A key the app
  //     sends and the firmware does not know is ignored in silence -- the
  //     session simply runs on the compiled-in value. Pasting the real line here
  //     is the cheapest thing that would notice.
  //
  //     Regenerate after editing GRGL/task.json:
  //       build_start_command(load_profile(<GRGL>), {f.metadata_key: f.default})
  { char line[START_LINE_MAX];
    int n = snprintf(line, sizeof(line),
      "START ERR=20000 ITI=4000 NPH=10000 NWP=2000 PRM=1000 POL=5 LZD=6000 "
      "LAZY=1 LZS=6000 LZM=30000 LZG=0 RW1=100 RW2=100 NT=1000 "
      "PW1=1 PW2=1 BS=30 CL=0 CR=0 BW=20 MCS=10 DBS=0.5 PMN=0.02 PMX=0.98 "
      "S0P=500 S0H=200 S0W=2000 S0O=4000 SEED=2147483646");
    assert(n > 0 && (size_t)n < sizeof(line));
    TaskParams p; parseStartCommand(line, p);
    // One assertion per group, so a dropped token names which one went.
    assert(p.errorDelay==20000 && p.standardITI==4000);          // trial timing
    assert(p.lazyRatDelay==6000 && p.lazyEscalationEnabled);     // abstention
    assert(p.rewardTimes[0]==100 && p.rewardTimes[1]==100);      // reward volume, per type
    assert(p.numTrials==1000 && p.blockSize==30);                // session
    assert(p.poolWeights[0]==1 && p.poolWeights[1]==1);          // trial pool
    assert(p.correctionLeft==0 && p.correctionRight==0);         // correction
    assert(p.biasWindow==20 && p.maxConsecutiveSide==10);        // anti-bias
    assert(p.odorPokeHold==500 && p.fluidWellPoll==2000);        // holds, via row 0
    assert(p.trialSeed==2147483646UL); }

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
