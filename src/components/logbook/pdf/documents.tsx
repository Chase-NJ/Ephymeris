/**
 * The session log on paper (`DATA.md#exporting-a-log`): one session, or a
 * cohort's whole logbook. Pure layout over `lib/logbook/document.ts`'s model —
 * every string is decided there, where it is tested.
 *
 * Loaded only by `export.ts`'s dynamic import, so react-pdf and its font
 * engine cost nothing until someone actually exports.
 */

import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";

import type { DocCohort, DocPerformance, DocSession } from "@/lib/logbook/document";

import { registerFonts } from "./fonts";
import { FAMILY, PAPER } from "./theme";

registerFonts();

const s = StyleSheet.create({
  page: {
    // Ligatures off, everywhere. The embedded faces are latin subsets, and a
    // ligature (JetBrains Mono's `...`, `//`, `==`; Inter's `->`) maps to a
    // glyph the subset dropped — which does not print wrongly, it crashes the
    // font engine and loses the whole export. A note is free text: "...", "--"
    // and "->" are exactly what people type.
    fontFeatureSettings: { liga: false, calt: false, clig: false, dlig: false, rlig: false },
    backgroundColor: PAPER.paper,
    color: PAPER.ink,
    fontFamily: FAMILY.sans,
    fontSize: 9,
    lineHeight: 1.4,
    paddingTop: 40,
    paddingBottom: 52,
    paddingHorizontal: 44,
  },
  kicker: {
    fontFamily: FAMILY.mono,
    fontSize: 7,
    letterSpacing: 1.2,
    color: PAPER.muted,
    textTransform: "uppercase",
  },
  // Heights pinned: the engine measures Space Grotesk's line box short and
  // drew the next line through the title.
  title: { fontFamily: FAMILY.display, fontWeight: 600, fontSize: 20, lineHeight: 1.2, height: 26, marginTop: 2 },
  subtitle: { color: PAPER.muted, fontSize: 9, marginTop: 1 },
  status: {
    fontFamily: FAMILY.mono,
    fontSize: 7,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: PAPER.muted,
    borderWidth: 0.75,
    borderColor: PAPER.rule,
    borderRadius: 3,
    paddingVertical: 2,
    paddingHorizontal: 5,
  },
  readouts: {
    flexDirection: "row",
    marginTop: 12,
    borderTopWidth: 0.75,
    borderBottomWidth: 0.75,
    borderColor: PAPER.rule,
  },
  readout: { flexGrow: 1, flexBasis: 0, paddingVertical: 8, paddingHorizontal: 10 },
  readoutRule: { borderLeftWidth: 0.75, borderColor: PAPER.rule },
  readoutValue: { fontFamily: FAMILY.mono, fontSize: 14, marginTop: 3 },
  elapsed: { fontFamily: FAMILY.mono, fontSize: 18, marginTop: 1, color: PAPER.pulsar },
  fine: { fontFamily: FAMILY.mono, fontSize: 7, color: PAPER.muted, marginTop: 4 },
  section: { marginTop: 16 },
  sectionTitle: {
    fontFamily: FAMILY.display,
    fontWeight: 500,
    fontSize: 10.5,
    lineHeight: 1.3,
    paddingBottom: 3,
    marginBottom: 4,
    borderBottomWidth: 0.75,
    borderColor: PAPER.pulsar,
  },
  empty: { color: PAPER.muted, fontSize: 8.5 },
  noteRow: {
    flexDirection: "row",
    paddingVertical: 5,
    borderBottomWidth: 0.5,
    borderColor: PAPER.rule,
  },
  noteGutter: { width: 58, paddingRight: 8, textAlign: "right" },
  offset: { fontFamily: FAMILY.mono, fontSize: 8.5, color: PAPER.pulsarInk },
  time: { fontFamily: FAMILY.mono, fontSize: 7, color: PAPER.muted },
  noteMeta: { fontSize: 7.5, color: PAPER.muted },
  flag: { color: PAPER.warning, fontFamily: FAMILY.mono, fontSize: 7 },
  body: { fontSize: 9, marginTop: 1 },
  tableHead: {
    flexDirection: "row",
    borderBottomWidth: 0.75,
    borderColor: PAPER.rule,
    paddingBottom: 2,
  },
  th: { fontFamily: FAMILY.mono, fontSize: 6.5, color: PAPER.muted },
  tr: { flexDirection: "row", paddingVertical: 3, borderBottomWidth: 0.5, borderColor: PAPER.rule },
  td: { fontFamily: FAMILY.mono, fontSize: 7.5 },
  // Pinned from the TOP, with a height and its own line height — all three
  // load-bearing. A `fixed` element is laid out again on every page; pinned by
  // `bottom` it grew about fortyfold per page, until by page 7 of a long
  // logbook its top was -1e21 and the PDF writer refused the whole export
  // ("unsupported number"). And the page's `lineHeight` reaches it already
  // resolved against the page's 9pt — taller than the footer — so without its
  // own, not one line fits and the footer silently prints nothing. 792 is
  // LETTER's height in points.
  footer: {
    position: "absolute",
    top: 792 - 24 - 12,
    height: 12,
    lineHeight: 1.2,
    left: 44,
    right: 140,
    fontFamily: FAMILY.mono,
    fontSize: 6.5,
    color: PAPER.muted,
  },
  // Spans the margins and aligns right, with NO height or width: a `render`
  // text given an explicit height is laid out empty and never prints.
  pageNumber: {
    position: "absolute",
    top: 792 - 24 - 12,
    lineHeight: 1.2,
    left: 44,
    right: 44,
    textAlign: "right",
    fontFamily: FAMILY.mono,
    fontSize: 6.5,
    color: PAPER.muted,
  },

  divider: { marginTop: 22, marginBottom: 18, borderTopWidth: 1.5, borderColor: PAPER.pulsar },
});

