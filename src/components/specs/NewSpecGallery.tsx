import { useMemo, useState } from "react";

import { Button } from "@/components/common/controls";
import { FieldRow } from "@/components/common/FieldRow";
import { Modal } from "@/components/common/Modal";
import { errorMessage } from "@/lib/cohorts/commands";
import { getSpec } from "@/lib/specs/commands";
import { createSpecFrom, idError, suggestId } from "@/lib/specs/create";
import { groupByParadigm, RECIPES, variantNote } from "@/lib/specs/paradigms";
import type { SpecEntry } from "@/lib/specs/types";
import { useSidecar } from "@/lib/ws/context";

/**
 * New task, from a paradigm.
 *
 * A "paradigm" here is a SHAPE, and the bundled specs are its variants — see
 * `lib/specs/paradigms.ts` for why that distinction is the honest one (three
 * graphs, five files). Starting from one is starting from a task that is known
 * to compile, known to lint clean, and carries an author's comments explaining
 * every value, which a generated blank skeleton cannot do.
 *
 * MECHANICALLY THIS IS RENAME-AND-SAVE, and deliberately no new wire command:
 * `createSpecFrom` is the one definition of that path, shared with Duplicate
 * and the designer wizard. `specs.save` targets the document's own `spec_id`,
 * and a save under an id with no user file creates one; the source is
 * untouched because nothing wrote to it.
 *
 * A recipe — a paradigm this rig can reach but no bundled file holds — is
 * offered here as a route into the wizard rather than as a one-click create,
 * because its steps ask questions (which emitter, how long a gap) that a
 * gallery card has nowhere to put.
 */
