from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./insaf_dastak.db"
    cookie_secure: bool = False
    session_days: int = 7
    max_failed_logins: int = 5
    lock_minutes: int = 15
    overdue_days: int = 7
    upload_dir: str = "./uploads"
    max_upload_mb: int = 5
    max_files_per_case: int = 10
    chat_hourly_limit: int = 60
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 300
    retention_days: int = 365
    rag_embedder: str = "local"  # local (offline, lafzon par) | gemini (matlab par, API)
    embed_model: str = "gemini-embedding-001"
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_timeout_seconds: float = 10
    rag_top_k: int = 4
    rag_min_score: float = -1.0  # -1 = khud (embedder ke hisaab se)
    rag_chunk_chars: int = 900
    rag_chunk_overlap: int = 120
    rag_max_pdf_mb: int = 10
    rag_max_pages: int = 200
    rag_use_llm: bool = True
    rag_hourly_limit: int = 30
    tesseract_cmd: str = ""
    ocr_lang: str = "eng"
    login_per_minute_ip: int = 20
    signup_per_hour_ip: int = 20
    trusted_origins: str = ""
    slot_min_minutes: int = 15
    slot_max_minutes: int = 240
    slot_max_days_ahead: int = 60
    ai_enabled: bool = False
    # Legacy fallback sirf tests/local ke liye. Asli keys admin panel se DB mein encrypt ho kar aati hain.
    ai_api_key: str = ""
    ai_model: str = "gemini-3.8-flash"
    ai_tier: str = "free"  # free | paid
    ai_timeout_seconds: int = 60
    ai_hourly_limit: int = 10
    # DB mein save AI keys isi secret se derive kiye gaye Fernet key se encrypt hoti hain.
    ai_key_secret: str = "dev-only-change-this-ai-key-secret"


settings = Settings()
