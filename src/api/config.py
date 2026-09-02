from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Tracepaper API"
    debug: bool = False

    # Comma-separated list of origins allowed to call the API from a browser.
    cors_origins: str = "http://localhost:5173"

    # --- Azure Document Intelligence ---
    azure_di_endpoint: str = ""
    azure_di_key: str = ""
    # prebuilt-layout is the table/structure model; prebuilt-read is OCR only.
    azure_di_model: str = "prebuilt-layout"
    # Seconds to wait for one analyse operation to finish before giving up.
    azure_di_timeout: float = 300.0
    # Attempts per document, including the first. Only transient failures retry.
    azure_di_max_attempts: int = 4
    # Exponential backoff base; delay is backoff * 2**(attempt-1), plus jitter,
    # unless the service sends a Retry-After header (which always wins).
    azure_di_backoff_seconds: float = 2.0

    # --- Extraction tuning ---
    # A page with fewer than this many extractable characters is treated as
    # scanned, so its text is expected to come from Azure DI's OCR instead.
    text_layer_min_chars: int = 24
    # Fraction of a PyMuPDF word's area that must fall inside an Azure DI cell
    # for the word to be considered part of that cell.
    cell_word_containment_threshold: float = 0.55
    # Fraction of the matched words' union that must lie inside the cell for
    # the match to count as strong and PyMuPDF text to be preferred. Equal to
    # the word threshold by default: membership above 0.5 is already an
    # exclusive assignment, so a stricter bar here only rejects correct text.
    cell_match_containment_threshold: float = 0.55
    # Rendering scale bounds for the page-image endpoint (1.0 == 72 dpi).
    render_min_scale: float = 0.5
    render_max_scale: float = 6.0
    # Largest PDF accepted by the upload endpoint.
    max_upload_bytes: int = 64 * 1024 * 1024

    database_url: str = "postgresql://postgres:password@localhost:5432/postgres"

    # Postgres schema BullMQ owns; it replaces the Redis key prefix.
    queue_schema: str = "bullmq"
    # Jobs a single worker process runs at a time.
    queue_concurrency: int = 4

    # --- Cloudflare R2 (S3-compatible) ---
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "drive"
    # Overrides the account-derived endpoint; useful for MinIO or tests.
    r2_endpoint_url: str = ""

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        """`database_url` with the psycopg3 async driver SQLAlchemy needs.

        The plain `postgresql://` form in .env is what psycopg and BullMQ want;
        SQLAlchemy needs the driver spelled out to pick the async dialect.
        """
        url = self.database_url
        if url.startswith("postgresql+"):
            return url
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url[len("postgresql://") :]
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url[len("postgres://") :]
        return url

    @property
    def r2_endpoint(self) -> str:
        return self.r2_endpoint_url or f"https://{self.r2_account_id}.r2.cloudflarestorage.com"

    @property
    def azure_di_configured(self) -> bool:
        return bool(self.azure_di_endpoint and self.azure_di_key)

    @property
    def r2_configured(self) -> bool:
        return bool(self.r2_access_key_id and self.r2_secret_access_key and self.r2_bucket_name)


@lru_cache
def get_settings() -> Settings:
    return Settings()
