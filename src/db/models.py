"""Relational model for extracted documents.

Shape follows the read paths the frontend actually uses. Tables and cells are
rows rather than a blob on the document, because the API pages over them and
the table viewer fetches one table at a time; page *content* - blocks, words,
spans - stays as JSON on the page row, since it is only ever read whole.

`JSON().with_variant(JSONB, "postgresql")` gives Postgres real JSONB (indexable,
binary) while letting the test suite run the identical models on SQLite.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# One alias so every JSON column makes the same choice.
JsonColumn = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), default="application/pdf", nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    # Content hash of the original bytes: the identity of the *file*, as
    # opposed to the identity of this extraction run.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Key in the blob store; see storage.document_key.
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)

    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)

    # PDF /Info dictionary.
    doc_metadata: Mapped[dict] = mapped_column("metadata", JsonColumn, default=dict, nullable=False)
    is_encrypted: Mapped[bool] = mapped_column(Integer, default=0, nullable=False)

    # One `ExtractorRun` each, plus matching stats and the thresholds used.
    # Stored whole: they are written once and always read together.
    pymupdf_run: Mapped[dict | None] = mapped_column(JsonColumn, nullable=True)
    azure_run: Mapped[dict | None] = mapped_column(JsonColumn, nullable=True)
    matching: Mapped[dict | None] = mapped_column(JsonColumn, nullable=True)
    matching_config: Mapped[dict | None] = mapped_column(JsonColumn, nullable=True)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set only when extraction failed outright.
    error: Mapped[dict | None] = mapped_column(JsonColumn, nullable=True)

    pages: Mapped[list[DocumentPage]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentPage.page_number",
    )
    tables: Mapped[list[DocumentTable]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentTable.position",
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number", name="uq_page_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Display-space geometry; see extraction.geometry.
    width: Mapped[float] = mapped_column(Float, nullable=False)
    height: Mapped[float] = mapped_column(Float, nullable=False)
    rotation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mediabox: Mapped[list] = mapped_column(JsonColumn, default=list, nullable=False)

    has_text_layer: Mapped[bool] = mapped_column(Integer, default=1, nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # blocks / words / images / links / annotations / fonts, read as a unit.
    content: Mapped[dict] = mapped_column(JsonColumn, default=dict, nullable=False)

    document: Mapped[Document] = relationship(back_populates="pages")


class DocumentTable(Base):
    __tablename__ = "document_tables"
    __table_args__ = (
        UniqueConstraint("document_id", "table_id", name="uq_table_id"),
        Index("ix_tables_document_page", "document_id", "page_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Public id, stable per document: "table_1", "table_2", ...
    table_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Azure's ordering, preserved so listings are reproducible.
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="azure_di", nullable=False)
    bbox: Mapped[list] = mapped_column(JsonColumn, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    continues_table_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    document: Mapped[Document] = relationship(back_populates="tables")
    cells: Mapped[list[DocumentTableCell]] = relationship(
        back_populates="table",
        cascade="all, delete-orphan",
        order_by="(DocumentTableCell.row, DocumentTableCell.column)",
    )


class DocumentTableCell(Base):
    __tablename__ = "document_table_cells"
    __table_args__ = (
        Index("ix_cells_table_position", "table_pk", "row", "column"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_pk: Mapped[int] = mapped_column(
        ForeignKey("document_tables.id", ondelete="CASCADE"), nullable=False, index=True
    )

    row: Mapped[int] = mapped_column(Integer, nullable=False)
    column: Mapped[int] = mapped_column(Integer, nullable=False)
    row_span: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    column_span: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="content", nullable=False)

    # The chosen value, plus both inputs. Keeping all three is what makes a
    # cell auditable: the UI can always show what each source said.
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    azure_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pymupdf_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    bbox: Mapped[list] = mapped_column(JsonColumn, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The full TextSource record: source, matched, method, containment, iou,
    # bbox, word_count.
    text_source: Mapped[dict] = mapped_column(JsonColumn, default=dict, nullable=False)

    table: Mapped[DocumentTable] = relationship(back_populates="cells")