function Footer({ left }: { left: string }) {
  return (
    <>
      <Text style={s.footer} fixed>
        {left}
      </Text>
      {/* Its own fixed element, react-pdf's documented form, styled per
          `pageNumber`'s note. */}
      <Text
        style={s.pageNumber}
        fixed
        render={({ pageNumber, totalPages }) => `${pageNumber} / ${totalPages}`}
      />
    </>
  );
}

function SessionHeader({ session, cohortName }: { session: DocSession; cohortName: string }) {
  return (
    <View wrap={false}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
        <View>
          <Text style={s.kicker}>Session log · {cohortName}</Text>
          <Text style={s.title}>{session.title}</Text>
          <Text style={s.subtitle}>{session.longDate}</Text>
        </View>
        <Text style={s.status}>{session.status}</Text>
      </View>
      <View style={s.readouts}>
        <Readout label="Date" value={session.date} />
        <Readout label="Start" value={session.start} rule />
        <Readout label="End" value={session.end} rule />
        <View style={[s.readout, s.readoutRule, { flexGrow: 1.3 }]}>
          <Text style={s.kicker}>Elapsed</Text>
          <Text style={s.elapsed}>{session.elapsed}</Text>
        </View>
      </View>
      {session.setup && <Text style={s.fine}>{session.setup}</Text>}
    </View>
  );
}

function Readout({ label, value, rule = false }: { label: string; value: string; rule?: boolean }) {
  return (
    <View style={rule ? [s.readout, s.readoutRule] : s.readout}>
      <Text style={s.kicker}>{label}</Text>
      <Text style={s.readoutValue}>{value}</Text>
    </View>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={s.section}>
      {/* A title is never stranded at the foot of a page without its first row. */}
      <Text style={s.sectionTitle} minPresenceAhead={36}>
        {title}
      </Text>
      {children}
    </View>
  );
}

/**
 * The screen's table on paper (`SessionTable`'s layout): one column per
 * condition, each cell the rewarded share over the sampled count, and the
 * run's clock folded under the animal's name — so ten conditions fit a
 * Letter page's 524pt without shrinking the type.
 */
function Performance({ performance }: { performance: DocPerformance }) {
  const groups = ["all", ...performance.conditions];
  const animalWidth = 96;
  const column = { flexGrow: 1, flexBasis: 0, textAlign: "right" as const, paddingLeft: 3 };
  return (
    <View>
      <View style={[s.tableHead, { alignItems: "flex-end" }]}>
        <Text style={[s.th, { width: animalWidth }]}>animal</Text>
        {groups.map((group, index) => (
          <Text key={group + index} style={[s.th, column, index === 0 ? { color: PAPER.ink } : {}]}>
            {group}
          </Text>
        ))}
      </View>
      {performance.rows.map((row) => (
        <View key={row.animal + row.start} style={[s.tr, { alignItems: "flex-start" }]} wrap={false}>
          <View style={{ width: animalWidth }}>
            <Text style={{ fontSize: 8 }}>{row.animal}</Text>
            <Text style={[s.time, { marginTop: 1 }]}>
              {row.start}–{row.end}
            </Text>
          </View>
          {row.note ? (
            <Text style={[s.td, column, { flexGrow: groups.length, color: PAPER.muted }]}>
              {row.note}
            </Text>
          ) : (
            row.cells.map((cell, index) => (
              <View key={index} style={column}>
                <Text style={[s.td, cell.thin ? { color: PAPER.muted } : {}]}>
                  {cell.rate}
                  {cell.thin ? "*" : ""}
                </Text>
                <Text style={[s.time, { marginTop: 1 }]}>{cell.sampled}</Text>
              </View>
            ))
          )}
        </View>
      ))}
      <Text style={s.fine}>
        Each cell: the share of sampled trials that ended with the reward delivered, over the number
        of trials sampled to completion. * fewer trials than the cohort's minimum — read loosely.
      </Text>
    </View>
  );
}

