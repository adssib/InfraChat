// The pipeline, as it runs: search, the similarity check (gate 1), the model reading,
// the citation check (gate 2). A rail of steps while it works, one summary line after.

import { Ban, Check, ChevronDown, LoaderCircle, Minus } from "lucide-react"
import { useEffect, useState, type ReactNode } from "react"

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { isFinished, type Message, type StepState } from "@/lib/events"
import { cn } from "@/lib/utils"

const fmtMs = (ms: number) => (ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`)

function Node({ state }: { state: StepState }) {
  const base = "relative z-10 flex size-5 items-center justify-center rounded-full border bg-background"
  if (state === "running") return <span className={base}><LoaderCircle className="size-3 animate-spin text-muted-foreground" /></span>
  if (state === "passed") return <span className={cn(base, "border-ok/50")}><Check className="size-3 text-ok" strokeWidth={3} /></span>
  if (state === "refused") return <span className={cn(base, "border-refuse/60")}><Ban className="size-3 text-refuse" strokeWidth={2.5} /></span>
  if (state === "skipped") return <span className={cn(base, "border-dashed")}><Minus className="size-3 text-muted-foreground/60" /></span>
  return <span className="relative z-10 flex size-5 items-center justify-center"><span className="size-1.5 rounded-full bg-muted-foreground/40" /></span>
}

function Step({
  state, title, meta, children, last,
}: { state: StepState; title: ReactNode; meta?: ReactNode; children?: ReactNode; last?: boolean }) {
  return (
    <li className="relative grid grid-cols-[1.25rem_1fr] gap-x-3 pb-4 last:pb-0">
      {!last && <span className="absolute top-5 bottom-0 left-[0.625rem] w-px -translate-x-1/2 bg-border" aria-hidden />}
      <Node state={state} />
      <div className="min-w-0">
        <div className="flex items-baseline justify-between gap-3 text-sm">
          <span className={cn(state === "skipped" || state === "waiting" ? "text-muted-foreground" : "text-foreground")}>{title}</span>
          {meta && <span className="shrink-0 font-mono text-xs text-muted-foreground tabular-nums">{meta}</span>}
        </div>
        {children && <div className="mt-2">{children}</div>}
      </div>
    </li>
  )
}

// Gate 1 drawn to scale: where the best match landed against the floor. The scale starts
// at 0.4 because no question in the eval set scored below 0.44.
function FloorMeter({ score, floor, passed }: { score: number; floor: number; passed: boolean }) {
  const lo = 0.4, hi = 0.9
  const pos = (v: number) => `${Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100))}%`
  return (
    <div className="pt-4 pb-1" role="img" aria-label={`Best match ${score.toFixed(3)}, floor ${floor}`}>
      <div className="relative h-1.5 rounded-full bg-muted">
        <div className={cn("meter-fill absolute inset-y-0 left-0 rounded-full", passed ? "bg-ok" : "bg-refuse")} style={{ width: pos(score) }} />
        <div className="absolute -top-2 -bottom-2 w-0.5 -translate-x-1/2 rounded bg-primary" style={{ left: pos(floor) }} />
        <span className="absolute -top-5 -translate-x-1/2 font-mono text-[10px] text-primary" style={{ left: pos(floor) }}>
          floor {floor}
        </span>
      </div>
    </div>
  )
}

function Excerpts({ m }: { m: Message }) {
  return (
    <ol className="space-y-1.5">
      {m.excerpts.map((h) => (
        <li key={h.chunk_id} className="grid grid-cols-[2.75rem_1fr_auto] items-baseline gap-2 font-mono text-xs">
          <span className="text-muted-foreground tabular-nums">{h.score.toFixed(3)}</span>
          <span className="truncate" title={`${h.doc} lines ${h.lines}`}>
            <span className="text-muted-foreground">{h.source === "kubernetes" ? "k8s" : "docker"}/</span>
            {h.doc.replace(/\.md$/, "")}
          </span>
          {h.keyword_rank && (!h.dense_rank || h.dense_rank > h.rank) ? (
            <span className="text-primary" title="Ranked higher because of an exact keyword match">keyword</span>
          ) : <span />}
        </li>
      ))}
    </ol>
  )
}

function summary(m: Message): string {
  if (m.error) return "Stopped by an error"
  const searched = `Searched ${m.candidates} passages`
  if (m.floor.state === "refused") return `${searched}. None were close enough to the question.`
  if (m.cite.state === "refused")
    return m.cite.saidNotInDocs
      ? `${searched}. The model found no answer in the top ${m.excerpts.length}.`
      : `${searched}. The answer cited nothing it was shown.`
  return `${searched}, answered from ${m.cite.cited.length} of them, both checks passed`
}

export function Trace({ m }: { m: Message }) {
  const finished = isFinished(m)
  const [open, setOpen] = useState(true)
  // Collapse once the run settles: the trace is the show while it works and a receipt after.
  useEffect(() => { if (finished) setOpen(false) }, [finished])

  const floorMeta = m.floor.score === null ? null : m.floor.score.toFixed(3)
  const citeMeta =
    m.cite.state === "passed" ? `${m.cite.cited.length} cited`
    : m.cite.state === "refused" ? (m.cite.saidNotInDocs ? "not in excerpts" : "nothing cited")
    : null

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-xl border bg-card/50">
      <CollapsibleTrigger className="flex w-full items-center justify-between gap-3 rounded-xl px-4 py-3 text-left text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
        <span className="truncate">{finished ? summary(m) : "Working through the docs"}</span>
        <span className="flex shrink-0 items-center gap-2 font-mono text-xs tabular-nums">
          {m.totalMs !== null && fmtMs(m.totalMs)}
          <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ol className="px-4 pt-1 pb-4">
          <Step
            state={m.excerpts.length ? "passed" : "running"}
            title={m.excerpts.length
              ? (m.hybrid ? "Searched by meaning and by keyword" : "Searched by meaning")
              : (m.hybrid ? "Searching by meaning and by keyword" : "Searching by meaning")}
            meta={m.searchMs ? fmtMs(m.searchMs) : null}
          >
            {m.excerpts.length > 0 && <Excerpts m={m} />}
          </Step>
          <Step state={m.excerpts.length ? m.floor.state : "waiting"} title="Similarity check" meta={floorMeta}>
            {m.floor.score !== null && (
              <FloorMeter score={m.floor.score} floor={m.floor.threshold} passed={m.floor.state === "passed"} />
            )}
          </Step>
          <Step
            state={m.model.state}
            title={m.model.state === "skipped" ? "Model not asked" : `Model read the top ${m.excerpts.length || 5}`}
            meta={m.model.promptTokens ? `${m.model.promptTokens} tok` : null}
          >
            {m.model.reasoning && (
              <p className="max-h-40 overflow-y-auto rounded-lg bg-muted/60 px-3 py-2 font-mono text-xs leading-5 text-muted-foreground">
                {m.model.reasoning}
              </p>
            )}
          </Step>
          <Step state={m.cite.state} title={m.cite.state === "skipped" ? "Citation check not needed" : "Citation check"} meta={citeMeta} last />
        </ol>
      </CollapsibleContent>
    </Collapsible>
  )
}
