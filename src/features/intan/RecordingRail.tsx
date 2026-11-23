import { RecordingStatus } from "./RecordingStatus";

/**
 * Mission Control's rail block for a recording (`RECORDING.md#recording-walkthrough`):
 * what RHX is doing. Each recorded box's own surface is its `LiveProbeMap`.
 *
 * Rendered only for a recording session — a recording is an addition to
 * Mission Control, not a mode of it. The block's body is `RecordingStatus`,
 * shared with the Recording tab's Live tile; the rail only supplies the glass.
 */
export function RecordingRail() {
  return (
    <section className="hud rounded-md p-3.5">
      <RecordingStatus />
    </section>
  );
}
