import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowRight } from 'lucide-react'

import { UploadDropzone } from '@/components/extraction/UploadDropzone'

export const Route = createFileRoute('/')({
  component: HomePage,
})

/**
 * The front door.
 *
 * The hero is the product's actual claim, drawn rather than described: a cell
 * in an extracted table wired to the exact spot on the page it came from. Every
 * table extractor can produce a grid of strings; the one thing worth showing is
 * that each string can be traced back to the pixels it was read from.
 *
 * Upload lives here, not one click further in, because uploading a PDF *is*
 * the first thing anyone arriving wants to do.
 */
function HomePage() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-10 px-6 py-12">
      <header className="flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground">
          PDF table extraction
        </p>
        <h1 className="max-w-2xl text-balance text-4xl font-semibold leading-[1.08] tracking-tight">
          Every number, traced back to the page it came from.
        </h1>
        <p className="max-w-xl text-pretty text-sm leading-relaxed text-muted-foreground">
          Tracepaper reads tables out of any PDF and keeps the receipt. Click a cell and see it
          highlighted in the original — the exact characters, at the exact coordinates, with the
          source that produced them.
        </p>
      </header>

      <TraceDiagram />

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium">Start with a PDF</h2>
        <UploadDropzone />
        <Link
          to="/documents"
          className="inline-flex w-fit items-center gap-1.5 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          Or open a document you have already extracted
          <ArrowRight className="size-3.5" />
        </Link>
      </section>

      <section className="grid gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-3">
        <Pillar title="Exact text, not a re-reading">
          Values come from the PDF&rsquo;s own text layer wherever it has one, so
          <span className="font-mono"> ₹1,25,000</span> is the file&rsquo;s characters — not an
          OCR guess at them.
        </Pillar>
        <Pillar title="Structure that survives">
          Merged headers, row and column spans, and multi-page tables are kept as the document laid
          them out, not flattened into a rectangle.
        </Pillar>
        <Pillar title="Auditable by construction">
          Each cell records what every source read, which one was used, and the geometry that
          joined them. Disagreements are surfaced, never silently resolved.
        </Pillar>
      </section>
    </div>
  )
}

function Pillar({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 bg-card p-4">
      <h3 className="text-sm font-medium">{title}</h3>
      <p className="text-xs leading-relaxed text-muted-foreground">{children}</p>
    </div>
  )
}

/**
 * The signature: a cell on the right, its source on the left, one thread
 * between them. Static and honest — these are the real shapes the viewer draws.
 */
function TraceDiagram() {
  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <div className="grid gap-px bg-border sm:grid-cols-2">
        <figure className="flex flex-col gap-2 bg-card p-4">
          <figcaption className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            In the PDF
          </figcaption>
          <div className="page-surface relative aspect-[7/4] w-full overflow-hidden rounded-sm">
            <svg viewBox="0 0 280 160" className="size-full" role="img" aria-label="A table on a PDF page with one cell highlighted">
              <rect width="280" height="160" fill="#fff" />
              {[38, 62, 86, 110, 134].map((y) => (
                <line key={y} x1="16" x2="264" y1={y} y2={y} stroke="#dbe0e8" strokeWidth="1" />
              ))}
              {[16, 120, 176, 220, 264].map((x) => (
                <line key={x} x1={x} x2={x} y1="14" y2="134" stroke="#dbe0e8" strokeWidth="1" />
              ))}
              <rect x="16" y="14" width="248" height="24" fill="#f1f3f7" />
              <text x="24" y="30" fontSize="9" fill="#6b7280" fontFamily="ui-sans-serif">Particulars</text>
              <text x="128" y="30" fontSize="9" fill="#6b7280" fontFamily="ui-sans-serif">Q1 26-27</text>
              <text x="184" y="30" fontSize="9" fill="#6b7280" fontFamily="ui-sans-serif">Q1 25-26</text>
              <text x="24" y="54" fontSize="9" fill="#111827" fontFamily="ui-sans-serif">Premiums earned</text>
              <text x="168" y="54" fontSize="9" fill="#111827" textAnchor="end" fontFamily="ui-monospace">11,149</text>
              <text x="216" y="54" fontSize="9" fill="#111827" textAnchor="end" fontFamily="ui-monospace">14,168</text>
              <text x="24" y="78" fontSize="9" fill="#111827" fontFamily="ui-sans-serif">Investment income</text>
              <text x="168" y="78" fontSize="9" fill="#111827" textAnchor="end" fontFamily="ui-monospace">315</text>
              <text x="216" y="78" fontSize="9" fill="#111827" textAnchor="end" fontFamily="ui-monospace">876</text>
              {/* The cell box, then the exact glyph box inside it. */}
              <rect x="120" y="38" width="56" height="24" fill="var(--selected)" fillOpacity="0.12" stroke="var(--selected)" strokeWidth="1.5" />
              <rect x="139" y="45" width="30" height="11" fill="var(--confirmed)" fillOpacity="0.28" stroke="var(--confirmed)" strokeWidth="1.5" />
            </svg>
          </div>
        </figure>

        <figure className="flex flex-col gap-2 bg-card p-4">
          <figcaption className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            What you get back
          </figcaption>
          <div className="flex-1 overflow-x-auto rounded-sm border bg-background">
            <pre className="p-3 font-mono text-[10.5px] leading-relaxed">
              <code>
                <span className="text-muted-foreground">{'{'}</span>
                {'\n  "text": '}
                <span className="text-confirmed-strong">&quot;11,149&quot;</span>
                {',\n  "bbox": [265.3, 154.5, 296.3, 161.9],\n  "confidence": 0.997,\n  "source": '}
                <span className="text-confirmed-strong">&quot;pdf text layer&quot;</span>
                {',\n  "match": '}
                <span className="text-confirmed-strong">&quot;exact&quot;</span>
                {'\n'}
                <span className="text-muted-foreground">{'}'}</span>
              </code>
            </pre>
          </div>
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            Coordinates are in PDF points from the top-left, so the value can be located in the
            original by anything downstream — not just by this interface.
          </p>
        </figure>
      </div>
    </div>
  )
}
