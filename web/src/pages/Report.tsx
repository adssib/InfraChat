// "How it's built": the write-up behind the demo. Every number here comes from the
// committed eval runs (eval/runs/*.jsonl) or a measurement recorded in docs/ — if one
// changes, change it there first.

import { ArrowRight, Ban, Check, ExternalLink } from "lucide-react"
import type { ReactNode } from "react"

import { GitHubMark } from "@/components/Header"
import { cn } from "@/lib/utils"

const REPO = "https://github.com/adssib/InfraChat"
const base = import.meta.env.BASE_URL

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-h`} className="scroll-mt-24 space-y-4">
      <h2 id={`${id}-h`} className="text-xl font-medium tracking-tight">{title}</h2>
      {children}
    </section>
  )
}

const P = ({ children }: { children: ReactNode }) => (
  <p className="max-w-[78ch] text-[15px] leading-7 text-foreground/85 text-pretty">{children}</p>
)

function Figure({ src, alt, caption }: { src: string; alt: string; caption: ReactNode }) {
  return (
    <figure className="space-y-2">
      <div className="overflow-hidden rounded-2xl bg-white p-2 ring-1 ring-white/10">
        <img src={`${base}report/${src}`} alt={alt} loading="lazy" className="w-full rounded-xl" />
      </div>
      <figcaption className="text-sm text-muted-foreground">{caption}</figcaption>
    </figure>
  )
}

function Flow({ steps }: { steps: { label: string; note: string; tone?: "gate" | "end" }[] }) {
  return (
    <ol className="flex flex-wrap items-stretch gap-2" aria-label="Pipeline">
      {steps.map((s, i) => (
        <li key={s.label} className="flex items-center gap-2">
          <div className={cn(
            "glass rounded-xl px-3 py-2",
            s.tone === "gate" && "ring-1 ring-refuse/40",
            s.tone === "end" && "ring-1 ring-primary/40",
          )}>
            <p className="text-sm font-medium">{s.label}</p>
            <p className="font-mono text-[11px] text-muted-foreground">{s.note}</p>
          </div>
          {i < steps.length - 1 && <ArrowRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />}
        </li>
      ))}
    </ol>
  )
}

const RESULTS = [
  { name: "Baseline (meaning search)", mrr: "0.795", recall: "0.952", fr: "6.2%", lat: "—", verdict: "start" },
  { name: "+ Reranker", mrr: "0.877", recall: "0.857", fr: "4.6%", lat: "+821 ms", verdict: "off" },
  { name: "+ Hybrid search", mrr: "0.858", recall: "0.952", fr: "3.1%", lat: "+6 ms", verdict: "shipped" },
  { name: "+ Query rewriter", mrr: "≈ +1 question", recall: "—", fr: "—", lat: "+1 LLM call", verdict: "off" },
]

function ResultsTable() {
  return (
    <div className="glass overflow-x-auto rounded-2xl">
      <table className="w-full min-w-[560px] text-sm">
        <caption className="sr-only">Results per component</caption>
        <thead>
          <tr className="border-b border-[var(--glass-edge)] text-left text-xs text-muted-foreground">
            <th className="px-4 py-3 font-medium">Configuration</th>
            <th className="px-3 py-3 font-medium">Ranking (MRR)</th>
            <th className="px-3 py-3 font-medium">Traps refused</th>
            <th className="px-3 py-3 font-medium">Wrongly refused</th>
            <th className="px-3 py-3 font-medium">Added time</th>
            <th className="px-4 py-3 font-medium">Verdict</th>
          </tr>
        </thead>
        <tbody className="font-mono tabular-nums">
          {RESULTS.map((r) => (
            <tr key={r.name} className={cn("border-b border-[var(--glass-edge)] last:border-0", r.verdict === "shipped" && "bg-primary/[0.07]")}>
              <th scope="row" className="px-4 py-2.5 text-left font-sans font-normal">{r.name}</th>
              <td className="px-3 py-2.5">{r.mrr}</td>
              <td className="px-3 py-2.5">{r.recall}</td>
              <td className="px-3 py-2.5">{r.fr}</td>
              <td className="px-3 py-2.5">{r.lat}</td>
              <td className="px-4 py-2.5 font-sans">
                {r.verdict === "shipped" ? (
                  <span className="inline-flex items-center gap-1 text-ok"><Check className="size-3.5" aria-hidden />Shipped</span>
                ) : r.verdict === "off" ? (
                  <span className="inline-flex items-center gap-1 text-muted-foreground"><Ban className="size-3.5" aria-hidden />Off</span>
                ) : (
                  <span className="text-muted-foreground">Starting point</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Finding({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="glass space-y-2 rounded-2xl p-5">
      <h3 className="font-medium">{title}</h3>
      <div className="space-y-2 text-sm leading-6 text-foreground/80">{children}</div>
    </div>
  )
}

const TOC = [
  ["problem", "The problem"], ["design", "Refuse instead of guess"], ["method", "One piece at a time"],
  ["eval", "How it's measured"], ["results", "What the numbers said"], ["lessons", "What I learned"],
  ["deploy", "How it runs"], ["limits", "What it doesn't do yet"],
] as const

function Toc({ className }: { className?: string }) {
  return (
    <nav aria-label="On this page" className={className}>
      <p className="mb-2 px-1 text-xs text-muted-foreground">On this page</p>
      <ol className="space-y-0.5 text-sm">
        {TOC.map(([id, label], i) => (
          <li key={id}>
            <a href="#/report" onClick={(e) => { e.preventDefault(); document.getElementById(id)?.scrollIntoView({ behavior: "smooth" }) }}
              className="flex gap-3 rounded-lg px-1 py-1 text-muted-foreground transition-colors hover:bg-[var(--glass)] hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
              <span className="w-4 font-mono text-xs leading-5 text-primary/80">{i + 1}</span>{label}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  )
}

export default function Report() {
  return (
    // The contents list is docked to the left edge, under the wordmark; the article is
    // centred in the space beside it.
    <main className="w-full flex-1 pt-10 pb-24 lg:grid lg:grid-cols-[minmax(220px,1fr)_minmax(0,1100px)_minmax(0,1fr)]">
      <aside className="hidden lg:block lg:pl-7">
        <Toc className="sticky top-28 w-[210px]" />
      </aside>
      <div className="min-w-0 px-4 sm:px-8">
      <header className="max-w-4xl space-y-4 pb-10">
        <h1 className="text-[clamp(1.9rem,4.5vw,2.6rem)] leading-tight font-medium tracking-tight text-balance">
          How InfraChat was built, and what measuring it taught me
        </h1>
        <P>
          InfraChat answers questions from the Kubernetes and Docker documentation, cites the page every answer
          came from, and refuses when the docs don&apos;t cover the question. The part worth reading is how it got
          there: a fixed set of 87 test questions came first, then each retrieval component was added one at a time
          and kept only if the numbers said it earned its place.
        </P>
        <div className="flex flex-wrap gap-2 pt-1">
          <a href={REPO} target="_blank" rel="noreferrer" className="glass inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm transition-colors hover:bg-[var(--glass-strong)] focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
            <GitHubMark className="size-4" /> Source code
          </a>
          <a href="#/" className="accent-gradient inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium text-white shadow-[0_4px_18px_-4px_rgb(41_159_255/0.7)] focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
            Try it <ArrowRight className="size-4" aria-hidden />
          </a>
        </div>
        <Toc className="glass mt-4 rounded-2xl p-4 lg:hidden" />
      </header>
      <div className="min-w-0 space-y-16">
        <Section id="problem" title="The problem">
          <P>
            A standard retrieval-augmented chatbot always answers. Search never returns &ldquo;nothing&rdquo;: it hands
            the model its five closest passages, and the model writes something fluent from them whether or not they
            contain the answer. On infrastructure questions that&apos;s the dangerous failure. A confident wrong
            command gets pasted into a real cluster.
          </P>
          <P>
            So InfraChat has two rules: every answer cites where it came from, or it refuses; and every component has
            to show, with a number, that it makes the system better.
          </P>
        </Section>

        <Section id="design" title="Refuse instead of guess">
          <P>
            The corpus is 281 pages of the Kubernetes concepts docs and the Docker build docs, split into 4,908
            passages and indexed two ways: by meaning (embeddings) and by keyword (BM25), all in one SQLite file. A
            question passes two independent checks before anyone sees an answer:
          </P>
          <Flow steps={[
            { label: "Search", note: "meaning + keyword, 20 passages" },
            { label: "Gate 1: similarity", note: "best match ≥ 0.65", tone: "gate" },
            { label: "Model reads top 5", note: "gpt-oss-20b on Groq" },
            { label: "Gate 2: citations", note: "cites what it was shown", tone: "gate" },
            { label: "Answer or refusal", note: "with page links", tone: "end" },
          ]} />
          <P>
            Gate 1 is cheap and catches the obviously off-topic, like &ldquo;What is the capital of France?&rdquo;,
            before the model is ever called. Gate 2 reads the model&apos;s answer and refuses it unless it cites a
            passage it was actually shown; the model can also say the passages don&apos;t answer the question.
          </P>
        </Section>

        <Section id="method" title="One piece at a time">
          <P>
            The system was built as a baseline plus one component per phase. Each component sits behind a small
            interface with a do-nothing default, so turning it on is a one-line config change and the rest of the
            pipeline never changes. The two gates never change either: components can only change what reaches them.
          </P>
          <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              ["Baseline", "Meaning search, both gates, and the eval harness, built first."],
              ["Reranker", "A second model re-reads the top 20 passages with the question and re-orders them."],
              ["Hybrid search", "Keyword search runs beside meaning search; the two lists are merged by rank."],
              ["Query rewriter", "An LLM expands the question before searching."],
            ].map(([t, d], i) => (
              <li key={t} className="glass rounded-2xl p-4">
                <p className="flex items-baseline gap-2 text-sm font-medium"><span className="font-mono text-xs text-primary">Phase {i + 1}</span>{t}</p>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">{d}</p>
              </li>
            ))}
          </ol>
        </Section>

        <Section id="eval" title="How it's measured">
          <P>
            87 fixed questions: 33 about Kubernetes, 33 about Docker, and 21 that should be refused. 20 of those 21
            are near-misses built to look answerable, like Docker Compose, Helm or GitLab CI, which sit right next
            to the indexed docs without being in them. Easy refusal questions prove nothing.
          </P>
          <P>
            Every run records what could change its results (corpus commit, model, prompt, chunk size), and runs are
            only compared on the same question set. The metrics: <strong className="font-medium text-foreground">MRR</strong> for
            how high the right page ranks, <strong className="font-medium text-foreground">traps refused</strong> (refusal recall), <strong className="font-medium text-foreground">wrongly
            refused</strong> answerable questions, and whether every citation points to a passage the model was shown.
          </P>
        </Section>

        <Section id="results" title="What the numbers said">
          <ResultsTable />
          <P>
            Paired on the 86 questions that completed in every run. Citation validity was 1.000 in every
            configuration: no invented citations. Latency is retrieval time, measured back to back.
          </P>
          <div className="grid gap-6 xl:grid-cols-2">
          <Figure
            src="cost-vs-gain.png"
            alt="Scatter of added latency against MRR: hybrid reaches 0.858 at +10 ms, the reranker 0.877 at +725 ms with a smaller refusal-recall bubble"
            caption="Hybrid search got 71% of the reranker's ranking gain at 0.8% of its latency, and kept every refusal."
          />
          <Figure
            src="refusal-outcomes.png"
            alt="Stacked bars of correct refusals, leaks and false refusals for baseline, reranker and hybrid"
            caption="The reranker answered 2 trap questions the baseline had refused. Hybrid didn't, and halved the wrongly refused questions."
          />
          </div>
        </Section>

        <Section id="lessons" title="What I learned">
          <div className="grid gap-3 md:grid-cols-2">
            <Finding title="The component that ranked best made the system less honest">
              <p>
                The reranker lifted ranking by 0.08 MRR, the biggest gain of any component. It also turned two trap
                questions into confident wrong answers with valid citations. A reranker finds the most plausible
                passage for a question; when the answer isn&apos;t in the docs, that&apos;s the most plausible wrong
                passage. Hybrid search shipped instead.
              </p>
            </Finding>
            <Finding title="No similarity threshold can tell answerable from unanswerable">
              <p>
                78% of the questions sit in the band where answerable and trap questions overlap. One trap, about
                GitLab CI, scored 0.834: higher than 48 of the 66 answerable questions. The threshold that maximised
                accuracy scored 79.3% on the questions it was tuned on and 75.2% on held-out ones, worse than not
                tuning. So gate 1 is a cheap first filter, set by a fixed rule, and gate 2 does the real work.
              </p>
            </Finding>
            <Finding title="The worst bugs don't crash, they lower the score">
              <p>
                Neighbouring passages are meant to overlap so an answer on a boundary isn&apos;t cut in half. A bug meant
                59% of boundaries had no overlap at all, and nothing errored. Measuring it found it: fixing it raised
                bridged boundaries from 41% to 96.5%, and ranking on paraphrased questions from 0.39 to 0.70.
              </p>
            </Finding>
            <Finding title="Not shipping something is a result too">
              <p>
                The query rewriter was worth about one question out of 66, for an extra LLM call on every question and
                weaker refusals. It stays in the code, switched off, with the reasoning written down.
              </p>
            </Finding>
          </div>
          <div className="grid gap-6 xl:grid-cols-2">
            <Figure
              src="floor-overlap.png"
              alt="Dot plot of top similarity scores for answerable and trap questions, overlapping between 0.70 and 0.83"
              caption="Answerable questions (top) and traps (bottom) overlap almost entirely above the floor."
            />
            <Figure
              src="floor-sweep.png"
              alt="Two curves against the floor value: traps refused and good questions wrongly refused rise together above 0.70"
              caption="Every floor that catches more traps also refuses more good questions. 0.65 came from a fixed rule, not from tuning."
            />
          </div>
        </Section>

        <Section id="deploy" title="How it runs">
          <Flow steps={[
            { label: "This page", note: "GitHub Pages, always on" },
            { label: "API", note: "Litestar, Azure Container Apps" },
            { label: "LLM", note: "Groq, streamed", tone: "end" },
          ]} />
          <P>
            The page you&apos;re reading is static and free to host. The backend runs in 15-minute sessions: a button in
            GitHub Actions runs Terraform to start a container on Azure, and the session deletes itself when it
            expires. Starting one takes about 40 seconds and costs about 3 cents. With no session running, the page
            replays real recorded runs of the example questions.
          </P>
          <P>
            Every push runs the tests, validates the Terraform, builds the container image with the search index
            inside it, checks that the image answers a question with no network access, and publishes it. The answer
            streams to the browser as Server-Sent Events: each step of the pipeline arrives as it happens, which is
            what the trace above every answer shows.
          </P>
        </Section>

        <Section id="limits" title="What it doesn't do yet">
          <ul className="max-w-[78ch] list-disc space-y-2 pl-5 text-[15px] leading-7 text-foreground/85 marker:text-muted-foreground">
            <li>
              Gate 2 proves where an answer came from, not that the passage supports it. The reranker&apos;s wrong
              answers passed it. Checking each cited sentence against its passage is the next thing to build.
            </li>
            <li>
              87 questions, all written by me, is a small set: one question moves a rate by about 1.1 points. The
              measured direction is clear; the exact sizes are not.
            </li>
            <li>Citations link to the page, not the exact lines, until line numbers are recorded against the original files.</li>
          </ul>
        </Section>

        <footer className="glass flex flex-wrap items-center justify-between gap-3 rounded-2xl p-5 text-sm">
          <p className="text-muted-foreground">
            Built by <a href="https://github.com/adssib" target="_blank" rel="noreferrer" className="text-foreground underline-offset-4 hover:underline">Adib Akkari</a>.
            Decisions, eval runs and code are all in the repository.
          </p>
          <a href={`${REPO}/tree/master/docs/decisions`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-primary underline-offset-4 hover:underline">
            Read the decision records <ExternalLink className="size-3.5" aria-hidden />
          </a>
        </footer>
      </div>
      </div>
    </main>
  )
}
