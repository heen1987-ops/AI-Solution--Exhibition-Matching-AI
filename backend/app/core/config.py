"""애플리케이션 설정.

pydantic-settings의 BaseSettings로 환경변수와 .env 파일을 읽는다.
값은 지연 로딩되지 않지만(Settings 인스턴스 생성 시 즉시 읽힘), 이 모듈을 임포트하는 것 자체는
실제 DB/Redis 연결을 만들지 않는다 - 연결은 app/db/session.py에서 요청 시점에 이루어진다.

사용법:
    from app.core.config import get_settings
    settings = get_settings()
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    DATABASE_ECHO: bool = Field(default=False, description="SQLAlchemy SQL 로그 출력 여부")
    DATABASE_POOL_SIZE: int = Field(default=5)
    DATABASE_MAX_OVERFLOW: int = Field(default=10)

    # --- Redis ---
    # 세션, 속도 제한, 추천 캐시, 부스상태 캐시 (db-erd-table-spec.md 3절)
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # --- S3 호환 Object Storage (로컬은 docker-compose.yml의 MinIO) ---
    # 업체자료 원본 저장(ai.source_document, C-2 문서)에 사용 예정 - 이번 Wave는 연결
    # 설정과 /health/ready 도달성 체크만 다루고, 실제 업로드 로직은 없다.
    S3_ENDPOINT: str = Field(default="http://localhost:9000")
    S3_BUCKET: str = Field(default="backju-dev")
    S3_ACCESS_KEY: str = Field(default="minioadmin")
    S3_SECRET_KEY: str = Field(default="minioadmin")

    # /health/ready에서 MinIO(S3) 장애를 전체 실패로 처리할지 여부. 기본값 false =
    # MinIO 장애는 checks.s3="warning"으로만 보고하고 PostgreSQL/Redis만 정상이면
    # 전체 status는 "degraded"를 유지한다(완전 실패로 보지 않는다).
    READY_CHECK_FAILS_ON_S3_DOWN: bool = Field(default=False)

    # --- CORS ---
    # 개발 환경에서는 전체 허용(main.py 참고). 운영 환경은 콤마로 구분된 origin 목록을 지정한다.
    CORS_ORIGINS: str = Field(default="*", description="콤마(,)로 구분된 허용 origin 목록, 기본값 전체 허용")

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _validate_cors_origins(cls, v: str) -> str:
        return v.strip() if v else "*"

    @property
    def cors_origins_list(self) -> list[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    # --- 보안 (다음 단계 에이전트가 인증 구현 시 사용) ---
    SECRET_KEY: str = Field(
        default="CHANGE_ME_INSECURE_DEFAULT_FOR_LOCAL_DEV_ONLY",
        description="세션 서명, HMAC 등에 사용하는 비밀키. 운영 환경에서는 반드시 .env로 재정의한다.",
    )


@lru_cache
def get_settings() -> Settings:
    """프로세스 전체에서 재사용하는 Settings 싱글턴.

    FastAPI Depends(get_settings)로 주입하거나 직접 호출해서 사용한다.
    lru_cache 덕분에 Settings()는 최초 호출 시 한 번만 생성된다.
    """

    return Settings()
