# PDF extraction

Two tools, one canonical document, and a rule about who owns what.

```
                          PDF
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
         PyMuPDF                    Azure DI
   metadata, geometry,          tables, layout,
   exact text, coordinates,     OCR, confidence
   images, links, fonts              │
              │                      │
              └──────────┬───────────┘
                         ▼
                  Normalization
        coordinate mapping · cell matching · provenance
                         │
                         ▼
                  Canonical JSON
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
         Backend API            Frontend
                            table viewer + PDF
```

**PyMuPDF owns deterministic PDF data. Azure DI owns document structure. The
normalization layer connects them without either overwriting the other.**

## Why the split

Azure Document Intelligence is good at a thing PDFs cannot tell you: which
rectangles on a page form a table, and how that table divides into rows and
columns. It is *not* the best source for the characters themselves when the PDF
already contains them — it is reading a rendering of text the file spells out
exactly.

So Azure supplies structure and confidence; PyMuPDF supplies every value that
the file itself determines. Where they overlap, both readings are kept and the
choice between them is recorded.

## Coordinate space

Every bounding box in the canonical document is in **page display space**:

- origin at the top-left of the page as a human sees it,
- units of PDF points (1/72 inch),
- axis-aligned, `x0 <= x1` and `y0 <= y1`,
- page size equal to PyMuPDF's `page.rect` — that is, **after** `/Rotate`.

Neither tool reports in this space natively.

**PyMuPDF** reports text in the *unrotated mediabox*, but renders in the
rotated space. On a `/Rotate 90` A4 page, `get_text("words")` puts a word at
`(100, 187)` while `get_pixmap()` produces an 842×595 image — the box lands
off-page. Every box is therefore pushed through `page.rotation_matrix`:

| rotation | `page.rect` | raw word box | display box |
| --- | --- | --- | --- |
| 0 | 595 × 842 | (100.0, 187.1, 139.3, 203.6) | (100.0, 187.1, 139.3, 203.6) |
| 90 | 842 × 595 | (100.0, 187.1, 139.3, 203.6) | (638.4, 100.0, 654.9, 139.3) |
| 180 | 595 × 842 | (100.0, 187.1, 139.3, 203.6) | (455.7, 638.4, 495.0, 654.9) |
| 270 | 842 × 595 | (100.0, 187.1, 139.3, 203.6) | (187.1, 455.7, 203.6, 495.0) |

**Azure DI** reports 4-point polygons in the units named by `page.unit` —
`inch` for PDF input, `pixel` for images — on a page it has already turned
upright. Conversion takes the axis-aligned hull, then rescales by the **ratio
of the two page sizes**:

```
scale_x = pymupdf_page.width / azure_page.width
scale_y = pymupdf_page.height / azure_page.height
```

Not a hard-coded 72 dpi. For `nl-1.pdf` the factors come out at **72.058** and
**72.024** — the service and the mediabox disagree by a fraction of a percent,
and assuming 72 would misplace the right-hand columns by about a point. Using
the ratio also makes the conversion unit-agnostic: inches and pixels both work
with no branch.

## Cell matching

Deterministic and reproducible. No language model, no fuzzy string matching.

**Membership.** A PyMuPDF word belongs to a cell when at least
`word_containment_threshold` (default **0.55**) of the word's area falls inside
the cell box.

Containment, not IoU: a word is far smaller than its cell, so a perfect match
still scores a near-zero IoU.

The threshold is above 0.5 for a specific reason — **a cell grid does not
overlap, so a word can exceed 50% containment in at most one cell**. Membership
is therefore an *exclusive assignment*: each word lands in exactly one cell, or
none, with no tie-break and no chance of being read into two columns. `nl-1.pdf`
depends on this: its nil markers are right-aligned dashes straddling a column
rule at 68% / 32%, and each is placed in exactly the right column.

