import type { Strobe } from "./playback";

/** How many strobes the feed shows above the playhead. */
const SHOWN = 14;

/** `61234` → `1:01.2`: the session clock to a tenth of a second. */
function stamp(ms: number): string {
  const tenths = Math.floor(ms / 100);
  const s = Math.floor(tenths / 10);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}.${tenths % 10}`;
}

/**
 * The strobes as the board sent them, newest first, up to the playhead: this
 * machine's code, its name, and its time on the session clock. A row is a
 * place to go.
 */
export function StrobeFeed({
  strobes,
  count,
  names,
  onSeek,
}: {
  strobes: readonly Strobe[];
  count: number;
  names: Record<string, string>;
  onSeek: (ms: number) => void;
}) {
  if (count === 0) {
    return <p className="text-[11px] leading-relaxed text-static">Strobes appear here as the board sends them.</p>;
  }
  const rows = [];
  for (let i = count - 1; i >= Math.max(0, count - SHOWN); i--) rows.push(i);

  return (
    <ol className="m-0 flex list-none flex-col gap-1 p-0">
      {rows.map((i, order) => {
        const { code, at } = strobes[i]!;
        return (
          <li key={i}>
            <button
              type="button"
              onClick={() => onSeek(at)}
              title="Go to this strobe"
              className={`grid w-full grid-cols-[38px_minmax(0,1fr)_auto] items-center gap-2 rounded-sm border px-1.5 py-1 text-left transition-colors hover:border-static/70 ${
                order === 0 ? "border-halo bg-halo/30" : "border-halo/50"
              }`}
            >
              <span className="rounded-[3px] border border-halo px-1 text-center font-mono text-[10px] tabular-nums text-static">
                {code}
              </span>
              <span className={`truncate font-mono text-[11px] ${order === 0 ? "text-starlight" : "text-static"}`}>
                {names[String(code)] ?? `Strobe ${code}`}
              </span>
              <span className="font-mono text-[10px] tabular-nums text-static">{stamp(at)}</span>
            </button>
          </li>
        );
      })}
      <li className="pt-0.5 font-mono text-[10px] tabular-nums text-static/70">
        {count} of {strobes.length} strobes
      </li>
    </ol>
  );
}
