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

<a id="stream-grammar"></a>
**Stream grammar**:
How the trial runner frames the strobes of a trial. Grammar 2 opens every trial with a header, carries exactly one outcome code and closes with `END_TRIAL`, and a board announces it as `STREAM=2`; grammar 1 is every stream recorded before the header existed, which still decodes.
_Avoid_: strobe format, stream version

<a id="exposed-parameter"></a>
**Exposed parameter**:
A task parameter the editor shows and the Start dialog offers; every other parameter stays at its default, out of sight, and is still sent to the board.
_Avoid_: visible parameter, enabled parameter

<a id="held-session"></a>
**Held session**:
The one session that holds the rig, from its mapping's confirmation (or a resume) until it ends or is abandoned. It stays held between groups, and it may still read `configuring`.
_Avoid_: running session, active session

<a id="trial-type"></a>
**Trial type**:
One kind of trial a spine task presents: a row of its definition, with a name, the channel that plays each role, and what each answer means. A trial-table task's equivalent is a condition.
_Avoid_: row (in anything a user reads), condition (for a spine task)

<a id="role"></a>
**Role**:
A part in a spine task's trial that a channel plays: the port the animal pokes, the sample, the left well, the line that pays. A slot of the definition; each trial type binds it to a channel of this rig.
_Avoid_: slot (in anything a user reads), wire

<a id="step"></a>
**Step**:
One phase of a spine task's trial as the editor shows it: a Wait, Hold, Present, Delay, Response window, Counter, Outcome or ITI.
_Avoid_: phase (in anything a user reads), state

<a id="penalty"></a>
**Penalty**:
How long a spine trial that ended a given way waits before the next trial, in place of the inter-trial interval: set on the exit that ends it (a Wait's timeout, a broken hold, an abort) or on a contingency-map entry.
_Avoid_: timeout (a phase's own duration), punishment

<a id="decode-only-sketch"></a>
**Decode-only sketch**:
A sketch kept in the bundle so the runs it recorded still decode, but never offered at mapping or in Debug Mode, and never flashed or started. Its `task.json` says `decodeOnly`.
_Avoid_: retired sketch, hidden sketch

<a id="cohort-archive"></a>
**Cohort archive**:
A cohort's sessions and runs as one whole: those this machine recorded, and the recovered runs filed under the sessions they belong to.
_Avoid_: the cohort's data, history

<a id="recovered-run"></a>
**Recovered run**:
A run known only from its file, with no run record behind it, which a rescan adopted. It counts under the recorded session sharing its folder's prefix, number and date, else under a recovered session of its own.
_Avoid_: orphan (once adopted), synthetic run
