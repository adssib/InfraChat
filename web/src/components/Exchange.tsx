import { Ban, ExternalLink, TriangleAlert } from "lucide-react"

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
    <ol className="space-y-0.5 border-t pt-3">
      {m.answer!.citations.map((c) => (
        <li key={c.n}>
          <a
            href={c.url ?? undefined}
            target="_blank"
            rel="noreferrer"
            className="group flex items-baseline gap-2 rounded-md px-1 py-0.5 font-mono text-xs text-muted-foreground transition-colors hover:bg-card hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary/10 px-1 text-[10px] text-primary">{c.n}</span>
            <span className="truncate">{c.source === "kubernetes" ? "Kubernetes" : "Docker"} docs, {c.doc}</span>
            {c.url && <ExternalLink className="size-3 shrink-0 self-center opacity-0 transition-opacity group-hover:opacity-70" aria-hidden />}
          </a>
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
        <p className="max-w-[85%] rounded-2xl rounded-br-md bg-[linear-gradient(135deg,rgb(41_159_255/0.22),rgb(139_92_246/0.18))] px-4 py-2.5 text-[15px] leading-6 ring-1 ring-white/10">{m.question}</p>
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
