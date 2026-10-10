# A hypothetical rig definition is context-local

Previews ask "what would this wiring or vocabulary break?" by validating every saved task under a hypothetical [rig definition](../../GLOSSARY.md#rig-definition). They used to install it process-wide with `set_rig_source` / `set_vocabulary_source` and restore it afterwards, which let any thread reading at that moment, above all the rebuild that writes every `TaskPins.h`, generate from previewed pins or codes. We put the hypothetical in a `ContextVar` (`registry.hypothetical`), seen only by the code that installed it and the `asyncio.to_thread` worker it runs in.

## Considered options

- **Pass a `ChannelMap` / `Vocabulary` explicitly** through `validate`, `failures` and the generators. Honest, but it threads a parameter through every path that today calls `channels()` for a value that changes a few times a year; the registry's module-level injection exists to avoid exactly that.
- **Keep the process-wide swap and lock every reader.** Readers run on the event loop and in many unlocked workers; a lock held for a preview would stall the loop, and a missed reader brings the bug back silently.

## Consequences

A preview must not start its own thread inside `registry.hypothetical`: a plain `threading.Thread` starts with an empty context and would read the definition in force. `asyncio.to_thread` copies the context and is fine.