function SessionBody({ session }: { session: DocSession }) {
  return (
    <>
      {(session.operator || session.summary) && (
        <Section title="Operator and summary">
          {session.operator && (
            <Text>
              <Text style={s.noteMeta}>Operator </Text>
              {session.operator}
            </Text>
          )}
          {session.summary && <Text style={{ marginTop: 3 }}>{session.summary}</Text>}
        </Section>
      )}

      <Section title={`Notes (${session.notes.length})`}>
        {session.notes.length === 0 ? (
          <Text style={s.empty}>No notes.</Text>
        ) : (
          session.notes.map((note, index) => (
            <View key={index} style={s.noteRow} wrap={false}>
              <View style={s.noteGutter}>
                <Text style={s.offset}>{note.offset}</Text>
                <Text style={s.time}>{note.time}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={s.noteMeta}>
                  {note.tag} · {note.scope}
                  {note.flag ? "  " : ""}
                  {note.flag && <Text style={s.flag}>{note.flag}</Text>}
                </Text>
                <Text style={s.body}>{note.body}</Text>
              </View>
            </View>
          ))
        )}
      </Section>

      <Section title="Performance">
        {session.performance ? (
          <Performance performance={session.performance} />
        ) : (
          <Text style={s.empty}>No runs were scored for this session.</Text>
        )}
      </Section>

      <Section title="What changed since each animal's previous run">
        {session.changes.every((c) => c.parts.length === 0) ? (
          <Text style={s.empty}>
            {session.recovered
              ? "Not compared: runs recovered from files carry no recorded parameters or box."
              : session.changes.length === 0
                ? "No runs recorded."
                : "Nothing changed."}
          </Text>
        ) : (
          session.changes
            .filter((c) => c.parts.length > 0)
            .map((change) => (
              <View key={change.animal + change.box} style={s.tr} wrap={false}>
                <Text style={{ width: 110, fontSize: 8.5 }}>
                  {change.animal} <Text style={s.time}>box {change.box}</Text>
                </Text>
                <Text style={{ flex: 1, fontSize: 8.5 }}>{change.parts.join(" · ")}</Text>
              </View>
            ))
        )}
      </Section>
    </>
  );
}

export function SessionLogDocument({
  session,
  cohortName,
  exportedAt,
}: {
  session: DocSession;
  cohortName: string;
  exportedAt: string;
}) {
  return (
    <Document title={`${session.title} — session log`} author="Ephymeris" creator="Ephymeris">
      <Page size="LETTER" style={s.page}>
        <SessionHeader session={session} cohortName={cohortName} />
        <SessionBody session={session} />
        <Footer left={`Ephymeris · ${cohortName} · ${session.title} · exported ${exportedAt}`} />
      </Page>
    </Document>
  );
}

export function CohortLogbookDocument({ cohort }: { cohort: DocCohort }) {
  return (
    <Document title={`${cohort.cohortName} — logbook`} author="Ephymeris" creator="Ephymeris">
      <Page size="LETTER" style={s.page}>
        <View style={{ marginTop: 120 }}>
          <Text style={s.kicker}>Logbook</Text>
          <Text style={[s.title, { fontSize: 30, height: 38 }]}>{cohort.cohortName}</Text>
          <Text style={[s.subtitle, { fontFamily: FAMILY.mono, marginTop: 6 }]}>{cohort.span}</Text>
          <View style={[s.readouts, { marginTop: 24 }]}>
            <Readout label="Sessions" value={String(cohort.sessions.length)} />
            <Readout label="Notes" value={String(cohort.noteCount)} rule />
            <Readout label="Open flags" value={String(cohort.openFlags.length)} rule />
          </View>
          <Text style={[s.fine, { marginTop: 10 }]}>
            Exported {cohort.exportedAt}. Times are local to the rig. Elapsed time runs from each
            session's first group start to its last group end.
          </Text>
        </View>

        {cohort.openFlags.length > 0 && (
          <View style={{ marginTop: 36 }}>
            <Text style={s.sectionTitle}>Still open</Text>
            {cohort.openFlags.map((flag, index) => (
              <View key={index} style={s.noteRow} wrap={false}>
                <View style={{ flex: 1 }}>
                  <Text style={s.noteMeta}>
                    {flag.tag} · {flag.scope} · from {flag.from}
                  </Text>
                  <Text style={s.body}>{flag.body}</Text>
                </View>
              </View>
            ))}
          </View>
        )}
        <Footer left={`Ephymeris · ${cohort.cohortName} · logbook · exported ${cohort.exportedAt}`} />
      </Page>

      <Page size="LETTER" style={s.page}>
        {cohort.sessions.map((session, index) => (
          <View key={session.id}>
            {index > 0 && <View style={s.divider} minPresenceAhead={160} />}
            <SessionHeader session={session} cohortName={cohort.cohortName} />
            <SessionBody session={session} />
          </View>
        ))}
        <Footer left={`Ephymeris · ${cohort.cohortName} · logbook · exported ${cohort.exportedAt}`} />
      </Page>
    </Document>
  );
}
