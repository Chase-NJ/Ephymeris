import { open } from "@tauri-apps/plugin-dialog";
import { FolderOpen } from "lucide-react";
import { useState } from "react";

import { Button, Toggle } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";

/**
 * Data folder display and relocation — `cohorts.md` §8.
 *
 * The real path is shown plainly at all times so there's never ambiguity about
 * where data actually lives — which matters precisely because renaming the
 * cohort deliberately does *not* move it. Relocating is its own explicit action
 * that offers to move existing contents.
 */
export function DataFolderField({
  path,
  onRelocate,
}: {
  path: string;
  onRelocate: (destination: string, moveExisting: boolean) => void;
}) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [destination, setDestination] = useState<string | null>(null);
  const [moveExisting, setMoveExisting] = useState(true);

  async function choose() {
    try {
      const picked = await open({
        directory: true,
        multiple: false,
        title: "Choose a new data folder",
      });
      if (typeof picked === "string") setDestination(picked);
    } catch (err) {
      console.error("directory picker failed", err);
    }
  }

  return (
    <>
      <div className="flex items-start justify-between gap-8 px-4 py-3.5">
        <div className="min-w-0 pt-0.5">
          <div className="text-[13px] font-medium text-starlight">Data folder</div>
          <p
            data-selectable
            className="mt-1 font-mono text-[12px] break-all text-static"
            title={path}
          >
            {path}
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-static/70">
            Renaming this cohort won't move its folder.
          </p>
        </div>
        <Button
          onClick={() => {
            setDestination(null);
            setMoveExisting(true);
            setDialogOpen(true);
          }}
        >
          <FolderOpen size={13} strokeWidth={1.75} />
          Change data folder…
        </Button>
      </div>

      <Modal
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title="Change data folder"
      >
        <div className="flex flex-col gap-4">
          <div>
            <div className="text-[11px] text-static">Current</div>
            <div data-selectable className="font-mono text-[12px] break-all text-static">
              {path}
            </div>
          </div>

          <div>
            <div className="text-[11px] text-static">New location</div>
            <div className="mt-1 flex items-center gap-2">
              <span
                data-selectable
                className={`min-w-0 flex-1 truncate rounded-sm border border-halo bg-nebula px-2.5 py-1.5 font-mono text-[12px] ${
                  destination ? "text-starlight" : "text-static/70"
                }`}
              >
                {destination ?? "Not chosen"}
              </span>
              <Button onClick={() => void choose()}>
                <FolderOpen size={13} strokeWidth={1.75} />
                Choose…
              </Button>
            </div>
          </div>

          <label className="flex items-center gap-2.5">
            <Toggle
              label="Move existing contents"
              checked={moveExisting}
              onChange={setMoveExisting}
            />
            <span className="text-[12px] text-static">
              Move existing contents to the new location
            </span>
          </label>

          {/* Two different intents, with opposite requirements for the
              destination. Saying only the "must be empty" half made attaching a
              cohort to an archive it didn't write look impossible. */}
          <p className="rounded-sm border border-halo bg-void/40 px-3 py-2 text-[12px] leading-relaxed text-static">
            {moveExisting ? (
              <>
                This cohort&rsquo;s data will be <strong>moved</strong> to the new
                folder, which must be empty — Ephymeris refuses rather than
                merging into or overwriting existing data.
              </>
            ) : (
              <>
                Nothing is moved or written. The cohort simply points at the new
                folder from now on — use this to attach it to data that is{" "}
                <strong>already there</strong>, then run Rescan in Analytics to
                index it.
              </>
            )}
          </p>

          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!destination}
              onClick={() => {
                if (!destination) return;
                setDialogOpen(false);
                onRelocate(destination, moveExisting);
              }}
            >
              Change folder
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
