import { FieldRow } from "@/components/common/FieldRow";

/**
 * What the task is called.
 *
 * IDENTITY IS HELD OUTSIDE THE DOCUMENT until Create, which folds it in through
 * `createSpecFrom`'s `rename()`. The id is the filename, the compiled table's
 * identity and half of what a board reports back, so it is the one step whose
 * answer gates Next — walking the rest of the wizard with a duplicate id and
 * finding out at Create is a whole walk of wasted work.
 */
export function IdentityStep({
  id,
  label,
  description,
  idError,
  onId,
  onLabel,
  onDescription,
}: {
  id: string;
  label: string;
  description: string;
  /** The id's problem, if it has one — computed by the caller against the library. */
  idError: string | undefined;
  onId: (next: string) => void;
  onLabel: (next: string) => void;
  onDescription: (next: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <FieldRow
        label="Id"
        help="Names the file, the compiled table, and what a board reports after an upload."
        type="string"
        value={id}
        fallback=""
        baseline=""
        error={idError}
        onChange={(next) => onId(String(next ?? ""))}
      />
      <FieldRow
        label="Label"
        help="What the library shows. Free text — it names nothing on disk."
        type="string"
        value={label}
        fallback=""
        baseline=""
        mono={false}
        onChange={(next) => onLabel(String(next ?? ""))}
      />
      <FieldRow
        label="Description"
        help="What this task measures, for whoever reads the library in six months."
        type="string"
        value={description}
        fallback=""
        baseline=""
        mono={false}
        onChange={(next) => onDescription(String(next ?? ""))}
      />
    </div>
  );
}
