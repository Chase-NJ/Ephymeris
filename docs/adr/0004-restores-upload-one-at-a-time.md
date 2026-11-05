# Restores upload one at a time

Supersedes the upload half of [ADR 0002](0002-restores-upload-side-by-side.md). Restores still run side by side and share one compile of the box utility, but their uploads now take turns: `SharedBuilds` (`ports/flashing.py`) holds one rig-wide upload lock inside the build gate, so only one `avrdude` talks to a board at a time, whoever asked for the flash.

ADR 0002 judged uploads safe to run together because six uploads to six ports share no state but a read-only build file. That holds for the software, not the wire. On a lab machine, one box's restore at startup failed intermittently, and a later flash of the same box failed avrdude's read-back with a verification mismatch. Six uploads at once is the heaviest load the rig ever puts on its USB path: every board resetting into its bootloader and taking page writes at the same moment, through shared hubs and their power. A marginal link on one box survives a lone upload and fails under that load. Uploading in turn takes the concurrency out of the picture and removes the rig's only many-boards-at-once electrical event.

## Considered options

- **Run whole restores one at a time, through the queue's scheduling.** That's the smallest change to `_next_runnable`, but a build is retired when its last upload ends, so each restore would compile the box utility again. On Windows that's several seconds a box, even with a warm cache.
- **Serialize only startup restores.** Startup is where the failures showed, but a wiring save or a vocabulary edit (`rebuilt()`) and **Reflash boxes** restore every box at once too, and put the same load on the same path.
- **Leave it concurrent and fix the hardware.** The hardware should be fixed regardless. But the cost here is about 3 s per box at startup, and the gain is that a weak link fails less often and is easier to tell apart from a bad board.

## Consequences

A cold start takes about one upload per box in turn rather than one upload's time in all, about 20 s for six boxes. A restore takes its port before it waits its turn, so every box being restored reads as flashing until its own upload ends. Restores side by side each hold the rig definition's read side until their upload lands, so a waiting write waits for the last of them. Session and Debug flashes already ran alone; for them, nothing changes.