export function NewSpecGallery({
  open,
  onClose,
  specs,
  onCreated,
  onDesign,
}: {
  open: boolean;
  onClose: () => void;
  specs: SpecEntry[];
  onCreated: (specId: string) => void;
  /** Open the wizard, optionally on a named recipe. */
  onDesign: (recipeId?: string) => void;
}) {
  const { client } = useSidecar();
  const [source, setSource] = useState<string | null>(null);
  const [id, setId] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Everything the catalogue recognises, grouped by the SHAPE it compiles to.
  // A rig's own edited copy of a bundled paradigm is still that paradigm — and
  // it is the version this rig actually runs — so `shipped_edited` belongs
  // here alongside `shipped`. Only specs with no recognised shape fall to the
  // "Custom" group at the end.
  const groups = useMemo(() => groupByParadigm(specs), [specs]);

  const taken = useMemo(() => new Set(specs.map((s) => s.specId)), [specs]);
  const error_ = idError(id, taken);

  function reset() {
    setSource(null);
    setId("");
    setLabel("");
    setError(null);
  }

  async function create() {
    if (!source || !id || error_) return;
    setBusy(true);
    setError(null);
    try {
      const reply = await getSpec(client, source);
      if (!reply.raw) {
        setError("That spec's YAML won't parse, so it can't be used as a starting point.");
        return;
      }
      await createSpecFrom(client, reply.raw, { id, label });
      onCreated(id);
      reset();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title="New task"
      size="lg"
    >
      <p className="text-[12px] leading-relaxed text-static">
        Start from a paradigm. Each is a working task the compiler and the linter
        already agree on — you get its shape, its timings and its author&rsquo;s
        notes, under a new id. The original is not touched.
      </p>

      <div className="mt-3 flex flex-col gap-3">
        {groups.map(({ paradigm, entries }) => (
          <section key={paradigm?.id ?? "custom"}>
            <div className="flex items-baseline gap-2">
              <h3 className="font-display text-[13px] text-starlight">
                {paradigm?.name ?? "Your own tasks"}
              </h3>
              {entries.length > 1 && (
                <span className="font-mono text-[9px] text-static/60">
                  same machine, different timings
                </span>
              )}
            </div>
            {paradigm && (
              <p className="mt-0.5 text-[11px] leading-relaxed text-static">
                {paradigm.affords}
              </p>
            )}

            <div className="mt-1.5 grid grid-cols-1 gap-1.5 sm:grid-cols-3">
              {entries.map((spec) => {
                const active = source === spec.specId;
                const note = variantNote(spec.specId);
                return (
                  <button
                    key={spec.specId}
                    type="button"
                    onClick={() => {
                      setSource(spec.specId);
                      if (id === "") setId(suggestId(spec.specId, taken));
                      if (label === "" && spec.label) setLabel(`${spec.label} (copy)`);
                    }}
                    className={`min-w-0 rounded-sm border px-2.5 py-2 text-left transition-colors ${
                      active
                        ? "border-pulsar bg-halo/40"
                        : "border-halo hover:border-static/60"
                    }`}
                  >
                    <div className="truncate text-[12px] text-starlight">
                      {spec.label ?? spec.specId}
                    </div>
                    <div className="truncate font-mono text-[9.5px] text-static/70">
                      {spec.specId}
                      {spec.template && ` · ${spec.template} v${spec.templateVersion}`}
                    </div>
                    <p className="mt-1 line-clamp-3 text-[10.5px] leading-relaxed text-static">
                      {note ?? spec.description}
                    </p>
                  </button>
                );
              })}
            </div>
          </section>
        ))}

        {/* Paradigms this rig can reach that no bundled file holds. Each is a
        base plus a fixed sequence of the editor's own structural blocks, so it
        arrives compiled rather than generated. */}
        <section className="border-t border-halo pt-2.5">
          <h3 className="font-display text-[13px] text-starlight">Design one</h3>
          <p className="mt-0.5 text-[11px] leading-relaxed text-static">
            Walk through the questions and watch the machine take shape. Start from
            a paradigm and change what you need, or take one of these as the
            opening move.
          </p>
          <div className="mt-1.5 grid grid-cols-1 gap-1.5 sm:grid-cols-3">
            <button
              type="button"
              onClick={() => {
                reset();
                onClose();
                onDesign();
              }}
              className="min-w-0 rounded-sm border border-pulsar/60 px-2.5 py-2 text-left transition-colors hover:border-pulsar"
            >
              <div className="text-[12px] text-starlight">Design from scratch</div>
              <p className="mt-1 text-[10.5px] leading-relaxed text-static">
                Every question, from what the animal samples to how the session ends.
              </p>
            </button>
            {RECIPES.map((recipe) => (
              <button
                key={recipe.id}
                type="button"
                onClick={() => {
                  reset();
                  onClose();
                  onDesign(recipe.id);
                }}
                className="min-w-0 rounded-sm border border-halo px-2.5 py-2 text-left transition-colors hover:border-static/60"
              >
                <div className="truncate text-[12px] text-starlight">{recipe.name}</div>
                <div className="truncate font-mono text-[9.5px] text-static/70">
                  from {recipe.base}
                </div>
                <p className="mt-1 line-clamp-3 text-[10.5px] leading-relaxed text-static">
                  {recipe.affords}
                </p>
              </button>
            ))}
          </div>
        </section>
      </div>

      {source && (
        <div className="mt-3 flex flex-col gap-1.5 border-t border-halo pt-3">
          <FieldRow
            label="Id"
            help="Names the file, the compiled table, and what a board reports after an upload."
            type="string"
            value={id}
            fallback=""
            baseline=""
            error={error_ ?? undefined}
            onChange={(next) => setId(String(next ?? ""))}
          />
          <FieldRow
            label="Label"
            type="string"
            value={label}
            fallback=""
            baseline=""
            mono={false}
            onChange={(next) => setLabel(String(next ?? ""))}
          />
        </div>
      )}

      {error && (
        <p className="mt-2 text-[11px]" style={{ color: "var(--color-status-error)" }}>
          {error}
        </p>
      )}

      <div className="mt-4 flex justify-end gap-2">
        <Button
          variant="ghost"
          onClick={() => {
            reset();
            onClose();
          }}
        >
          Cancel
        </Button>
        <Button
          variant="primary"
          disabled={!source || id === "" || error_ !== null || busy}
          onClick={() => void create()}
        >
          {busy ? "Creating…" : "Create"}
        </Button>
      </div>
    </Modal>
  );
}
