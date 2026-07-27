import { Button } from "@/components/common/controls";
import { HandshakeIndicator } from "./HandshakeIndicator";
import type { useHandshakeTest } from "@/lib/hardware/useHandshakeTest";
import type { BoxBinding } from "@/lib/settings/schema";

/** One handshake-test card per bound box — shared by the wizard and Config. */
export function HandshakeList({
  bound,
  handshake,
  connected,
}: {
  bound: BoxBinding[];
  handshake: ReturnType<typeof useHandshakeTest>;
  connected: boolean;
}) {
  return (
    <div className="flex flex-col gap-2">
      {bound.length === 0 && (
        <p className="text-[12px] leading-relaxed text-static">
          No boxes are bound to a board yet — nothing to test.
        </p>
      )}
      {bound.map((binding) => (
        <div
          key={binding.box}
          className="flex items-center justify-between gap-4 rounded-sm border border-halo px-3 py-2.5"
        >
          <div className="flex min-w-0 items-center gap-3">
            <span className="font-mono text-[12px] text-static">{binding.box}</span>
            <span className="truncate text-[13px] text-starlight">{binding.label}</span>
          </div>
          <div className="flex items-center gap-3">
            <HandshakeIndicator state={handshake.stateFor(binding.box)} />
            <Button
              onClick={() => void handshake.run(binding.box)}
              disabled={!connected || handshake.stateFor(binding.box).phase === "running"}
            >
              Test
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}
