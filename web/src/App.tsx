import { Boxes, CirclePause, Container, ShieldAlert, type LucideIcon } from "lucide-react"
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react"

import { Composer } from "@/components/Composer"
import { Exchange } from "@/components/Exchange"
import { Header, type Mode } from "@/components/Header"
import { TooltipProvider } from "@/components/ui/tooltip"
import examples from "@/examples.json"
import { isFinished, newMessage, reduce, type Message, type TraceEvent } from "@/lib/events"
import { askLive, backendIsUp } from "@/lib/live"
import { paced } from "@/lib/pace"
import { playReplay } from "@/lib/replay"

type Group = { label: string; hint?: string; questions: string[] }

const Report = lazy(() => import("@/pages/Report"))

const GROUP_ICON: Record<string, LucideIcon> = { Kubernetes: Boxes, Docker: Container, "Try to trick it": ShieldAlert }

// Where the 15-minute backend is started (docs/DEMO-PLAN.md § 4). Until that workflow
// exists, the page runs on recorded answers only.
const START_BACKEND_URL = "https://github.com/adssib/InfraChat/actions"

type Item = { kind: "run"; m: Message } | { kind: "offline"; id: string; question: string }

function Examples({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {(examples as Group[]).map((g) => {
        const Icon = GROUP_ICON[g.label] ?? Boxes
        const trick = g.label === "Try to trick it"
        return (
          <section key={g.label} aria-labelledby={`ex-${g.label}`} className="glass rounded-2xl p-2">
            <h2 id={`ex-${g.label}`} className="flex items-center gap-2 px-2 pt-1.5 pb-2 text-xs font-medium text-muted-foreground">
              <Icon className={trick ? "size-3.5 text-refuse" : "size-3.5 text-primary"} aria-hidden />
              {g.label}
            </h2>
            <ul className="space-y-0.5">
              {g.questions.map((q) => (
                <li key={q}>
                  <button
                    type="button"
                    onClick={() => onPick(q)}
                    className="w-full rounded-xl px-2 py-1.5 text-left text-sm leading-5 text-foreground/85 transition-colors hover:bg-[var(--glass-strong)] hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  >
                    {q}
                  </button>
                </li>
              ))}
            </ul>
            {g.hint && <p className="px-2 pt-2 pb-1 text-xs text-muted-foreground">{g.hint}</p>}
          </section>
        )
      })}
    </div>
  )
}

function OfflineNotice({ question }: { question: string }) {
  return (
    <article className="space-y-5">
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-md bg-[linear-gradient(135deg,rgb(41_159_255/0.22),rgb(139_92_246/0.18))] px-4 py-2.5 text-[15px] leading-6 ring-1 ring-white/10">{question}</p>
      </div>
      <div className="glass flex gap-3 rounded-xl px-4 py-3 text-sm">
        <CirclePause className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="space-y-1">
          <p className="font-medium">Live answers are off right now</p>
          <p className="text-muted-foreground">
            This page is showing recorded answers. Pick one of the example questions, or{" "}
            <a href={START_BACKEND_URL} className="text-primary underline-offset-4 hover:underline">start a 15-minute live session</a>.
          </p>
        </div>
      </div>
    </article>
  )
}

const pageFromHash = () => (window.location.hash.startsWith("#/report") ? "report" : "chat")

export default function App() {
  const [items, setItems] = useState<Item[]>([])
  const [page, setPage] = useState<"chat" | "report">(pageFromHash)
  useEffect(() => {
    const on = () => { setPage(pageFromHash()); window.scrollTo({ top: 0 }) }
    window.addEventListener("hashchange", on)
    return () => window.removeEventListener("hashchange", on)
  }, [])
  const [mode, setMode] = useState<Mode>("checking")
  const modeRef = useRef<Promise<Mode> | null>(null)
  // Ask the backend once whether a session is up; every question waits on that answer, so
  // a ?q= link opened mid-check still goes to the right place.
  modeRef.current ??= backendIsUp().then((up) => { const m: Mode = up ? "live" : "offline"; setMode(m); return m })
  const abort = useRef<AbortController | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  const busy = items.some((i) => i.kind === "run" && !isFinished(i.m))

  const ask = useCallback(async (question: string) => {
    abort.current?.abort()
    const ctrl = new AbortController()
    abort.current = ctrl
    const id = crypto.randomUUID()
    const live = (await modeRef.current) === "live"
    setItems((xs) => [...xs, { kind: "run", m: newMessage(id, question, live ? "live" : "replay") }])
    const onEvent = paced((e: TraceEvent) =>
      setItems((xs) => xs.map((x) => (x.kind === "run" && x.m.id === id ? { kind: "run", m: reduce(x.m, e) } : x))), ctrl.signal)
    let found = true
    if (live) await askLive(question, onEvent, ctrl.signal)
    else found = await playReplay(question, onEvent, ctrl.signal)
    if (ctrl.signal.aborted) {
      // Superseded (a new conversation, or StrictMode's double-run in development).
      setItems((xs) => xs.filter((x) => !(x.kind === "run" && x.m.id === id && !isFinished(x.m))))
      return
    }
    if (!found) setItems((xs) => xs.map((x) => (x.kind === "run" && x.m.id === id ? { kind: "offline", id, question } : x)))
  }, [])

  useEffect(() => { bottom.current?.scrollIntoView({ block: "end", behavior: "smooth" }) }, [items])

  // ?q=<question> asks on load, so a link can open on a specific example.
  const asked = useRef(false)
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q")
    if (q && !asked.current) { asked.current = true; void ask(q) }
  }, [ask])

  const empty = items.length === 0

  return (
    <TooltipProvider delayDuration={150}>
      <div className="flex min-h-dvh flex-col">
        <Header mode={mode} page={page} onHome={() => { abort.current?.abort(); setItems([]); window.location.hash = "#/" }} />

        {page === "report" ? (
          <Suspense fallback={<div className="flex-1" />}><Report /></Suspense>
        ) : empty ? (
          <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-4 pb-16 sm:px-6">
            <h1 className="text-[clamp(1.75rem,4vw,2.25rem)] leading-tight font-medium tracking-tight text-balance">
              Ask the Kubernetes and Docker docs.
            </h1>
            <p className="mt-3 max-w-[60ch] text-muted-foreground text-pretty">
              Every answer cites the lines it came from. If the docs don&apos;t cover your question, it says so instead of guessing.
            </p>
            <div className="mt-8"><Composer onSend={ask} busy={busy} autoFocus /></div>
            <div className="mt-10"><Examples onPick={ask} /></div>
          </main>
        ) : (
          <>
            <main className="mx-auto w-full max-w-3xl flex-1 space-y-10 px-4 pt-4 pb-8 sm:px-6">
              {items.map((it) => (it.kind === "run"
                ? <Exchange key={it.m.id} m={it.m} />
                : <OfflineNotice key={it.id} question={it.question} />))}
              <div ref={bottom} />
            </main>
            <div className="sticky bottom-0 px-4 pt-6 pb-4 sm:px-6 [background:linear-gradient(to_top,var(--background)_55%,transparent)]">
              <div className="mx-auto max-w-3xl"><Composer onSend={ask} busy={busy} /></div>
            </div>
          </>
        )}
      </div>
    </TooltipProvider>
  )
}
