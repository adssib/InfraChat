// The report page shows the eval charts. Their source of truth is docs/images/results/
// (rendered by scripts/plot_results.py); copy them in rather than keep a second copy in git.
import { copyFileSync, mkdirSync, readdirSync } from "node:fs"
import { join } from "node:path"

const src = join(import.meta.dirname, "..", "..", "docs", "images", "results")
const dst = join(import.meta.dirname, "..", "public", "report")
mkdirSync(dst, { recursive: true })
const pngs = readdirSync(src).filter((f) => f.endsWith(".png"))
for (const f of pngs) copyFileSync(join(src, f), join(dst, f))
console.log(`report-assets: ${pngs.length} charts → public/report/`)
