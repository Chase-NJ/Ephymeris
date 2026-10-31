# Ephymeris

A lab app that runs rodent behavior sessions on six Arduino boxes and keeps the per-animal data they record.

## Language

<a id="rig-definition"></a>
**Rig definition**:
The rig wiring plus the strobe vocabulary in force on this machine: the channels, pins and strobe codes every generated sketch takes from the rig rather than from its task.
_Avoid_: rig configuration, rig settings

<a id="channel-set"></a>
**Channel set**:
The rig wiring's lab-wide half: every channel and what it is (type, role, the code names of its edges), with no pins. It carries its own content hash.
_Avoid_: channel registry, channel list

<a id="pin-map"></a>
**Pin map**:
The rig wiring's local half: which pin each channel of the channel set is on, on this machine's box.
_Avoid_: pinout (the shipped transcription a pin map starts from)

<a id="held-wiring"></a>
**Held wiring**:
Stored rig wiring that passes every check but that the record cannot vouch for as the wiring last saved, or confirmed, on this machine: copied in, changed by hand, a layout a later save replaced, or wiring saved here when a save after it did not finish. It is never in force, at any start, until its pins are confirmed and it is saved. Unrelated to a held session.
_Avoid_: unconfirmed wiring, pending wiring

<a id="held-session"></a>
**Held session**:
The one session that holds the rig, from its mapping's confirmation (or a resume) until it ends or is abandoned. It stays held between groups, and it may still read `configuring`.
_Avoid_: running session, active session

<a id="cohort-archive"></a>
**Cohort archive**:
A cohort's sessions and runs as one whole: those this machine recorded, and the recovered runs filed under the sessions they belong to.
_Avoid_: the cohort's data, history

<a id="recovered-run"></a>
**Recovered run**:
A run known only from its file, with no run record behind it, which a rescan adopted. It counts under the recorded session sharing its folder's prefix, number and date, else under a recovered session of its own.
_Avoid_: orphan (once adopted), synthetic run
