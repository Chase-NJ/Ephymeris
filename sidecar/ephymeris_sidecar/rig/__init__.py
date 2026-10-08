"""The rig's own description of itself: what each channel means, and where it is.

Two registries and one operator-owned document:

  * `schema/channels.v1.json` -- WHAT a channel is (kind, well, port slot).
  * `hardware/<pinout>.json`  -- WHERE it is on this box generation.
  * `<data_dir>/hardware/rig.json` -- the operator's own wiring, when they have
    edited one. It REPLACES the shipped pair rather than merging with it
    (`hardware/store.py` says why), and is composed here by `channels()`.

Plus the strobe vocabulary: `<data_dir>/strobes/vocabulary.json`, seeded from
`schema/strobe_vocab.default.json` and read through `vocabulary()`.

This package was extracted from the task-spec compiler (`taskgraph/registries.py`)
when that system was removed. The registries survived because they describe the
BOX, not the compiler: the rig wiring editor reads them, and the task-profile
code generator writes pin numbers and strobe codes out of them into the firmware
it compiles.
"""
