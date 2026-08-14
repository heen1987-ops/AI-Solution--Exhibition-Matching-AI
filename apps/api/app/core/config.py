"""애플리케이션 설정.

pydantic-settings의 BaseSettings로 환경변수와 .env 파일을 읽는다.
값은 지연 로딩되지 않지만(Settings 인스턴스 생성 시 즉시 읽힘), 이 모듈을 임포트하는 것 자체는
실제 DB/Redis 연결을 만들지 않는다 - 연결은 app/db/session.py에서 요청 시점에 이루어진다.

사용법:
    from app.core.config import get_settings
    settings = get_settings()
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SEARCH_EMBEDDING_MODEL_VERSION_ID_V1 = UUID("5f2fe7ac-74d7-59c9-85d3-6b5faf2f7a4e")
SEARCH_EMBEDDING_MODEL_CONFIG_HASH_V1 = (
    "42668df981d3117c82428759a153b3abf6bb94bf6bca4affd9660b225699ffa5"
)
SEARCH_EMBEDDING_BASE_URL_V1 = "https://api.openai.com/v1"


class Settings(BaseSettings):
    """환경변수 기반 전역 설정.

    필드명은 대문자 환경변수와 1:1로 매핑된다 (예: DATABASE_URL -> DATABASE_URL).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # --- 앱 메타 ---
    PROJECT_NAME: str = "Backju AI Matching Service"
    ENV: str = Field(default="local", description="local, dev, staging, production 등")
    DEBUG: bool = Field(default=True)

    # --- API ---
    # docs/frontend-backend-ai-interface-spec.md 4.1 기본 규격: 기본 경로 /api/v1
    API_V1_PREFIX: str = "/api/v1"

    # --- 데이터베이스 (SQLAlchemy 2.0 async, asyncpg 드라이버) ---
    # 형식 예: postgresql+asyncpg://user:password@localhost:5432/backju
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://backju:backju@localhost:5432/backju",
    )
    DATABASE_ECHO: bool = Field(
        default=False, description="SQLAlchemy SQL 로그 출력 여부"
    )
    DATABASE_POOL_SIZE: int = Field(default=5)
    DATABASE_MAX_OVERFLOW: int = Field(default=10)

    # --- Redis ---
    # 세션, 속도 제한, 추천 캐시, 부스상태 캐시 (db-erd-table-spec.md 3절)
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # --- CORS ---
    # 개발 환경에서는 전체 허용(main.py 참고). 운영 환경은 콤마로 구분된 origin 목록을 지정한다.
    CORS_ORIGINS: str = Field(
        default="*", description="콤마(,)로 구분된 허용 origin 목록, 기본값 전체 허용"
    )

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _validate_cors_origins(cls, v: str) -> str:
        return v.strip() if v else "*"

    @property
    def cors_origins_list(self) -> list[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [
            origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()
        ]

    # --- 보안 (다음 단계 에이전트가 인증 구현 시 사용) ---
    SECRET_KEY: str = Field(
        default="CHANGE_ME_INSECURE_DEFAULT_FOR_LOCAL_DEV_ONLY",
        description="세션 서명, HMAC 등에 사용하는 비밀키. 운영 환경에서는 반드시 .env로 재정의한다.",
    )
    SITE_CONTEXT_SECRET: str | None = Field(
        default=None,
        description="사이트 BFF 사용자 컨텍스트 서명 전용 비밀키",
    )

    @property
    def site_context_secret(self) -> str:
        return self.SITE_CONTEXT_SECRET or self.SECRET_KEY

    # --- Authentication (CONTRACT-006) ---
    AUTH_TOKEN_PEPPER: SecretStr | None = Field(default=None, repr=False)
    AUTH_ENCRYPTION_KEY_B64: SecretStr | None = Field(default=None, repr=False)
    AUTH_SESSION_COOKIE_NAME: str = "__Host-meet_ai_session"
    AUTH_SESSION_ABSOLUTE_SECONDS: int = Field(default=43_200, ge=900, le=86_400)
    AUTH_GUEST_SESSION_TTL_SECONDS: int = Field(default=86_400, ge=900, le=604_800)
    AUTH_SESSION_IDLE_USER_SECONDS: int = Field(default=3_600, ge=300, le=14_400)
    AUTH_SESSION_IDLE_ADMIN_SECONDS: int = Field(default=1_800, ge=300, le=7_200)
    AUTH_MAGIC_LINK_TTL_SECONDS: int = Field(default=900, ge=60, le=900)
    AUTH_LINK_RATE_WINDOW_SECONDS: int = Field(default=300, ge=60, le=3_600)
    AUTH_LINK_RATE_TOKEN_LIMIT: int = Field(default=5, ge=1, le=100)
    AUTH_LINK_RATE_ACCOUNT_LIMIT: int = Field(default=10, ge=1, le=100)
    AUTH_LINK_RATE_NETWORK_LIMIT: int = Field(default=300, ge=1, le=10_000)
    AUTH_MFA_CHALLENGE_TTL_SECONDS: int = Field(default=300, ge=60, le=600)
    AUTH_MFA_FRESHNESS_SECONDS: int = Field(default=900, ge=60, le=1_800)
    AUTH_WEBAUTHN_RP_ID: str = "localhost"
    AUTH_WEBAUTHN_RP_NAME: str = "Meet AI"
    AUTH_WEBAUTHN_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
    AUTH_BROWSER_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
    AUTH_JWT_ISSUER: str = "meet-ai"
    AUTH_JWT_AUDIENCE: str = "meet-ai-api"
    AUTH_JWT_PUBLIC_KEY_PEM: SecretStr | None = Field(default=None, repr=False)
    SERVICE_MINIMUM_AGE: int = Field(default=19, ge=0, le=120)

    @property
    def auth_token_pepper(self) -> bytes:
        configured = self.AUTH_TOKEN_PEPPER
        value = configured.get_secret_value() if configured else self.SECRET_KEY
        return value.encode("utf-8")

    @property
    def auth_encryption_key(self) -> bytes:
        configured = self.AUTH_ENCRYPTION_KEY_B64
        if configured:
            try:
                key = base64.urlsafe_b64decode(configured.get_secret_value())
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    "AUTH_ENCRYPTION_KEY_B64 must be URL-safe base64"
                ) from exc
            if len(key) != 32:
                raise ValueError("AUTH_ENCRYPTION_KEY_B64 must decode to 32 bytes")
            return key
        return hashlib.sha256(self.SECRET_KEY.encode("utf-8")).digest()

    @property
    def auth_webauthn_origins(self) -> list[str]:
        return [
            item.strip()
            for item in self.AUTH_WEBAUTHN_ORIGINS.split(",")
            if item.strip()
        ]

    @property
    def auth_browser_origins(self) -> list[str]:
        return [
            item.strip()
            for item in self.AUTH_BROWSER_ORIGINS.split(",")
            if item.strip()
        ]

    # --- 공개 검색·익명 키오스크 ---
    SEARCH_SESSION_TTL_SECONDS: int = Field(default=900, ge=60, le=3600)
    SEARCH_EMBEDDING_ENABLED: bool = False
    SEARCH_EMBEDDING_PROVIDER: Literal["OPENAI"] = "OPENAI"
    SEARCH_EMBEDDING_MODEL_VERSION_ID: UUID = SEARCH_EMBEDDING_MODEL_VERSION_ID_V1
    SEARCH_EMBEDDING_MODEL: Literal["text-embedding-3-small"] = "text-embedding-3-small"
    SEARCH_EMBEDDING_DIMENSIONS: Literal[512] = 512
    SEARCH_EMBEDDING_MIN_RELEVANCE: Literal[0.35] = 0.35
    SEARCH_EMBEDDING_TOP_K: int = Field(default=80, ge=10, le=200)
    SEARCH_EMBEDDING_TIMEOUT_SECONDS: float = Field(default=3.0, ge=0.5, le=10.0)
    SEARCH_EMBEDDING_BASE_URL: str = SEARCH_EMBEDDING_BASE_URL_V1
    SEARCH_EMBEDDING_OPENAI_API_KEY: SecretStr | None = Field(
        default=None,
        repr=False,
    )

    @field_validator("SEARCH_EMBEDDING_MODEL_VERSION_ID")
    @classmethod
    def _validate_embedding_model_version_id(cls, value: UUID) -> UUID:
        if value != SEARCH_EMBEDDING_MODEL_VERSION_ID_V1:
            raise ValueError("search embedding model version requires a new contract")
        return value

    @field_validator("SEARCH_EMBEDDING_BASE_URL")
    @classmethod
    def _validate_embedding_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if normalized != SEARCH_EMBEDDING_BASE_URL_V1:
            raise ValueError(
                "search embedding base URL requires a new provider contract"
            )
        return normalized

    KIOSK_EVENT_ID: UUID = UUID("11111111-1111-4111-8111-111111111111")
    KIOSK_EVENT_NAME: str = "2026 대한민국 백주대간"
    KIOSK_DEFAULT_LANGUAGE: Literal["ko", "en", "ja", "zh"] = "ko"
    KIOSK_SUPPORTED_LANGUAGES: str = "ko,en,ja,zh"
    KIOSK_ZONE_ID: str | None = "entrance-a"
    KIOSK_SESSION_TIMEOUT_SECONDS: int = Field(default=90, ge=60, le=120)
    KIOSK_QR_EXPIRATION_MINUTES: int = Field(default=30, ge=1, le=60)
    KIOSK_PRIMARY_COLOR: str = "#7A2432"
    GUEST_WEB_BASE_URL: str = "http://localhost:3000"

    # --- 참가업체 문서 업로드 (BACKEND-DOCUMENT, WAVE 2D) ---
    # app/services/document/storage.py가 이 세 값을 참조한다. object storage 서비스가
    # 아직 없어 로컬 파일시스템 어댑터의 저장 루트를 DOCUMENT_STORAGE_DIR로 대체한다.
    DOCUMENT_STORAGE_DIR: str = Field(default="./var/document-storage")
    DOCUMENT_MAX_UPLOAD_BYTES: int = Field(
        default=25 * 1024 * 1024, description="문서 업로드 최대 크기 (기본 25MB)"
    )
    DOCUMENT_DOWNLOAD_TOKEN_TTL_SECONDS: int = Field(
        default=300, description="다운로드 토큰(서명된 URL 대체) 유효시간"
    )

    @property
    def kiosk_supported_languages(self) -> list[Literal["ko", "en", "ja", "zh"]]:
        allowed = {"ko", "en", "ja", "zh"}
        values = [
            value.strip()
            for value in self.KIOSK_SUPPORTED_LANGUAGES.split(",")
            if value.strip() in allowed
        ]
        return values or ["ko"]  # type: ignore[return-value]

    @model_validator(mode="after")
    def _production_security_must_fail_closed(self) -> Settings:
        embedding_secret = self.SEARCH_EMBEDDING_OPENAI_API_KEY
        if self.SEARCH_EMBEDDING_ENABLED and (
            embedding_secret is None or not embedding_secret.get_secret_value().strip()
        ):
            raise ValueError(
                "SEARCH_EMBEDDING_OPENAI_API_KEY is required when semantic search is enabled"
            )
        if self.ENV.lower() in {"staging", "production"}:
            if self.SECRET_KEY == "CHANGE_ME_INSECURE_DEFAULT_FOR_LOCAL_DEV_ONLY":
                raise ValueError(
                    "SECRET_KEY must be configured outside local development"
                )
            if not self.SITE_CONTEXT_SECRET:
                raise ValueError("SITE_CONTEXT_SECRET must be configured in deployment")
            if not self.AUTH_TOKEN_PEPPER:
                raise ValueError("AUTH_TOKEN_PEPPER must be configured in deployment")
            if not self.AUTH_ENCRYPTION_KEY_B64:
                raise ValueError(
                    "AUTH_ENCRYPTION_KEY_B64 must be configured in deployment"
                )
            origin_sets = {
                "AUTH_BROWSER_ORIGINS": self.auth_browser_origins,
                "AUTH_WEBAUTHN_ORIGINS": self.auth_webauthn_origins,
            }
            for setting_name, origins in origin_sets.items():
                if not origins or any(
                    not origin.startswith("https://") for origin in origins
                ):
                    raise ValueError(f"{setting_name} must contain only HTTPS origins")
            if self.AUTH_WEBAUTHN_RP_ID == "localhost":
                raise ValueError("AUTH_WEBAUTHN_RP_ID must be configured in deployment")
        return self


@lru_cache
def get_settings() -> Settings:
    """프로세스 전체에서 재사용하는 Settings 싱글턴.

    FastAPI Depends(get_settings)로 주입하거나 직접 호출해서 사용한다.
    lru_cache 덕분에 Settings()는 최초 호출 시 한 번만 생성된다.
    """

    return Settings()
