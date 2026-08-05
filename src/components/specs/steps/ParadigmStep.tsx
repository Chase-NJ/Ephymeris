import { useMemo } from "react";

import { FieldRow } from "@/components/common/FieldRow";
import type { PlacedDiagnostics } from "@/lib/specs/diagnostics";
import { getAt, setAt } from "@/lib/specs/document";
import type {
  ParadigmQuestion,
  SpecDocument,
  SpecSchema,
} from "@/lib/specs/types";
import { SpecField } from "../SpecField";
import { SelectRow } from "../rows";

/**
 * The paradigm's own questions, rendered from what the sidecar declared.
 *
 * Each `path` is a document path the schema knows, so an answer is a set on a
 * validated location and never new structure — which is what lets a paradigm
 * file stay declarative.
 */
export function ParadigmStep({
  questions,
  doc,
  schema,
  placed,
  onChange,
}: {
  questions: ParadigmQuestion[];
  doc: SpecDocument;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  onChange: (next: SpecDocument) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {questions.map((q) => (
        <ParadigmQuestionRow
          key={q.id}
          question={q}
          doc={doc}
          schema={schema}
          placed={placed}
          onChange={(value) => onChange(setAt(doc, q.path, value))}
        />
      ))}
    </div>
  );
}

/**
 * One paradigm question, rendered by the same overlay the form uses.
 *
 * `source` says where the options come from, and every one of them is a
 * registry the compiler validates against — so a picker here cannot offer a
 * value the compile then rejects. `value` is free entry, and falls through to
 * the overlay's own widget for the path.
 */
function ParadigmQuestionRow({
  question,
  doc,
  schema,
  placed,
  onChange,
}: {
  question: ParadigmQuestion;
  doc: SpecDocument;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  onChange: (value: unknown) => void;
}) {
  const current = getAt(doc, question.path);

  const options = useMemo(() => {
    const channels = (schema.channels ?? {}) as {
      channels?: Record<string, { kind: string; index: number }>;
    };
    switch (question.source) {
      case "channel":
        return Object.entries(channels.channels ?? {})
          .filter(([, c]) => !question.kind || c.kind === question.kind)
          .map(([name, c]) => ({ value: name, label: `${name} (pin ${c.index})` }));
      case "stimulus": {
        const stimuli = (doc["contingency"] as { stimuli?: Array<{ id?: string }> })
          ?.stimuli;
        return (stimuli ?? []).map((s) => ({ value: String(s.id), label: String(s.id) }));
      }
      case "trial_type": {
        const tt = (doc["contingency"] as { trial_types?: Array<{ id?: string }> })
          ?.trial_types;
        return (tt ?? []).map((t) => ({ value: String(t.id), label: String(t.id) }));
      }
      case "strobe":
        return Object.keys(
          ((schema.strobes ?? {}) as { codes?: Record<string, unknown> }).codes ?? {},
        ).map((n) => ({ value: n, label: n }));
      default:
        return null;
    }
  }, [question, doc, schema]);

  if (options !== null) {
    return (
      <SelectRow
        label={question.label}
        help={question.help ?? undefined}
        value={typeof current === "string" ? current : null}
        baseline={null}
        options={options}
        error={
          question.required && (current === null || current === undefined)
            ? "This paradigm needs an answer here."
            : undefined
        }
        onChange={onChange}
      />
    );
  }

  const meta = schema.overlay.fields[overlayKeyFor(question.path)];
  if (meta) {
    return (
      <SpecField
        path={question.path}
        overlayKey={overlayKeyFor(question.path)}
        meta={{
          ...meta,
          label: question.label,
          ...(question.help ? { help: question.help } : {}),
        }}
        value={current}
        baseline={current}
        schema={schema}
        doc={doc}
        placed={placed}
        onChange={onChange}
      />
    );
  }
  return (
    <FieldRow
      label={question.label}
      help={question.help ?? undefined}
      type={typeof current === "number" ? "int" : "string"}
      value={current}
      fallback={current ?? ""}
      baseline={current}
      onChange={onChange}
    />
  );
}

/** `contingency.stimuli[0].emitter` → `contingency.stimuli[].emitter`. */
function overlayKeyFor(path: string): string {
  return path.replace(/\[\d+\]/g, "[]").replace(/\.[a-z0-9_]+\.(?=[a-z_]+$)/i, ".*.");
}
