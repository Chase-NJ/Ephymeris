import { kindColor, type RigDocument } from "@/lib/hardware/types";

/**
 * Every configured pin, as a listing — the wiring page's reference half.
 *
 * The board map is the editor's picture of the rig; this is the same document
 * as a table an operator can read down while standing at the box with a
 * multimeter: pin, channel, kind, label, and whatever else the channel
 * declares. It EDITS NOTHING — the map selects and moves, the rail edits, and
 * a third editing surface is exactly what that rule forbids. A row click
 * selects, which is the map's own gesture performed from the listing.
 *
 * Rows follow the document as it stands, unsaved edits included, because the
 * table and the map must never disagree about where a channel is — both read
 * the page's one `RigSession` document.
 *
 * SORTED BY PIN NUMBER, not document order. The map's reading order is the
 * document's (a rename must not shuffle the board), but a listing is what you
 * scan to answer "what is on pin 31", and that question is asked in board
 * order. Two channels on one pin (TG228) simply produce two adjacent rows —
 * the diagnostic names the collision; the table doesn't hide it.
 */
export function PinTable({
  doc,
  selected,
  onSelect,
}: {
  doc: RigDocument;
  selected: string | null;
  onSelect: (channel: string | null) => void;
}) {
  const rows = Object.entries(doc.channels)
    .map(([name, entry]) => ({ name, entry, pin: doc.pins[name] }))
    .sort(
      (a, b) =>
        (a.pin?.index ?? Number.MAX_SAFE_INTEGER) -
          (b.pin?.index ?? Number.MAX_SAFE_INTEGER) ||
        a.name.localeCompare(b.name),
    );

  if (rows.length === 0) {
    return (
      <p className="px-4 py-5 text-[12px] text-static">
        No channels yet — add one on the board above.
      </p>
    );
  }

  return (
    <table className="w-full border-collapse text-left">
      <thead>
        <tr className="border-b border-halo font-mono text-[10px] uppercase tracking-wider text-static">
          <th scope="col" className="w-14 px-4 py-2 text-right font-normal">
            Pin
          </th>
          <th scope="col" className="px-3 py-2 font-normal">
            Channel
          </th>
          <th scope="col" className="px-3 py-2 font-normal">
            Kind
          </th>
          <th scope="col" className="px-3 py-2 font-normal">
            Label
          </th>
          <th scope="col" className="px-3 py-2 pr-4 font-normal">
            Detail
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map(({ name, entry, pin }) => {
          const isSelected = selected === name;
          return (
            <tr
              key={name}
              onClick={() => onSelect(isSelected ? null : name)}
              aria-selected={isSelected}
              className={`cursor-pointer border-b border-halo/50 transition-colors last:border-b-0 ${
                isSelected ? "bg-halo/40" : "hover:bg-halo/25"
              }`}
            >
              <td className="px-4 py-2 text-right font-mono text-[12px] text-starlight">
                {pin?.index ?? "—"}
              </td>
              <td className="px-3 py-2 font-mono text-[12px]">
                <span className="flex items-center gap-2">
                  <span
                    aria-hidden
                    className="size-2 shrink-0 rounded-[2px]"
                    style={{ background: kindColor(entry.kind), opacity: 0.7 }}
                  />
                  <span className={isSelected ? "text-pulsar" : "text-starlight"}>
                    {name}
                  </span>
                </span>
              </td>
              <td className="px-3 py-2 font-mono text-[11px] text-static">
                {entry.kind}
              </td>
              <td className="px-3 py-2 text-[12px] text-static">
                {entry.label ?? ""}
              </td>
              <td className="px-3 py-2 pr-4 font-mono text-[11px] text-static">
                {detailOf(entry, pin)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/**
 * The channel's declarations the other columns don't carry, joined into one
 * line. A reward line's plumbing is stated even when absent — "not plumbed" is
 * the one blank that means something (`RigWiringEditor`'s Serves field), so the
 * listing says it rather than showing an empty cell that reads as fine.
 */
function detailOf(
  entry: RigDocument["channels"][string],
  pin: RigDocument["pins"][string] | undefined,
): string {
  const parts: string[] = [];
  if (entry.kind === "response" && entry.port_slot !== undefined)
    parts.push(`slot ${entry.port_slot}`);
  if (entry.kind === "reward")
    parts.push(entry.well ? `serves ${entry.well}` : "not plumbed");
  if (entry.kind === "sync") parts.push("pulses on every event → recording DIN");
  if (pin?.watch_bit !== undefined) parts.push(`watch bit ${pin.watch_bit}`);
  return parts.join(" · ");
}
