"""The rig's own description of itself: what each channel means, and where it is.

Two registries and the operator's own pair of documents:

  * `schema/channels.v1.json` -- WHAT a channel is (kind, type, role, slot).
  * `hardware/<pinout>.json`  -- WHERE it is on this box generation.
  * `<data_dir>/hardware/channel_set.json` + `pin_map.json` -- the operator's
    own wiring, when they have edited one: the channel set (lab-wide) and the
    pin map (this box). It REPLACES the shipped pair rather than merging with
    it (`hardware/store.py` says why), and is composed here by `channels()`.

Plus the strobe vocabulary: `<data_dir>/strobes/vocabulary.json`, seeded from
`schema/strobe_vocab.default.json` and read through `vocabulary()`.

Together the wiring and the vocabulary are the rig definition, and
`definition.py` owns every write to them (TASKS.md#the-rig-definition).

This package was extracted from the task-spec compiler (`taskgraph/registries.py`)
when that system was removed. The registries survived because they describe the
BOX, not the compiler: the rig wiring editor reads them, and the task-profile
code generator writes pin numbers and strobe codes out of them into the firmware
it compiles.
"""
