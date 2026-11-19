# Ephymeris

A lab app that runs rodent behavior sessions on six Arduino boxes and keeps the per-animal data they record.

## Language

<a id="rig-definition"></a>
**Rig definition**:
The rig wiring plus the strobe vocabulary in force on this machine: what every generated sketch takes from the rig rather than from its task.
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
Stored rig wiring that passes every check but is not vouched for as last saved or confirmed on this machine (copied in, changed by hand, superseded, or followed by an unfinished save). Never in force until its pins are confirmed and it is saved. Unrelated to a held session.
_Avoid_: unconfirmed wiring, pending wiring

<a id="stream-grammar"></a>
**Stream grammar**:
How the trial runner frames a trial's strobes. Grammar 2 opens each trial with a header, carries exactly one outcome code, closes with `END_TRIAL`, and is announced as `STREAM=2`; grammar 1 is every stream recorded before the header existed, and still decodes.
_Avoid_: strobe format, stream version

<a id="exposed-parameter"></a>
**Exposed parameter**:
A task parameter the editor shows and the Start dialog offers; every other parameter stays at its default, out of sight, and is still sent to the board.
_Avoid_: visible parameter, enabled parameter

<a id="held-session"></a>
**Held session**:
The one session that holds the rig, from its mapping's confirmation (or a resume) until it ends or is abandoned, including between rounds; it may still read `configuring`.
_Avoid_: running session, active session

<a id="round"></a>
**Round**:
One set of animals run together in a session: up to six, each in a box and on a task chosen for that round. A session has one or more, and any animal of the cohort may run in any of them.
_Avoid_: group, group run, batch

<a id="usual-box"></a>
**Usual box**:
The box session set-up offers first for an animal. A default and nothing more: animals may share one, and the box a run used is on its run record.
_Avoid_: standing box, assigned box

<a id="trial-type"></a>
**Trial type**:
One kind of trial a spine task presents: a row of its definition, with a name, the channel that plays each role, and what each answer means. A trial-table task's equivalent is a condition.
_Avoid_: row (in anything a user reads), condition (for a spine task)

<a id="target"></a>
**Target**:
A group of an implanted device's channels that sit at one place in the brain, with a region, a hemisphere and coordinates. A device has one or more; the lab's custom 32-channel electrode has two, one per bundle of 16.
_Avoid_: site (Intan's word for one contact), bundle (the wires, not where they are)

<a id="role"></a>
**Role**:
A part a channel plays in a spine task's trial (the port the animal pokes, the sample, the left well, the line that pays): a slot of the definition that each trial type binds to a channel of this rig.
_Avoid_: slot (in anything a user reads), wire

<a id="step"></a>
**Step**:
One phase of a spine task's trial as the editor shows it: a Wait, Hold, Present, Delay, Response window, Counter, Outcome or ITI.
_Avoid_: phase (in anything a user reads), state

<a id="penalty"></a>
**Penalty**:
How long a spine trial that ended a given way waits before the next trial, in place of the ITI; set on the exit that ends it (a Wait's timeout, a broken hold, an abort) or on a contingency-map entry.
_Avoid_: timeout (a phase's own duration), punishment

<a id="decode-only-sketch"></a>
**Decode-only sketch**:
A sketch kept in the bundle only so its runs still decode: never offered at mapping or in Debug Mode, never flashed or started. Its `task.json` says `decodeOnly`.
_Avoid_: retired sketch, hidden sketch

<a id="cohort-archive"></a>
**Cohort archive**:
A cohort's sessions and runs as one whole: those this machine recorded, and the recovered runs filed under their sessions.
_Avoid_: the cohort's data, history

<a id="recovered-run"></a>
**Recovered run**:
A run known only from its file, with no run record, adopted by a rescan. It counts under the recorded session sharing its folder's prefix, number and date, else under a recovered session of its own.
_Avoid_: orphan (once adopted), synthetic run
