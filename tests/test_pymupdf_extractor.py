"""PyMuPDF extraction: deterministic, and correct in display space."""

import math

import pymupdf
import pytest

from extraction.errors import EmptyPdfError, EncryptedPdfError, InvalidPdfError
from extraction.geometry import BBox
from extraction.pymupdf_extractor import PdfExtractor


def make_pdf(*, rotation: int = 0, text: str = "Policy Number POL-10234", pages: int = 1) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), text, fontsize=11)
        if rotation:
            page.set_rotation(rotation)
    return doc.tobytes()


class TestOpen:
    def test_rejects_non_pdf_bytes(self, pdf_extractor):
        with pytest.raises(InvalidPdfError) as err:
            pdf_extractor.open(b"this is not a pdf")
        assert err.value.code == "invalid_pdf"

    def test_rejects_empty_input(self, pdf_extractor):
        with pytest.raises(EmptyPdfError):
            pdf_extractor.open(b"")

    def test_rejects_a_pdf_with_no_pages(self, pdf_extractor):
        """Hand-written: PyMuPDF refuses to *save* a zero-page document, but
        such files exist and must be rejected with a typed error rather than
        crashing somewhere downstream."""
        empty = (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF\n"
        )
        with pytest.raises(EmptyPdfError):
            pdf_extractor.open(empty)

    def test_opens_a_pdf_protected_only_against_editing(self, pdf_extractor):
        """An owner password with an empty user password is common in filings
        and must not block extraction."""
        doc = pymupdf.open("pdf", make_pdf())
        data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="")
        opened = pdf_extractor.open(data)
        assert opened.page_count == 1
        opened.close()

    def test_rejects_a_pdf_needing_a_user_password(self, pdf_extractor):
        doc = pymupdf.open("pdf", make_pdf())
        data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="secret")
        with pytest.raises(EncryptedPdfError) as err:
            pdf_extractor.open(data)
        assert err.value.code == "encrypted_pdf"


class TestGeometry:
    @pytest.mark.parametrize(
        ("rotation", "size"),
        [(0, (595.0, 842.0)), (90, (842.0, 595.0)), (180, (595.0, 842.0)), (270, (842.0, 595.0))],
    )
    def test_reports_display_size(self, pdf_extractor, rotation, size):
        doc = pdf_extractor.open(make_pdf(rotation=rotation))
        page = pdf_extractor.extract_page(doc, 0)
        assert (page.geometry.width, page.geometry.height) == size
        assert page.geometry.rotation == rotation
        # The mediabox stays unrotated, so the transform can be retraced.
        assert page.geometry.mediabox == (0.0, 0.0, 595.0, 842.0)
        doc.close()

    @pytest.mark.parametrize("rotation", [0, 90, 180, 270])
    def test_words_land_inside_the_rendered_page(self, pdf_extractor, rotation):
        """The invariant the whole overlay depends on: text coordinates and the
        rendered image share one space, whatever /Rotate says."""
        doc = pdf_extractor.open(make_pdf(rotation=rotation))
        page = pdf_extractor.extract_page(doc, 0)
        assert page.content.words
        for w in page.content.words:
            box = BBox(*w.bbox)
            assert 0 <= box.x0 <= box.x1 <= page.geometry.width
            assert 0 <= box.y0 <= box.y1 <= page.geometry.height
        doc.close()

    def test_rotation_actually_moves_the_text(self, pdf_extractor):
        """Guards against a regression where the transform silently no-ops."""
        upright = pdf_extractor.open(make_pdf(rotation=0))
        rotated = pdf_extractor.open(make_pdf(rotation=90))
        a = pdf_extractor.extract_page(upright, 0).content.words[0].bbox
        b = pdf_extractor.extract_page(rotated, 0).content.words[0].bbox
        assert a != b
        upright.close()
        rotated.close()


