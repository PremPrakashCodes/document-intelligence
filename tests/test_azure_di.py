"""Azure DI: error mapping, retry policy, and SDK flattening."""

import json
import pathlib

import pytest

from extraction.azure_di import (
    AzureDocumentIntelligenceExtractor,
    AzureSpan,
    RetryPolicy,
    _enum_str,
    layout_from_sdk,
    map_azure_error,
)
from extraction.errors import (
    AzureAuthError,
    AzureNotConfiguredError,
    AzureRateLimitError,
    AzureServiceError,
    AzureTimeoutError,
    AzureUnsupportedDocumentError,
)


class FakeResponse:
    def __init__(self, headers=None):
        self.headers = headers or {}


class FakeHttpError(Exception):
    """Shaped like azure.core.exceptions.HttpResponseError."""

    def __init__(self, status_code=None, code=None, message="boom", headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.error = type("E", (), {"code": code})()
        self.response = FakeResponse(headers)


class TestErrorMapping:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (401, AzureAuthError),
            (403, AzureAuthError),
            (429, AzureRateLimitError),
            (408, AzureTimeoutError),
            (504, AzureTimeoutError),
            (400, AzureUnsupportedDocumentError),
            (500, AzureServiceError),
            (503, AzureServiceError),
        ],
    )
    def test_maps_status_codes(self, status, expected):
        assert isinstance(map_azure_error(FakeHttpError(status_code=status)), expected)

    @pytest.mark.parametrize(
        ("status", "retryable"),
        [(401, False), (400, False), (429, True), (500, True), (408, True)],
    )
    def test_retryability_follows_whether_a_retry_could_help(self, status, retryable):
        assert map_azure_error(FakeHttpError(status_code=status)).retryable is retryable

    def test_maps_permanent_service_codes(self):
        err = map_azure_error(FakeHttpError(status_code=500, code="InvalidContent"))
        assert isinstance(err, AzureUnsupportedDocumentError)
        assert err.retryable is False

    def test_reads_retry_after(self):
        err = map_azure_error(FakeHttpError(status_code=429, headers={"Retry-After": "12"}))
        assert err.retry_after == 12.0

    def test_tolerates_an_http_date_retry_after(self):
        err = map_azure_error(
            FakeHttpError(status_code=429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
        )
        assert err.retry_after is None  # falls back to the backoff curve


class TestRetryPolicy:
    def test_retry_after_overrides_the_curve(self):
        assert RetryPolicy().delay_for(1, retry_after=7.0) == 7.0

    def test_retry_after_is_still_capped(self):
        assert RetryPolicy(max_delay_seconds=30).delay_for(1, retry_after=9999) == 30

    def test_delay_stays_within_the_jitter_ceiling(self):
        policy = RetryPolicy(backoff_seconds=2.0)
        for attempt in range(1, 5):
            ceiling = min(2.0 * 2 ** (attempt - 1), policy.max_delay_seconds)
            assert 0.0 <= policy.delay_for(attempt) <= ceiling


class TestAnalyze:
    async def test_unconfigured_client_raises_rather_than_calling_out(self):
        extractor = AzureDocumentIntelligenceExtractor(endpoint="", key="")
        assert extractor.configured is False
        with pytest.raises(AzureNotConfiguredError):
            await extractor.analyze(b"%PDF-")

    async def test_retries_transient_failures_then_succeeds(self, monkeypatch):
        extractor = AzureDocumentIntelligenceExtractor(
            endpoint="https://example.invalid/",
            key="k",
            retry=RetryPolicy(max_attempts=3, backoff_seconds=0.0),
        )
        calls = {"n": 0}

        async def flaky(data):
            calls["n"] += 1
            if calls["n"] < 3:
                raise AzureServiceError("transient")
            return _sdk_result()

        monkeypatch.setattr(extractor, "_analyze_once", flaky)
        layout = await extractor.analyze(b"%PDF-")
        assert calls["n"] == 3
        assert layout.attempts == 3

    async def test_does_not_retry_a_permanent_failure(self, monkeypatch):
        extractor = AzureDocumentIntelligenceExtractor(
            endpoint="https://example.invalid/", key="k",
            retry=RetryPolicy(max_attempts=4, backoff_seconds=0.0),
        )
        calls = {"n": 0}

        async def always_auth_error(data):
            calls["n"] += 1
            raise AzureAuthError("bad key")

        monkeypatch.setattr(extractor, "_analyze_once", always_auth_error)
        with pytest.raises(AzureAuthError):
            await extractor.analyze(b"%PDF-")
        assert calls["n"] == 1

    async def test_gives_up_after_max_attempts(self, monkeypatch):
        extractor = AzureDocumentIntelligenceExtractor(
            endpoint="https://example.invalid/", key="k",
            retry=RetryPolicy(max_attempts=3, backoff_seconds=0.0),
        )
        calls = {"n": 0}

        async def always_fail(data):
            calls["n"] += 1
            raise AzureRateLimitError("429")

        monkeypatch.setattr(extractor, "_analyze_once", always_fail)
        with pytest.raises(AzureRateLimitError):
            await extractor.analyze(b"%PDF-")
        assert calls["n"] == 3


def _sdk_result():
    from azure.ai.documentintelligence.models import AnalyzeResult

    return AnalyzeResult({"content": "", "pages": [], "tables": []})


class TestEnumStr:
    def test_unwraps_an_enum(self):
        import enum

        class Kind(enum.Enum):
            COLUMN_HEADER = "columnHeader"

        assert _enum_str(Kind.COLUMN_HEADER) == "columnHeader"

    def test_passes_a_plain_string_through(self):
        assert _enum_str("content") == "content"

    def test_uses_the_default_for_none(self):
        assert _enum_str(None, "content") == "content"


class TestLayoutFromSdk:
    """Flattening is checked against the recorded live response, so a change in
    the SDK's shape shows up here rather than in production."""

    def test_maps_pages_tables_and_cells(self, sample_layout):
        assert len(sample_layout.pages) == 1
        page = sample_layout.pages[0]
        assert page.unit == "inch"
        assert (round(page.width, 3), round(page.height, 3)) == (11.681, 8.264)
        assert len(page.words) == 602
        assert len(sample_layout.tables) == 2
        assert (sample_layout.tables[0].row_count, sample_layout.tables[0].column_count) == (29, 19)

    def test_unwraps_cell_kind_enums(self, sample_layout):
        kinds = {cell.kind for table in sample_layout.tables for cell in table.cells}
        assert kinds == {"content", "columnHeader"}

    def test_keeps_word_confidence_and_spans(self, sample_layout):
        word = sample_layout.pages[0].words[0]
        assert 0.0 < word.confidence <= 1.0
        assert word.span is not None

    def test_derives_cell_confidence_from_word_spans(self, sample_layout):
        """Azure has no per-cell confidence; it is averaged over the cell's
        words, which is the only honest way to report one."""
        cell = next(c for t in sample_layout.tables for c in t.cells if c.content == "Particulars")
        confidence = sample_layout.cell_confidence(1, cell.spans)
        assert confidence is not None
        assert 0.9 < confidence <= 1.0

    def test_cell_confidence_is_none_without_matching_words(self, sample_layout):
        assert sample_layout.cell_confidence(1, ()) is None
        assert sample_layout.cell_confidence(99, (AzureSpan(0, 5),)) is None


class TestAzureSpan:
    @pytest.mark.parametrize(
        ("other", "overlaps"),
        [((3, 4), True), ((5, 2), False), ((0, 5), True), ((4, 1), True), ((10, 1), False)],
    )
    def test_overlap(self, other, overlaps):
        assert AzureSpan(0, 5).overlaps(AzureSpan(*other)) is overlaps
