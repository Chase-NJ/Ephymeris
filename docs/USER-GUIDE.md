# Ephymeris user guide

This guide is for the people who run daily behaviour sessions. It covers what to click, what the screen
is telling you, and what never to do. Words in **bold** are labels you will see on screen. Words you may
not know are in the [Glossary](#glossary).

The screenshots come from a demo rig of six boxes running a cohort called *Odor Discrimination 2026*
(animals `remy1` to `remy12`, in Group A and Group B). Your names and numbers will differ.

## Before you start

**What Ephymeris does.** It runs behaviour sessions for a cohort of animals. It puts the right program
(the task) on each box, starts the boxes, shows you live progress, and saves every event to a data file
for each animal while the session runs. Afterwards, the **Analytics** screen shows how each animal is
doing.

**The rig.** There are up to six behaviour boxes, numbered 1 to 6. Each box has a small computer inside
it, an Arduino board, connected to the lab computer by USB. Inside each box are odor ports, where the
animal pokes its nose to sample an odor, and water wells, where it pokes to answer and gets a drop of
water when it is right. One animal goes into one box.

**A session** is one sitting at the rig: you pick a cohort, place a group of animals in the boxes, run
them, and maybe swap in a second group. Every animal gets its own file. A session has a **prefix** (the
task's short name, such as `2O-Bdisc`) and a **session number**.

**Before your first session, check three things:**

1. **A cohort exists** with animals, and each animal has a box in its group (see
   [Setting up a cohort](#setting-up-a-cohort)).
2. **The boxes are bound.** On the **Rig** tab, each box is linked to its board. Your lab manager
   normally does this once.
3. **A task is saved** on the **Task** tab. Your lab manager normally does this too.

## A tour of the app

The sidebar on the left lists the screens: **Dashboard**, **Rig**, **Cohorts**, **Task**, **Recording**
and **Analytics** at the top, and **Settings** near the bottom. At the very bottom is a small star
figure, one star per box, with a count such as *6/6 boxes* under it. A box's star is lit when its board
is connected, dim when it is missing, green while that box is running (or while you are placing an
animal in it), and red when it has a fault. You can check it from any screen.

<img src="images/sidebar-status.webp" alt="The sidebar's star figure: six lit stars joined by lines, one per box, with '6/6 boxes' underneath" width="280">

**Dashboard.** The home screen. The big button is **Start a Session** (or **Resume Session** while one is
running). Below it is **Start a Recording**, for sessions recorded with Intan. Below that, the session
dock lists anything that needs you: a running session, a set-up you left half-done, or a session that
ended unexpectedly. The tiles on the right show the rig, the task, your cohorts, the boxes (with how many
are connected), and recent results. The 3D sky behind everything is the rig: click a box's star, or its
row in the **Boxes** tile, to open that box's panel (see [Checking a box](#checking-a-box)).

![The Dashboard: Start a Session and Start a Recording on the left, the rig drawn as a 3D sky of box stars in the middle, and tiles for Rig, Task, Cohorts, Boxes (6/6 connected) and Analytics on the right](images/dashboard.webp)

While a session is running, the big button reads **Resume Session** and the dock shows the session: its
name, which boxes are recording, and **Open Mission Control** and **End Session** buttons.

![The Dashboard during a session: Resume Session at the top, and a dock card for 2O-Bdisc_15 listing each box and animal, with Open Mission Control and End Session buttons](images/dashboard-running.webp)

**Rig.** What each box is: which board is box 3, which program idle boxes rest on, and the wiring of
every pin. Usually set up once by the lab manager. The **Boxes** table has each box's label, its bound
board, a **Handshake** column and a **Test** button. Under **Utility baseline**, a chip per box says
whether it is **Ready** on the resting program.

![The Rig tab: the Boxes table with label, bound board, handshake and Test button for each of six boxes, and below it the Utility baseline section showing BOX_Utility and a Ready chip for every box](images/rig.webp)

**Cohorts.** Your groups of animals, drawn as planets. Click one to open it, or click the small disc
labelled **New cohort** to make a new cohort. The **Search…** box and the **Show archived** switch are at
the top left.

![The Cohorts screen: three cohorts drawn as planets in a 3D sky, a small disc labelled New cohort, and a search box and Show archived switch at the top left](images/cohorts.webp)

**Task.** What the animal does: the trial types, the shaping ramp and every number the box uses. Saving
a task makes a program that can be put on a box. Usually managed by the lab manager. The landing page
lists each saved task with its number of conditions, its stages and whether it is **ready**.

![The Task tab: a + New task row, then three saved tasks (4-Odor Discrimination, Shaping - Both Sides, 2-Odor Discrimination), each marked ready, with Strobes and Walkthrough tiles below](images/task-landing.webp)

**Recording.** The link to the Intan RHX recording software, which digital input each box is wired to,
and the default recording settings. See [Recording with Intan](#recording-with-intan).

**Analytics.** Results. Pick a cohort to see its sessions, animals and learning curves.

![The Analytics landing: the same cohort planets as the Cohorts screen, under the heading "Pick a cohort to study its recorded sessions"](images/analytics-landing.webp)

**Settings.** Where data is saved (**Data directory**), where a backup copy goes (**Backup directory**),
**Reduce motion**, and how the star figure is drawn (**Constellation**). If no backup directory is set,
a note under it says so.

![The Settings screen: Data directory set to a folder, Backup directory showing Not set with a warning that data is only on one drive, the Reduce motion switch, and the Constellation picker](images/settings.webp)

## Setting up a cohort

A **cohort** is a batch of animals that are trained together.

### Create a cohort

1. Open **Cohorts** and click the small disc labelled **New cohort**. A **New Cohort** page opens.
2. Type a **Name**. It must be unique among active cohorts.
3. If no **Data directory** is set in Settings, the page asks for a **Data folder**. Otherwise the folder
   is made for you inside the Data directory, named after the cohort.
4. Add **Animals**. The quickest way is the bulk box: paste a list of names (one per line, or copied
   from a spreadsheet column), or type a pattern like `R- × 8` to make `R-1` to `R-8`. Click **Add**.
   Names already in the cohort are skipped. You can also fill in **Sex**, **ID number** and **Notes**.

   ![The cohort editor: the Name field, the Data folder with its Change data folder… button, and the Animals section with the bulk-add box and a table of animals with Sex, ID number and Notes](images/cohort-editor.webp)

5. Optional: under **Cages & spaceships**, drag cagemates onto a shared spaceship (one per home cage).
   **Add a spaceship** makes another one.
6. Under **Groups & boxes**, drag each animal onto the box it runs in. You can also click an animal, then
   click its box.

   ![The lower half of the cohort editor: spaceship cards each holding two cagemates, then Groups & boxes with Group A and Group B, each showing Box 1 to Box 6 with one animal in each](images/cohort-groups.webp)

7. Click **Create cohort**. To change an existing cohort later, open it and click **Save changes**.

You can save a cohort before it is finished and fill it in over the next few days. Ticks at the top of
the page (**Named**, the number of animals, **Ready to run**) show what is still missing.

### Groups

A **group** is the set of animals that are in the boxes at the same time. If you have more animals than
boxes, split them into groups: each group gets the whole rig, so box numbers repeat between groups. Use
**Split into groups** or **Add a group**, then drag animals between group cards. A box can hold only one
animal per group. **Fill boxes** assigns boxes to everyone in a group who does not have one. Anyone in a
group without a box is listed under **No box yet**.

Groups have no fixed order. You choose which group runs when you start the session, and again each
time you switch.

### Auto-balance

**Auto-balance…** proposes a complete grouping for you.

1. Under **Split by**, choose **Number of groups** or **Max group size**, and type the number in the box
   beside it.
2. Turn on **Balance by sex** to spread males and females evenly (only offered when some animals have a sex).
3. Click **Suggest grouping**. A preview appears. Nothing is saved yet.
4. Adjust the preview by hand if you like, then click **Apply grouping**, or **Cancel**.

![The Auto-balance panel: Split by set to Number of groups, Groups set to 2, the Balance by sex switch, Suggest grouping, and a preview of Group 1 and Group 2 with each animal's box, above Apply grouping and Cancel](images/auto-balance.webp)

Applying replaces the current grouping entirely. A group can never have more than six animals.

### The data folder

The cohort's data folder is fixed when the cohort is made. **Renaming a cohort does not move or rename
its folder.** To move it, use **Change data folder…**: with **Move existing contents to the new location**
ticked, the files are moved and the new folder must be empty. With it unticked, nothing is moved; the
cohort is simply pointed at a folder that already holds its data.

### Archive and delete

**Archive** hides a cohort but keeps everything. Turn on **Show archived** on the Cohorts screen to see
archived cohorts and **Restore** one. **Delete permanently** is only offered for archived cohorts. It
removes the cohort, its animals and groups from Ephymeris, but **never deletes its data folder**.

## Running a session

A session day at a glance. Each step is explained in the sections below:

```mermaid
flowchart TD
    cohort["Cohort ready: animals in groups,<br/>each with a box"] --> start["Dashboard: Start a Session,<br/>or Start a Recording"]
    start --> configure["Configure: cohort, first group,<br/>prefix, session number"]
    configure --> boxes["Boxes: check each box's task"]
    boxes --> place["Place the animals in box-number order,<br/>closing each box as you go"]
    place --> flashed["Each box loads its program"]
    flashed --> recording{"Recording session?"}
    recording -->|"yes"| record["Set Up the Recording"]
    recording -->|"no"| run["Mission Control: Start All,<br/>watch until every box finishes"]
    record --> run
    run --> another{"Another group to run?"}
    another -->|"yes"| swap["Switch Group: animals home,<br/>pick the next group"]
    swap --> boxes
    another -->|"no"| finish["End session"]
    finish --> results["Check the results in Analytics"]
```

A row of dots at the top of every step (**Configure**, **Boxes**, **Run**, **Finish**, plus **Record**
for a recording) shows where you are.

### Configure

1. On the Dashboard, click **Start a Session**.
2. Pick the **Cohort**.
3. Pick the **Group** that goes on the rig first. Each group card lists which animal goes in which box.
   Only groups with at least one animal assigned to a box are offered.
4. Pick the **Prefix** (the task's short name). Use **Add a prefix** for a new one.
5. Check the **Session number**. It is filled in with the next number for this prefix.
6. Optional: a **Time limit** in minutes. Each box stops by itself that many minutes after *it* started.
7. Click **Continue**.

![The Configure step of Start a Session: cohort cards with Odor Discrimination 2026 selected, Group A and Group B cards with Group A selected, and the Prefix and Session number fields](images/session-configure.webp)

If a warning says this session number already has data from today, you are about to write into the
same folder. That is usually a mistake. If you meant to continue today's session, use **Continue today**
instead (see [Continue a session from earlier today](#continue-a-session-from-earlier-today)).

### Boxes

This step is titled **Confirm boxes**. Each animal in the group gets a card with two pickers: the
**sketch** (the task program) and the **box** it goes in. Changes here apply to this run only.

1. Pick the sketch for each box. A new card starts at **— none —**; the list groups the sketches by
   kind.

   ![The Confirm boxes step with remy1's sketch list open, showing — none —, GRGL, BOX_Utility, GRGL_Sim, 2-Odor Discrimination, 4-Odor Discrimination and Shaping - Both Sides](images/session-sketch-picker.webp)

2. Once a sketch is picked, the card shows the task's settings as one summary line with the number of
   parameters. Open it to see **Quick tune** (the values usually changed per animal, per day) and
   **All parameters**.

   ![Confirm boxes with every card set to 2-Odor Discrimination and Box 1 to Box 6, each with a collapsed "28 parameters" line, above the Place the animals button](images/session-boxes.webp)

   ![One box card with its parameters opened: the QUICK TUNE section showing Left and Right correction budgets, each with a short explanation](images/session-quick-tune.webp)

3. If a box shows an error, read its message and click **Acknowledge**. You cannot continue while any
   box is in an error state.
4. Click **Place the animals**. (**Back** returns to Configure.)

### Place the animals

The app walks you down the bench, one box at a time, **in box-number order**.

1. The screen points at one box: *Place this animal in box 1*. If the rig allows it, **that box lights
   up** (*Its light is on, and goes out when you confirm*), and its star in the sidebar turns green. The
   light only confirms the box. Always check the number on the box itself.
2. Put the named animal in that box and close it.
3. Click **Enclosure closed**. That box starts flashing (loading its program) while you fetch the next
   animal.

   ![Place the animals: a drawing of remy1 being lifted into box 1, and remy1's card saying "Place this animal in box 1 — Its light is on" with the Enclosure closed button. Box 1's star in the sidebar is green](images/session-placement.webp)

4. Repeat until every animal is in. Boxes already done are marked **flashed** with a tick.
   **Skip this box** passes over one box; **All animals are in** finishes the walk in one click if you
   already loaded them.

   ![Later in the walk: remy1 and remy2 are ticked and marked flashed, and the screen now asks for remy3 in box 3](images/session-placement-flashing.webp)

If you loaded the rig before opening this screen, click **They're already in — flash all** instead of
**Place the animals**.

> [!CAUTION]
> **An animal in the wrong box produces a complete, normal-looking data file under the wrong name.**
> Nothing later can detect it. Follow the box order, and trust the number on the box over the light.

When every box has flashed, Mission Control opens by itself (or the Record step, for a recording). If a box fails to flash, click
**Acknowledge** on its card, then **Retry flash**.

### Record

Only a session started with **Start a Recording** has this step, after the boxes have flashed. See
[Recording with Intan](#recording-with-intan).

### Run

On **Mission Control**, click **Start All** to start every box, or **Start** on one box. Before anything
has started, every box tile says `IDLE` and *No live metrics yet*, and the second button reads
**Discard session**. See [During a session](#during-a-session).

![Mission Control before starting: the session name 2O-Bdisc_15, the clock, Start All and Discard session on the left, and six box tiles on the right, each IDLE with Start, Stop and Reset buttons](images/mission-control-ready.webp)

### Switching groups

When every box in the group has finished, a prompt appears with a return checklist: *All boxes
finished — return each animal to its home cage, then pick the next group*.

1. Take each animal back to its home cage and tick it off, or click **All animals are out**.
2. Click **Pick next group**, or **End session** if you are done. You can also click **Switch Group** at
   any time after a group has run.

   ![The group-finished prompt over Mission Control: a drawing of an animal going home, a checklist of the six animals with "0 of 6 back in their cages", All animals are out, and the Pick next group and End session buttons](images/group-switch-prompt.webp)

3. On the **Next Group** step, choose **any** group and click **Run this group**. A group that already
   ran shows when it ran (for example *ran 10:42*). Running it again is allowed: it adds new files beside
   the old ones and overwrites nothing.

   ![The Next Group step: Group A marked "ran 23:34", Group B selected, and the Run this group and End session buttons](images/group-step.webp)

4. You return to the Boxes step for the new animals. Confirm sketches and place the animals again.

### Ending the session

When the last group finishes, a **That's a wrap** window appears. Tick each animal home, then click
**End session**. The files are already saved, and Analytics opens on this session. **Run another group**
is still offered if you need it; **Not yet** closes the window.

![The That's a wrap window: "Every group has run", a checklist with all six animals ticked home, and the Not yet, Run another group and End session buttons](images/wrap-up.webp)

You can also click **End Session** in Mission Control at any time. If no box ever ran, the button reads
**Discard session** and nothing is saved. Only ending the session finishes it; switching groups never does.

> [!IMPORTANT]
> **End Session and Switch Group stop any box still running straight away, cutting its current trial
> short.** If you want every trial complete, click **Stop** on each box and wait for **Finished** before
> ending. (Recording sessions are different: they wait for each box to finish its trial.)

### Continue a session from earlier today

If the app was closed between groups, or a session was ended too early, you can run another group under
the same session (same folder, same number):

- Click **Start a Session**, pick the cohort, and under **Continue today** click **Continue**, or
- If the Dashboard dock lists the session as **Ended unexpectedly**, click **Continue with another group**.

![The Configure step with a CONTINUE TODAY panel under the cohort: session 2O-Bdisc_15, "ran Group A, Group B", and a Continue button](images/session-continue-today.webp)

Then choose the group and click **Run this group**.

This only works on the same day. It cannot resume a group in the middle of its run.

## During a session

Mission Control shows the 3D view of the session, a tile for each box, and the session controls. You can
leave it (for example to the Dashboard) and the session keeps running; come back with **Resume Session**.
The line under the session name reminds you how Stop works: *Stop takes effect at the next trial
boundary*.

![Mission Control while running: the session name, the clock with time elapsed, Switch Group and End Session on the left, the session drawn as a 3D sky, and box tiles on the right, each IN_SESSION with its own clock and two live metrics](images/mission-control.webp)

### Reading a box tile

<img src="images/box-tile.webp" alt="One running box tile: 'Box 1 · remy1', the sketch name, the clock 1:28, a green IN_SESSION chip, Start, Stop and Reset buttons, and two live metrics, P(right well | Odor…) 0.60 and P(left well | Odor…) 0.90, each with a small trend line" width="420">

- **Box 3 · Remy** names the box and the animal, with the sketch underneath.
- **The clock** shows time since *this* box started (`12:04`). With a time limit it shows both
  (`12:04 / 30:00`). At the limit it reads *time up — stopping at the next trial boundary*: the box is
  finishing its last trial and will stop by itself.
- **The state chip** shows the box's state. `IN_SESSION` (green) means running. `IDLE` means not running.
  `FLASHING` and `RESETTING` are brief. `ERROR` (red) means something went wrong; hover over it to read why.
- **Live metrics** show how the animal is doing, such as the rolling chance of a correct answer for each
  odor, with a small trend line. They fill in as trials complete.
- **Finished — …** replaces the metrics when the box's run is over, with the reason. *Finished —
  BF_END_SESSION received* means the box ended on its own; *Finished — board disconnected* means it lost
  its connection (see below).

Click a tile, or a star, to see that box's full panel: its **Rolling accuracy**, the **Trial flow**
diagram with the state the box is in right now, a chart of each odor's answers over time, the
**Outcome mix**, the **Live metrics** and the **Recent strobes** (the latest events from the board).
**Back to overview** (or Esc) returns.

![A box's full panel for remy1: Back to overview at the top left, Start/Stop/Reset and Rolling accuracy 0.70 at the top right, the Trial flow diagram with the current state lit, the P(right | odor) chart, the Outcome mix, Live metrics and Recent strobes](images/box-panel.webp)

### The buttons

- **Start** starts that box. Starting resets the board, waits for it to be ready, then sends the task.
- **Stop** asks the box to stop. **It stops at the end of the current trial, not instantly. Wait for it.**
  Do not click again or reset it while you wait.
- **Reset** restarts the board. It works only while the box is not running. Use it if a box will not start.

### When a box shows ERROR or a board disconnects

If a board loses its USB connection, or something else fails, that box's run stops at once and its state
becomes `ERROR`. Its tile reads *Finished — board disconnected* (or another reason), and its star turns
red. Everything recorded up to that moment is safe. Other boxes keep running.

![Mission Control with box 2 in ERROR: its tile reads "Finished — board disconnected" while boxes 1, 3 and 4 keep running, and box 2's star in the sidebar is red](images/mission-control-error.webp)

<img src="images/box-tile-error.webp" alt="Close-up of the box 2 tile: a red ERROR chip and the line 'Finished — board disconnected'" width="420">

1. Write down the box, the animal and the time.
2. Check the USB cable and that the board's lights are on.
3. To clear the error: go to the **Dashboard**, click that box's star, and click **Acknowledge** in its
   panel. The panel shows the fault under **Connection**, for example *board disconnected or
   unreadable*, with **Acknowledge** beside it.

   ![Box 2's Debug panel opened from the Dashboard: the header says fault, the Connection section shows error and the message "board disconnected or unreadable" next to an Acknowledge button, and the console lists the board's last events](images/debug-error.webp)

4. Ask your lab manager before restarting that animal. If you press **Start** again, a new file is begun
   for it and the earlier file is kept.

What to do depends on where you see the error. **Reset** never clears it; only **Acknowledge** does.

```mermaid
flowchart TD
    where{"Where does the box show ERROR?"}
    where -->|"Boxes step, while programs load"| card["Read the message on the box's card"]
    card --> retry["Click Acknowledge, then Retry flash"]
    retry --> again{"Did it fail again?"}
    again -->|"yes"| tellFlash["Tell the lab manager"]
    again -->|"no"| carryOn["Carry on placing animals"]
    where -->|"Mission Control, during a run"| writeDown["Write down the box,<br/>the animal and the time"]
    writeDown --> cable["Check the USB cable<br/>and the board's lights"]
    cable --> clear["Dashboard: click the box's star,<br/>then Acknowledge"]
    clear --> ask["Ask the lab manager before<br/>starting that animal again"]
    where -->|"Anywhere else"| panel["Dashboard: click the box's star,<br/>then Acknowledge"]
```

### Session write failed

A red line on a box tile that starts **Box N: session write failed** means **that box's data is not being
saved**. The animal is still running. The usual cause is a full or disconnected drive. Tell the lab
manager straight away, and note the box and time.

### Backup pill

The Mission Control header shows **backup ok** or **backup failing**. A failing backup never stops the
session and data is still saved locally. Tell the lab manager after the session.

### Do not touch during a session

- Do not unplug a box or its USB cable.
- Do not close Ephymeris. Closing it stops every box's recording.
- Do not open the data folder and move or edit files.
- Do not change the Rig, Task or Settings screens.

## Recording with Intan

A recording session runs the behaviour and an Intan RHX electrophysiology recording together. Details
for maintainers are in [Recording with Intan RHX](RECORDING.md).

**Once, on the Recording tab** (usually done by the lab manager):

- **Connection**: shows whether Ephymeris is talking to RHX, with **Connect** or **Disconnect**. Leave
  the **TCP ports** at RHX's defaults (5000, 5001, 5002) unless someone changed them in RHX's Remote TCP
  Control dialog.
- **Sync inputs**: each recorded box needs its **Digital input**, the RHX input its sync cable plugs into.
  The tab also says if the rig's wiring has no sync channel yet; the lab manager adds one on the Rig tab.

  ![The Recording tab: Connection showing connected to RHX 3.5.0 with a Disconnect button, the TCP ports, and the Sync inputs table giving each box a digital input DIN 1 to DIN 6, with "This rig's wiring has a sync channel" at the bottom](images/recording-tab.webp)

  *This screenshot is from a demo machine whose ports were changed to 5100–5102. RHX's own defaults are
  5000–5002.*

- **Defaults**: where recordings are saved, the file format, which signals to save, and the spike
  thresholds.

  ![The Recording defaults: Save location, File format set to Per signal type, switches for Save wideband, Save spikes, Spike snapshots, Save highpass and Save lowpass, and Set thresholds at 5 × RMS, negative](images/recording-defaults.webp)

**Each recording session:**

1. Open RHX first. In RHX, open **Network → Remote TCP Control**, go to the **Commands** tab and press
   **Connect**.
2. In Ephymeris, open the **Recording** tab and click **Connect**. You must do this again whenever RHX
   disconnects.
3. On the Dashboard, click **Start a Recording** (not Start a Session). Its subtitle tells you whether
   RHX is connected.
4. Configure and place the animals as usual. After the Boxes step comes **Set Up the Recording**:
   - **Readiness** lists anything still missing. Each line says what to fix.
   - **Saving** shows where the recording will be saved and **Using your defaults**. Click
     **Edit for this session** to change them. A yellow line warns if the path contains a space.
   - **Boxes**: for each box choose **Record** or **Behavior only**, its port and channel range, and
     optionally a probe map.

   ![Set Up the Recording: Readiness 5/5 ready (RHX version, RHX is not recording, headstage on port A, the rig has a sync channel, every recorded box has a digital input), Saving with the save location and a space warning, Using your defaults with Edit for this session, and the first box under Boxes set to Record on Port A, channels 0 to 15](images/record-step.webp)

5. Click **Configure RHX and continue**. Nothing is sent to RHX before this.
6. In Mission Control, **Start All** starts the RHX recording first. If RHX cannot start, no box starts.
   A **Recording** panel shows **REC**, the file being written and a **Sync check** table: for each box,
   how many sync pulses were **matched** to events, **missed**, or arrived as **stray** pulses. *no pulses
   arriving* means the sync cable is not reaching RHX.
7. Each recorded box's tile shows its port, digital input and channels, and has **Spike Scope**, **PSTH**,
   **ISI** and (with a probe map) **Probe map** buttons. Each opens its own window, which you can drag to
   another monitor.

   ![Mission Control during a recording: the Recording panel with REC, the file name, the format and 30 kS/s, and a SYNC CHECK table of matched, missed and stray pulses per box; each box tile shows port A, its DIN and channel range, and Spike Scope, PSTH, ISI and Probe map buttons](images/mission-control-recording.webp)

8. **End Session** and **Switch Group** let each box finish its current trial first (up to 45 seconds).
   The panel shows **ENDING**, *Finishing the trials in flight*, and which boxes are still finishing;
   **End now** stops RHX without waiting.

   ![A recording ending: the panel reads ENDING, "Finishing the trials in flight" and "Waiting for box 1, 4, 5 to finish its trial…", with an End now button; boxes 2 and 3 already show Finished](images/mission-control-ending.webp)

The four live windows:

| Spike Scope | PSTH |
|---|---|
| ![Spike Scope window for Box 1, channel A-000: about twenty overlaid spike waveforms and a dashed threshold line at −41 µV](images/scope-spikescope.webp) | ![PSTH window for Box 1: a raster of 18 trials and a histogram, both aligned to ODOR_1_ON, with firing rising after the odor comes on](images/scope-psth.webp) |
| **ISI** | **Probe map** |
| ![ISI window for Box 2: a histogram of the time between spikes, with the mean interval and firing rate underneath](images/scope-isi.webp) | ![Probe Map window for Box 2: a 16-site shank with each site shaded by how fast it is firing](images/scope-probemap.webp) |

- **Spike Scope** overlays recent spikes on one channel. Drag the dashed threshold line to set RHX's
  threshold for that channel.
- **PSTH** lines up each trial on an event (such as an odor coming on) and shows the spikes around it.
- **ISI** shows how long the gaps between spikes are.
- **Probe map** shades each site by its firing. Click a site to open its Spike Scope.

There is one recording per group. The Record step comes back for each new group.

## Checking a box

Debug Mode is for checking or testing a box outside a session. Open it by clicking a box's star on the
Dashboard, or its row in the **Boxes** tile. **Nothing you do in Debug Mode is recorded as data.** Press
Esc, click empty space, or click **← Constellation** to leave.

![Debug Mode for box 3 resting on BOX_Utility: board, port and sketch at the top left, Connection with Open and Reset, the Console, and on the right the Sketch section with Flash…, Full self-test, Prime, and switches for the fluid lines, vacuum, trial light and twelve odor lines](images/debug-mode.webp)

The panel has three parts:

- **Connection.** **Open** connects to the box's console. **Close** disconnects. **Reset** restarts the
  board. **Acknowledge** clears an `ERROR`.
- **Sketch.** **Flash…** puts a program on the box. Pick a sketch and click **Flash**. The log shows the
  program being built and loaded; when it says *Flashed. The console is open*, click **Close**.

  ![The Flash box 3 dialog: sketches grouped under Olfactory behavior, Utility, Discrimination and Shaping, with Refresh and Flash buttons](images/flash-dialog.webp)

  ![The Flash dialog after flashing: the upload log ending in "avrdude done", and the message "Flashed. The console is open — the sketch's output is in it." with a Close button](images/flash-progress.webp)

  For a task sketch, **Send START** starts it with the rig's usual values and shows live metrics, marked
  *Scored as a session would be. Nothing here is recorded.* **End** asks it to stop at the next trial
  boundary.

  ![Debug Mode running 2-Odor Discrimination on box 3: Send START, End and Return to baseline, the console streaming events, and a LIVE section with rolling accuracy, two metrics, a P(right | odor) chart and the outcome mix](images/debug-run.webp)

  When the box is resting on the utility sketch, open the console first (the panel says *open
  passthrough to control*). You then get a switch and a pulse for each valve and odor line, **All off**,
  **Full self-test**, and **Prime**, which runs water down each chosen line in turn: pick how many
  seconds and which lines, then click **Prime** (it reads, for example, **Prime 4 lines**). After flashing your own sketch, **Return to baseline**
  puts the box back on the utility sketch.
- **Console.** Everything the board prints. Type in the box and press Enter to send a command. The
  **Status** tab holds the utility sketch's regular status lines, so the **Console** tab stays readable.
  You can copy or save the log.

**Finding which physical box is which:** on the **Rig** tab, click **Test** on a box's row. It connects to
the board and waits for it to announce itself; the **Handshake** column then reads *speaks Ephymeris —
READY received*. During animal placement the app lights each box for you.

![The Rig tab after pressing Test on box 1: its Handshake column reads "speaks Ephymeris — READY received" while the other boxes say not tested](images/rig-test.webp)

> [!WARNING]
> **`GRGL_Sim` really opens the fluid lines.** It runs a whole session with no animal in the box. Run it
> dry (no water in the reservoirs) unless you mean to dispense.

## Looking at results

### Where files are saved

Each animal gets three files per run, inside the cohort's data folder:

```
<Data directory>/<cohort>/<prefix>/<prefix>_<number>_<YYYY-MM-DD>/
    behavior.tsv/   written live, one line per event
    behavior.json/  built when the run ends
    behavior.mat/   the same, for MATLAB
```

A file is named `<animal>_<prefix>_<number>_<date>_<time>`, for example
`remy1_2O-Bdisc_25_2026-07-22_113123.json`. The `.json` and `.mat` files are the ones to analyse. The
`.tsv` is the safety copy written during the run (see [Crash safety](DATA.md#crash-safety)). A recording
is saved in an `ephys` folder in the session folder, unless the Recording defaults name another place.

### Analytics

1. Open **Analytics** and click a cohort's planet.
2. The **Sessions** rail places sessions by date, so a gap in training shows as a gap. Under it, the
   **Task** strip shows which task each stretch of sessions was running. Below that are the cohort's
   **Accuracy**, **Effort** and **Outcome mix** charts.

   ![Analytics for one cohort: the Data folder, Rescan, Recover, Tidy records and Export cohort PNG buttons at the top, the Sessions rail spaced by date, the Task strip changing from Shaping to 2-Odor Discrimination, and the Accuracy chart with response and rewarded lines](images/analytics-cohort.webp)

3. The **Animals** rail lists each animal with its trend. Hover over one to highlight it in every chart;
   click to keep it highlighted. Beside it, **Strategy space** places each animal per session in one of
   four corners (*discriminating*, *chance*, *side bias*, *reversed*), and **Overall accuracy** shows each
   animal's line over time. Each chart has a **how to read this** note you can open.

   ![The lower half of the cohort view: Effort and Outcome mix bar charts, the Animals rail grouped by Group A and B with a trend and score for each animal, the Strategy space scatter, and Overall accuracy per animal](images/analytics-panels.webp)

4. Click a session on the rail to look at just that one, or **All sessions** to see everything. One
   session shows a **Session summary** table: each animal's start and end time, how many trials it
   sampled and the share rewarded, overall and per condition.

   ![One session selected: the Session summary for 2O-Bdisc_14 with a row per animal giving start, end, trials sampled and percent rewarded for all trials and for each odor, and the Export session PNG button](images/analytics-session.webp)

   Further down, each animal has a card with its conditions and outcomes, and the strategy and rolling
   accuracy charts follow that session trial by trial. Clicking an animal in the **Animals** rail picks it
   out in these charts.

   ![One session with remy3 picked out: per-animal condition cards with outcome bars, the Strategy within this session chart tracing remy3's trials, and Rolling accuracy per trial](images/analytics-session-detail.webp)

5. **All cohorts** goes back to the cohort choice.

**What accuracy means.** For each trial the animal answered, it was either correct or not. Accuracy is
the fraction correct. By default Ephymeris shows **pooled accuracy across conditions**: every condition's
trials counted together. This matters. An animal that always pokes the same side would look perfect on
one condition and terrible on the other; pooled, it correctly sits at chance (0.5). Some charts also
separate *rewarded* accuracy (the animal earned the water) from *response* accuracy (it chose the right
side, even if it let go too early). Full definitions are in [Derived metrics](DATA.md#derived-metrics).

### Exporting a sheet

**Export cohort PNG** (or **Export session PNG** when one session is selected) saves the charts on
screen as one image, with the cohort, task and dates written on it.

### Rescan Recover and Tidy records

These buttons are at the top of Analytics. Use them when the lab manager asks, or as described here.

- **Rescan** looks for session files that Ephymeris has no record of, such as sessions from the other lab
  machine. Use it when a session you expect is missing or marked *not indexed*.
- **Recover** rebuilds the `.json` and `.mat` files from a `.tsv` that a crash left behind. Use it after
  the app or computer crashed during a session. It is refused while any box is running.
- **Tidy records** merges one session that ended up as two records (for example after starting the same
  session number twice in a day) and removes records with no data. It shows what it will do first, in a
  **Tidy session records** window, and it never moves, renames or deletes a data file. Click **Tidy** to
  go ahead, or **Cancel**.

  ![The Tidy session records window: "No data file is moved, renamed or deleted", a preview listing one empty record to remove, and the Cancel and Tidy buttons](images/tidy-records.webp)

## Troubleshooting

| What you see | What to do |
|---|---|
| A box's star is dim, or missing from the Boxes tile | The board is not detected. Check its USB cable and power. If it still does not appear, the box may not be bound: check the **Rig** tab |
| A box will not flash | Read the message on its card. If the box shows `ERROR`, click **Acknowledge**, then try again. If it fails again, tell the lab manager |
| A box is stuck in `ERROR` | Open it from the Dashboard (click its star) and click **Acknowledge**. Reset does not clear an error |
| A box will not start | Click **Reset**, wait a few seconds, then **Start** again |
| **Stop** seems to do nothing | The box stops at the end of the current trial. If no animal is poking, that can take until the trial times out. Wait |
| Screens say *Waiting for the backend* or *The backend isn't connected*, or Debug Mode shows *sidecar down* | The app lost its connection to its own background process. Close Ephymeris and open it again. It does not restart this by itself |
| **backup failing** on Mission Control, or a warning under **Backup directory** in Settings | Data is still saved locally; the backup copy is not being made. Tell the lab manager. The refresh button beside the warning copies anything missing once the backup drive is back |
| A session from earlier today needs another group | **Start a Session**, pick the cohort, then **Continue today**. See [Continue a session from earlier today](#continue-a-session-from-earlier-today) |
| The dock shows a session that **Ended unexpectedly** | The app closed during a session. Use **Continue with another group** (same day only), **View in Analytics**, or **Close out**. Then run **Recover** in Analytics |
| The placement walk says it could not light a box | Go by the number on the box. The walk works without the light |

## Rules that protect the data

- **Do not unplug a box during a session.** The run for that animal stops at once.
- **Do not rename, move or delete anything in the data folder.** Analytics finds sessions by their folder
  and file names, and a renamed file can be lost from its session or read under the wrong date.
- **Never edit a `.tsv` file.** It is the original record of the run, and Recover rebuilds the other
  files from it.
- **`GRGL_Sim` really opens the fluid lines.** Run it dry unless you mean to dispense.
- **Close Ephymeris normally**, with its own close button, and only after ending the session. Closing it
  during a session stops every box's recording.
- **Run only one copy of Ephymeris per computer.** Two copies fight over the boxes' connections and the
  same database.
- **Follow the box order when placing animals**, and check the number on each box. A wrong placement
  cannot be detected later.
- **Do not reuse a session number by accident.** If the configure step warns that the number already has
  data today, stop and check.

## Glossary

| Term | Meaning |
|---|---|
| **Cohort** | A batch of animals trained together, with its own data folder |
| **Group** | The animals that are in the boxes at the same time. A cohort with more animals than boxes has several groups |
| **Box** | One behaviour chamber, numbered 1 to 6. The box number is how Ephymeris identifies it everywhere |
| **Board** | The Arduino computer inside a box, connected by USB. A box is *bound* to its board on the Rig tab |
| **Sketch** | A program for the board |
| **Task** | What the animal does in a session: its trial types, shaping ramp and timings. Saving a task on the Task tab makes a sketch |
| **Task profile** | The description that ships with a sketch, telling Ephymeris its settings, events and live metrics |
| **Prefix** | The task's short name used in folder and file names, such as `2O-Bdisc`. Shared across cohorts |
| **Session** | One sitting at the rig, named by prefix, number and date. It may include several groups |
| **Run** | One animal's part in one session. Each run has its own files |
| **Strobe** | One event the board reports (an odor poke, a water delivery), with a code and a time |
| **Trial** | One attempt: the animal samples an odor, then answers at a well, or does not |
| **Condition** | One kind of trial, such as a particular odor whose correct answer is the left well |
| **START line** | The message that starts a task on a board, carrying all its settings |
| **Utility sketch (baseline)** | The resting program idle boxes are kept on. It lets the app light a box and run Prime |
| **Mission Control** | The screen where you start, watch and stop the boxes during a session |
| **Constellation** | The star figures: the small one in the sidebar shows box health, and the 3D views show the rig or the session's animals |
