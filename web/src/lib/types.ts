/**
 * Wire types for the documents API.
 *
 * These mirror `src/api/schemas.py`. Every bounding box is `[x0, y0, x1, y1]`
 * in **page display space**: PDF points, top-left origin, page rotation already
 * applied. The rendered page image is the same space scaled up, so an overlay
 * is positioned by dividing a box by the page width and height - never by
 * multiplying by the render scale, which drifts because PyMuPDF rounds pixmap
 * dimensions up to whole pixels.
 */

export type BBox = [number, number, number, number]

/** Which extractor a value came from. */
export type Source = 'pymupdf' | 'azure_di'

/** How a cell's text was resolved against the PDF text layer. */
export type MatchMethod = 'exact' | 'spatial' | 'weak' | 'none'

export type DocumentStatus =
  | 'pending'
  | 'processing'
  | 'completed'
  /** PyMuPDF succeeded, Azure DI did not - text is present, tables are not. */
  | 'partial'
  | 'failed'

export interface Paginated<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface ExtractorRun {
  completed: boolean
  version: string | null
  model: string | null
  duration_ms: number | null
  attempts: number
  error: { code: string; message: string; retryable?: boolean } | null
}

export interface MatchingStats {
  total_cells: number
  /** Cells with no text from either source; excluded from `match_rate`. */
  empty_cells: number
  content_cells: number
  matched_cells: number
  exact_matches: number
  spatial_matches: number
  unmatched_cells: number
  match_rate: number
}

export interface Extraction {
  pymupdf: ExtractorRun
  azure_di: ExtractorRun
  matching: MatchingStats
  /** The thresholds this document was extracted with. */
  config: Record<string, number> | null
  extracted_at: string | null
}

export interface DocumentSummary {
  id: string
  filename: string
  mime_type: string
  file_size: number
  sha256: string
  page_count: number
  status: DocumentStatus
  created_at: string
  updated_at: string
}

export interface DocumentDetail extends DocumentSummary {
  metadata: Record<string, string>
  is_encrypted: boolean
  extraction: Extraction | null
  error: { code: string; message: string } | null
  table_count: number
}

export interface PageGeometry {
  width: number
  height: number
  rotation: number
  mediabox: BBox
}

export interface PageSummary {
  page_number: number
  geometry: PageGeometry
  has_text_layer: boolean
  text_length: number
  table_count: number
}

export interface PageWord {
  text: string
  bbox: BBox
  block: number
  line: number
  word: number
}

/** A run of characters sharing one font, size, and style. */
export interface PageSpan {
  text: string
  bbox: BBox
  font: string
  size: number
  /** PyMuPDF's packed style bits - see `SPAN_FLAG` in `pageFlow.ts`. */
  flags: number
  color: number
}

export interface PageLine {
  bbox: BBox
  /** Writing direction as a unit vector; `[1, 0]` is normal left-to-right. */
  direction: [number, number]
  spans: PageSpan[]
}

/** A text or image block, in PyMuPDF's own block order. */
export interface PageBlock {
  number: number
  type: 'text' | 'image'
  bbox: BBox
  lines?: PageLine[]
}

export interface PageDetail {
  page_number: number
  geometry: PageGeometry
  has_text_layer: boolean
  text: string
  content: { words?: PageWord[]; blocks?: PageBlock[]; [key: string]: unknown }
  table_ids: string[]
}

/** Provenance for one cell's text. */
export interface TextSource {
  source: Source
  matched: boolean
  method: MatchMethod
  /** Fraction of the matched words inside the cell - the decision variable. */
  containment: number
  /** Diagnostic only; scales with cell padding, so it never gates a match. */
  iou: number
  /** The exact text location in the PDF, for highlighting. */
  bbox: BBox | null
  word_count: number
}

export interface TableCell {
  row: number
  column: number
  row_span: number
  column_span: number
  kind: string
  /** The chosen value. */
  text: string
  azure_text: string
  pymupdf_text: string | null
  bbox: BBox
  confidence: number | null
  text_source: TextSource
}

export interface TableSummary {
  id: string
  page_number: number
  source: Source
  bbox: BBox
  row_count: number
  column_count: number
  caption: string | null
  confidence: number | null
  continues_table_id: string | null
  cell_count: number
}

export interface TableDetail extends TableSummary {
  cells: TableCell[]
}

export interface UploadResponse {
  id: string
  filename: string
  status: DocumentStatus
  job_id: string | null
}
