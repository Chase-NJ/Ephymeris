# Ephymeris

A lab app that runs rodent behavior sessions on six Arduino boxes and keeps the per-animal data they record.

## Language

<a id="rig-definition"></a>
**Rig definition**:
The rig wiring plus the strobe vocabulary in force on this machine: the channels, pins and strobe codes every generated sketch takes from the rig rather than from its task.
_Avoid_: rig configuration, rig settings

<a id="held-session"></a>
**Held session**:
The one session that holds the rig, from its mapping's confirmation (or a resume) until it ends or is abandoned. It stays held between groups, and it may still read `configuring`.
_Avoid_: running session, active session
