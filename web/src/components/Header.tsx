import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

const GITHUB_PROFILE = "https://github.com/adssib"
const START_BACKEND_URL = "https://github.com/adssib/InfraChat/actions"

export type Mode = "checking" | "live" | "offline"

// lucide dropped brand logos, so the GitHub mark is GitHub's own octicon path.
export function GitHubMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} aria-hidden fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  )
}

function Wordmark() {
  return (
    <span className="flex items-center gap-2 font-mono text-sm font-semibold tracking-tight">
      <span className="accent-gradient flex size-6 items-center justify-center rounded-lg shadow-[0_0_16px_-2px_rgb(41_159_255/0.6)]">
        <svg viewBox="0 0 32 32" className="size-4" aria-hidden>
          <path d="M9 21V11m7 10V11m7 10v-6" stroke="white" strokeWidth="3.5" strokeLinecap="round" />
        </svg>
      </span>
      infrachat
    </span>
  )
}

function ModePill({ mode }: { mode: Mode }) {
  if (mode === "live")
    return (
      <span className="glass flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs text-foreground" title="Questions are answered live by the backend">
        <span className="relative flex size-2">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-ok opacity-60 motion-reduce:hidden" />
          <span className="relative inline-flex size-2 rounded-full bg-ok" />
        </span>
        Live
      </span>
    )
  return (
    <a
      href={START_BACKEND_URL}
      className="glass flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      title="Live answers need the backend, which runs in 15-minute sessions"
    >
      <span className="size-1.5 rounded-full bg-muted-foreground/60" aria-hidden />
      {mode === "checking" ? "Connecting" : "Recorded answers"}
    </a>
  )
}

function NavLink({ href, active, children }: { href: string; active: boolean; children: ReactNode }) {
  return (
    <a
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "rounded-full px-3 py-1.5 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        active ? "glass-strong text-foreground" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </a>
  )
}

export function Header({ mode, page, onHome }: { mode: Mode; page: "chat" | "report"; onHome: () => void }) {
  return (
    <header className="sticky top-3 z-20 mx-3 sm:mx-4">
      <div className="glass flex items-center justify-between gap-3 rounded-2xl px-3 py-2 sm:px-4">
        <div className="flex items-center gap-4">
          <button type="button" onClick={onHome} className="rounded-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none" aria-label="New conversation">
            <Wordmark />
          </button>
          <nav className="hidden items-center gap-1 sm:flex" aria-label="Pages">
            <NavLink href="#/" active={page === "chat"}>Ask</NavLink>
            <NavLink href="#/report" active={page === "report"}>How it's built</NavLink>
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <ModePill mode={mode} />
          <a
            href={GITHUB_PROFILE}
            target="_blank"
            rel="noreferrer"
            className="glass flex items-center gap-2 rounded-full py-1.5 pr-3.5 pl-2.5 text-sm font-medium transition-[background-color,transform] hover:bg-[var(--glass-strong)] active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <GitHubMark className="size-4" />
            <span className="hidden sm:inline">Adib Akkari</span>
            <span className="sr-only sm:hidden">Adib Akkari on GitHub</span>
          </a>
        </div>
      </div>
      <nav className="mt-2 flex justify-center gap-1 sm:hidden" aria-label="Pages">
        <NavLink href="#/" active={page === "chat"}>Ask</NavLink>
        <NavLink href="#/report" active={page === "report"}>How it's built</NavLink>
      </nav>
    </header>
  )
}