**Grading.** The words in a cell are joined in PyMuPDF's own `(block, line,
word)` reading order, then graded on `containment` — the fraction of the
matched words' *union* that lies inside the cell:

| method | condition | text used |
| --- | --- | --- |
| `exact` | strings equal after Unicode/whitespace normalization | PyMuPDF |
| `spatial` | strings differ, containment ≥ threshold | PyMuPDF |
| `weak` | the union escapes the cell despite membership | Azure |
| `none` | no words inside the cell | Azure |

`spatial` prefers PyMuPDF deliberately: it is the literal content of the file,
and a divergence is nearly always Azure re-reading — or dropping — a glyph the
PDF already spells out.

### Why not IoU

An earlier version graded on IoU with a 0.35 bar. IoU between a cell and its
text is not a measure of match quality; it is a measure of how much padding the
cell has. On `nl-1.pdf`, 148 cells hold a single `-` in a 30pt-wide numeric
column. Those dashes are real PDF content that Azure dropped, they sit perfectly
inside their cells, and their IoU is about **0.05**. Grading on IoU rejected all
148 and kept Azure's empty string — silently losing real text and inverting the
ownership rule this pipeline exists to enforce.

Containment has no such bias: a word wholly inside its cell scores 1.0 whether
the cell is snug or generously padded. IoU is still computed and reported so a
reviewer can see the geometry, but it never decides anything.

Measured on `nl-1.pdf`:

| grading rule | populated cells matched |
| --- | --- |
| IoU ≥ 0.35 | 369 / 521 (70.8%) |
| containment ≥ 0.8 | 513 / 521 (98.5%) |
| containment ≥ 0.55 (shipped) | **519 / 521 (99.6%)** |

The two remaining cells are Azure `:unselected:` selection marks — checkbox
state, which has no PDF text by definition. That is a correct outcome, not a
failure.

### Empty cells are not failures

A filing table is mostly blank grid: `nl-1.pdf` has 714 cells of which 343 hold
nothing at all. `MatchingStats` counts those separately and excludes them from
`match_rate`, because reporting "52% matched" for an extraction that resolved
369 of 371 populated cells exactly would destroy trust in the number.

## Confidence

`DocumentTableCell` has **no** confidence field in the Azure SDK — only words
do. A cell's confidence is therefore derived by averaging the confidences of the
words whose character spans fall inside the cell's spans.

When no word in range carries a confidence — usual for born-digital PDFs, where
the service reads embedded text rather than running OCR — the result is `null`,
surfaced in the UI as "not reported" rather than as a zero-confidence read.

## Degradation

**A failure in Azure DI never discards a successful PyMuPDF extraction.**

PyMuPDF runs first and its failure is fatal — there is no document without it.
Azure runs second and its failure is recorded as data, leaving a `partial`
document that still has text, coordinates, geometry, and metadata:

```json
{
  "extraction": {
    "pymupdf": { "completed": true, "version": "1.28.2" },
    "azure_di": {
      "completed": false,
      "error": { "code": "azure_rate_limited", "message": "…", "retryable": true }
    }
  }
}
```

`POST /documents/{id}/extract` re-runs the pipeline over the stored bytes to
fill in the tables once the service recovers.

Errors are mapped once, in `map_azure_error`, so retryability is decided in one
place: 401/403 and 4xx are permanent, 429/408/5xx and network faults retry with
exponential backoff and full jitter, and the service's own `Retry-After` always
wins over the curve.

## Rendering

Page images come from the same PyMuPDF page object that produced every stored
coordinate, in the same display space. The frontend therefore needs no
calibration and handles no rotation.

One subtlety: PyMuPDF rounds a pixmap **up** to whole pixels. An 841.68pt page
at scale 2 renders 1684px wide, not 1683.36. Overlays are consequently
positioned as a **fraction of the page box**, never by multiplying a coordinate
by the render scale — the fraction is exact at every zoom level.

## Thresholds

All configurable through the environment; the values used are persisted on each
document as `matching_config`, so a stored extraction can still be explained
after the defaults change.

| setting | default | meaning |
| --- | --- | --- |
| `CELL_WORD_CONTAINMENT_THRESHOLD` | 0.55 | word → cell membership; above 0.5 makes it exclusive |
| `CELL_MATCH_CONTAINMENT_THRESHOLD` | 0.55 | strong-match bar for preferring PyMuPDF text |
| `TEXT_LAYER_MIN_CHARS` | 24 | below this a page is treated as scanned |
| `AZURE_DI_MAX_ATTEMPTS` | 4 | attempts per document, including the first |
| `AZURE_DI_BACKOFF_SECONDS` | 2.0 | backoff base; `Retry-After` overrides |

## Scanned and mixed documents

`has_text_layer` is set per page, so a document with both scanned and digital
pages is handled page by page with no special mode:

| page kind | text | tables |
| --- | --- | --- |
| digital | PyMuPDF | Azure DI structure, text confirmed against PyMuPDF |
| scanned | Azure DI OCR | Azure DI structure and text (`method: none`) |

On a scanned page every cell matches as `none` and keeps Azure's text, which is
the correct outcome: there is no PDF text layer to verify against, and the UI
says so rather than implying the value was confirmed.

## Modules

| module | responsibility |
| --- | --- |
| `extraction/geometry.py` | bbox primitives, rotation, IoU, containment |
| `extraction/pymupdf_extractor.py` | `PdfExtractor` — deterministic PDF data, rendering |
| `extraction/azure_di.py` | `AzureDocumentIntelligenceExtractor`, retries, error mapping |
| `extraction/matcher.py` | `TableMatcher` — word → cell association |
| `extraction/normalizer.py` | `DocumentNormalizer` — coordinate mapping, provenance |
| `extraction/pipeline.py` | `ExtractionPipeline` — orchestration and degradation |
| `extraction/types.py` | the canonical schema |
