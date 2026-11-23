/*
  TaskTrials.h -- the TASK SIMULATOR's trial table: the rows the host sent on its
  ROW lines (tasksim.cpp), built into TrialType exactly as a generated
  TaskTrials.h writes them. Included by the sketch after <BehaviorBox.h>.

  A pointer and a count, not an array: the sketch only ever indexes the table
  and hands it to the selector, and a generated header's `kTrials[]` cannot be
  sized after the program has started.
*/

#ifndef TASK_TRIALS_H
#define TASK_TRIALS_H

inline TrialType *bbsim_buildTable()
{
  const int count = (int)bbsim_rows.size();
  TrialType *table = (TrialType *)::operator new(sizeof(TrialType) * (count > 0 ? count : 1));
  for (int i = 0; i < count; i++)
  {
    const BbsimRow &row = bbsim_rows[i];
    if (row.isGo)
      new (&table[i]) TrialType(true, Odors[row.odorIndex],
                                row.side == 'R' ? rightWell : leftWell, row.rewardIndex,
                                row.onsetCode, row.fluidCode, row.stopFluidCode,
                                row.rewardMs, row.typeCode);
    else
      new (&table[i]) TrialType(false, Odors[row.odorIndex], SENTINEL, SENTINEL,
                                row.onsetCode, 0, 0, 0, row.typeCode);
  }
  return table;
}

static TrialType *const kTrials = bbsim_buildTable();
static const int kTrialCount = (int)bbsim_rows.size();

#endif // TASK_TRIALS_H
