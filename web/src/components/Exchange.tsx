import { Ban, TriangleAlert } from "lucide-react"

import { AnswerText } from "@/components/AnswerText"
import { Trace } from "@/components/Trace"
import type { Message } from "@/lib/events"

function Refusal({ m }: { m: Message }) {
  const r = m.refusal!
  const why =
    r.gate === "floor"
      ? `Nothing in the indexed docs was close enough to this question (best match ${m.floor.score?.toFixed(3)}, floor ${m.floor.threshold}). The model was never asked.`
      : m.cite.saidNotInDocs
        ? "The closest passages are related, but the model found no answer in them, so InfraChat won't guess."
        : "The model answered without citing anything it was shown, so the answer was withheld."
  return (
    <div className="flex gap-3 rounded-xl border border-refuse/30 bg-refuse/5 px-4 py-3">
      <Ban className="mt-0.5 size-4 shrink-0 text-refuse" aria-hidden />
      <div className="space-y-1 text-sm">
        <p className="font-medium text-foreground">Not in the Kubernetes or Docker docs</p>
        <p className="text-muted-foreground">{why}</p>
      </div>
    </div>
  )
}

function Sources({ m }: { m: Message }) {
  return (
    <ol className="space-y-1 border-t pt-3">
      {m.answer!.citations.map((c) => (
        <li key={c.n} id={`source-${c.n}`} className="flex items-baseline gap-2 font-mono text-xs text-muted-foreground">
          <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary/10 px-1 text-[10px] text-primary">{c.n}</span>
          <span className="truncate text-foreground/80">{c.source === "kubernetes" ? "Kubernetes" : "Docker"} docs, {c.doc}</span>
          <span className="shrink-0">lines {c.lines.replace(/^L/, "")}</span>
        </li>
      ))}
    </ol>
  )
}

export function Exchange({ m }: { m: Message }) {
  // Only an actual drafted answer gets the struck-out retraction; a model that said
  // NOT_IN_DOCS wrote no answer, so there is nothing to withdraw.
  const retracting = m.refusal?.gate === "citation" && !m.cite.saidNotInDocs && m.draft
  return (
    <article className="space-y-5" aria-busy={m.totalMs === null}>
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl bg-card px-4 py-2.5 text-[15px] leading-6">{m.question}</p>
      </div>

      <div className="space-y-4">
        <Trace m={m} />

        {m.error && (
          <div className="flex gap-3 rounded-xl border border-error/30 bg-error/5 px-4 py-3 text-sm">
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-error" aria-hidden />
            <p>{m.error}</p>
          </div>
        )}

        {m.answer ? (
          <div className="space-y-4">
            <AnswerText text={m.answer.text} citations={m.answer.citations} />
            <Sources m={m} />
          </div>
        ) : m.refusal ? (
          <div className="space-y-3">
            {retracting && (
              <p className="retracted font-mono text-xs text-muted-foreground line-through decoration-refuse/70" aria-label="Withdrawn draft">
                {m.draft}
              </p>
            )}
            <Refusal m={m} />
          </div>
        ) : m.draft && !m.draft.trimStart().startsWith("NOT_IN_DOCS") ? (
          <div>
            <AnswerText text={m.draft} draft />
            <p className="mt-2 text-xs text-muted-foreground">Unverified until the citation check passes</p>
          </div>
        ) : null}
      </div>
    </article>
  )
}
