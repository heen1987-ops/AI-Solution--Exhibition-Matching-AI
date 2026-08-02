# backend/(FastAPI) 운영 이미지. 빌드 컨텍스트는 저장소 루트여야 한다
# (backend/가 루트의 meet_ai 패키지(src/meet_ai)에 의존하므로 - backend/app/services/matching/*
# 가 "from meet_ai.scoring import ..." 등으로 import한다).
#
# 빌드: docker build -f infra/docker/backend.Dockerfile -t backju-backend .
# (CI: .github/workflows/ci.yml docker-build 잡)

FROM python:3.12-slim AS base

WORKDIR /srv

# 루트 meet_ai 패키지 먼저 설치 (backend가 이를 import에 의존, ASSUMPTION-001/005 참고 -
# 이 두 패키지는 물리적으로 분리된 채 유지된다).
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir -e .

# backend 패키지 설치
COPY backend/pyproject.toml backend/README.md ./backend/
COPY backend/app ./backend/app
RUN pip install --no-cache-dir -e ./backend

EXPOSE 8000

WORKDIR /srv/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
