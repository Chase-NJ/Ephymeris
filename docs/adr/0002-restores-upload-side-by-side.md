# Restores upload side by side

The flash queue ran one flash at a time, rig-wide, because two `arduino-cli` builds at once are slower than one after the other on the lab machines, and a half-flashed pair is worse than a whole one. That made a cold start six restores in a row, about 20 s with a warm build cache, almost all of it uploads. We keep one compile at a time and let utility baseline restores upload together: restores share one compile of the box utility (`SharedBuilds`, `ports/flashing.py`) and each uploads to its own serial port at once. Session and Debug flashes still run alone.

The serial rule rested on the build, and an upload builds nothing: it runs `avrdude` against the build `arduino-cli` left in its build directory. Six uploads go to six ports and share no state but that read-only file. The `arduino-cli` daemon runs concurrent `Upload` RPCs, each with its own `avrdude`; two uploads to two unresponsive ports took 1.8 s together, the same as one alone.

## Considered options

- **Defer the cold restore until a box is needed.** Keeps the queue serial, but the placement walk is the first thing that needs every box, and it would then wait for six flashes in a row anyway.
- **Run whole flashes, compile included, side by side.** Simplest change to the worker, but it brings back the concurrent builds the serial rule existed to avoid, and a compile of a folder rewrites the build an upload of that folder is reading.
- **Parallelise every origin.** A session or Debug flash is something a person is watching, and nothing needs it to run beside anything else. Keeping it alone means it never shares a compile with a restore or rebuilds a folder whose build a restore is uploading.

## Consequences

A compile of a folder must wait until every upload of its older build has ended. `SharedBuilds` does this, and a flash outside the queue would not. Restores side by side each hold the rig definition's read side through their upload, so a waiting write now waits for the slowest of them. A cold start with a broken build fails every restore that shared the compile, which is the same result six serial compiles would have reached.