class TestContent:
    def test_extracts_words_blocks_and_fonts(self, pdf_extractor):
        doc = pdf_extractor.open(make_pdf())
        page = pdf_extractor.extract_page(doc, 0)
        assert [w.text for w in page.content.words] == ["Policy", "Number", "POL-10234"]
        assert page.content.blocks and page.content.blocks[0].type == "text"
        assert page.content.blocks[0].lines[0].spans[0].font
        assert page.content.fonts[0].name == "Helvetica"
        doc.close()

    def test_extracts_links_images_and_annotations(self, pdf_extractor):
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "hello world", fontsize=11)
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 20))
        pix.set_rect(pix.irect, (255, 0, 0))
        page.insert_image(pymupdf.Rect(400, 90, 440, 110), pixmap=pix)
        page.insert_link(
            {"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 200, 200, 215), "uri": "https://example.com"}
        )
        page.add_text_annot((300, 300), "a note")

        opened = pdf_extractor.open(doc.tobytes())
        extracted = pdf_extractor.extract_page(opened, 0)
        assert extracted.content.images[0].bbox == (400.0, 90.0, 440.0, 110.0)
        assert extracted.content.links[0].uri == "https://example.com"
        assert extracted.content.annotations[0].content == "a note"
        opened.close()

    def test_flags_a_page_with_no_usable_text_layer(self, pdf_extractor):
        """How a scanned page is recognised: too little embedded text to use."""
        doc = pymupdf.open()
        doc.new_page(width=595, height=842)
        opened = pdf_extractor.open(doc.tobytes())
        assert pdf_extractor.extract_page(opened, 0).has_text_layer is False
        opened.close()

    def test_flags_a_page_with_real_text(self, pdf_extractor, sample_pdf_bytes):
        doc = pdf_extractor.open(sample_pdf_bytes)
        assert pdf_extractor.extract_page(doc, 0).has_text_layer is True
        doc.close()

    def test_reads_document_metadata(self, pdf_extractor, sample_pdf_bytes):
        doc = pdf_extractor.open(sample_pdf_bytes)
        metadata = pdf_extractor.metadata(doc)
        assert metadata["producer"].startswith("Document Intelligence")
        assert "" not in metadata.values()  # empty entries are dropped
        doc.close()


class TestDeterminism:
    def test_the_same_bytes_give_byte_identical_output(self, pdf_extractor, sample_pdf_bytes):
        """The property the whole audit trail rests on."""
        first = pdf_extractor.open(sample_pdf_bytes)
        second = pdf_extractor.open(sample_pdf_bytes)
        assert [p.model_dump_json() for p in pdf_extractor.extract_pages(first)] == [
            p.model_dump_json() for p in pdf_extractor.extract_pages(second)
        ]
        first.close()
        second.close()

    def test_sample_page_extracts_expected_shape(self, pdf_extractor, sample_pdf_bytes):
        doc = pdf_extractor.open(sample_pdf_bytes)
        page = pdf_extractor.extract_page(doc, 0)
        assert doc.page_count == 1
        # Landscape A4, born-digital.
        assert page.geometry.width > page.geometry.height
        assert len(page.content.words) == 713
        assert "REVENUE ACCOUNT" in page.content.text
        doc.close()


class TestRender:
    def test_renders_png_at_the_requested_scale(self, pdf_extractor, sample_pdf_bytes):
        doc = pdf_extractor.open(sample_pdf_bytes)
        page = pdf_extractor.extract_page(doc, 0)
        png = pdf_extractor.render_page(doc, 0, scale=2.0)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        # PyMuPDF rounds the pixmap *up* to whole pixels: this landscape page is
        # 841.68pt, so scale 2 gives 1684px rather than 1683.36. The frontend
        # therefore positions overlays as a fraction of the page box rather than
        # by multiplying a coordinate by the nominal scale, which would drift by
        # up to a pixel at the right and bottom edges.
        pixmap = pymupdf.Pixmap(png)
        assert pixmap.width == math.ceil(page.geometry.width * 2)
        assert pixmap.height == math.ceil(page.geometry.height * 2)
        doc.close()

    @pytest.mark.parametrize("rotation", [0, 90])
    def test_render_matches_display_geometry_when_rotated(self, pdf_extractor, rotation):
        doc = pdf_extractor.open(make_pdf(rotation=rotation))
        page = pdf_extractor.extract_page(doc, 0)
        pixmap = pymupdf.Pixmap(pdf_extractor.render_page(doc, 0, scale=1.0))
        assert (pixmap.width, pixmap.height) == (
            math.ceil(page.geometry.width),
            math.ceil(page.geometry.height),
        )
        doc.close()
