"""PDF extraction: PyMuPDF primitives, Azure DI structure, one canonical document."""

from extraction.azure_di import AzureDocumentIntelligenceExtractor, AzureLayout, LayoutExtractor
from extraction.matcher import TableMatcher
from extraction.normalizer import DocumentNormalizer
from extraction.pipeline import ExtractionPipeline, build_pipeline
from extraction.pymupdf_extractor import PdfExtractor
from extraction.types import CanonicalDocument, DocumentStatus, Page, Source, Table, TableCell

__all__ = [
    "AzureDocumentIntelligenceExtractor",
    "AzureLayout",
    "CanonicalDocument",
    "DocumentNormalizer",
    "DocumentStatus",
    "ExtractionPipeline",
    "LayoutExtractor",
    "Page",
    "PdfExtractor",
    "Source",
    "Table",
    "TableCell",
    "TableMatcher",
    "build_pipeline",
]
