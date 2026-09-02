"""Task profiles: the operator's task, compiled into firmware.

A **task definition** is what the operator authors on the Task tab — the trial
table, how the next trial is chosen, the shaping ramp, and the numbers. The
**generator** turns one plus this rig's wiring into a compilable sketch folder,
which `discovery.py` then finds as an ordinary sketch. From there, `port.flash`,
the session flow, `tasks.getProfile` and Analytics need no special case at all.

    model.py     what a definition is
    fields.py    the parameter surface, declared once instead of per sketch
    validate.py  everything wrong with one, located
    generate.py  definition + wiring -> .ino, TaskPins.h, TaskTrials.h, task.json
    store.py     <data_dir>/tasks/, and regeneration on a wiring change

The split that matters: what fits on a `START` line stays on the wire, so one
flashed binary serves six boxes tuned differently; everything else — the trial
table, the pins, the stage COUNT — is compiled in, because it cannot fit and
because pins have to be constants. See `docs/tasks.md` §1.1.
"""
