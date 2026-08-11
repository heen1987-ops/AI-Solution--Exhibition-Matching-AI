"""오브젝트 스토리지 어댑터 - Protocol 인터페이스 + 로컬 파일시스템/인메모리 구현.

Known limitation (최종 보고서에도 명시)
----------------------------------------
docker-compose.yml에는 아직 S3-compatible 오브젝트 스토리지 서비스가 없다(PROJECT_SCOPE.md
"S3-compatible object storage"가 최종 목표 스택으로 명시되어 있지만 이 저장소에는 아직
컨테이너가 없다). 이 모듈은 그 서비스가 준비되기 전까지 쓸 수 있는 로컬 파일시스템 어댑터를
Protocol 뒤에 숨겨 제공한다 - 운영 전환 시 ObjectStorageAdapter를 구현하는 S3 어댑터로
교체하기만 하면 app/services/document/service.py는 변경할 필요가 없다.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Protocol


class StorageKeyError(Exception):
    """스토리지 키가 유효하지 않거나(경로 탈출 시도 등) 대상이 없을 때."""


class ObjectStorageAdapter(Protocol):
    """document_file.storage_key가 가리키는 실제 바이트를 다루는 최소 인터페이스."""

    def put(self, *, key: str, data: bytes) -> None: ...

    def get(self, *, key: str) -> bytes: ...

    def delete(self, *, key: str) -> None: ...

    def exists(self, *, key: str) -> bool: ...


def build_storage_key(*, exhibitor_id: uuid.UUID, document_id: uuid.UUID, file_id: uuid.UUID,
                       extension: str) -> str:
    """저장소 키를 결정적으로 만든다 - 업체별로 네임스페이스를 분리해 둔다(운영 전환 시
    버킷 prefix/IAM 정책을 업체 단위로 나누기 쉽게 하기 위함)."""

    return f"exhibitor/{exhibitor_id}/{document_id}/{file_id}.{extension}"


class LocalFilesystemStorageAdapter:
    """로컬 디스크에 파일을 저장하는 개발/폴백용 어댑터.

    저장 루트 밖으로 벗어나는 키(경로 탈출, 예: "../../etc/passwd")는 거부한다 - storage_key는
    이 서비스가 스스로 생성한 값만 신뢰해야 하지만(build_storage_key), 방어적으로 한 번 더
    검사한다.
    """

    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir).resolve()
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        candidate = (self._base_dir / key).resolve()
        try:
            candidate.relative_to(self._base_dir)
        except ValueError as exc:
            raise StorageKeyError(f"경로 탈출이 감지된 storage_key: {key!r}") from exc
        return candidate

    def put(self, *, key: str, data: bytes) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, *, key: str) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise StorageKeyError(f"storage_key를 찾을 수 없습니다: {key!r}")
        return path.read_bytes()

    def delete(self, *, key: str) -> None:
        path = self._resolve(key)
        path.unlink(missing_ok=True)

    def exists(self, *, key: str) -> bool:
        return self._resolve(key).is_file()


class InMemoryStorageAdapter:
    """테스트 전용 인메모리 어댑터. 디스크/외부 자원에 전혀 접근하지 않는다."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, *, key: str, data: bytes) -> None:
        self._objects[key] = data

    def get(self, *, key: str) -> bytes:
        try:
            return self._objects[key]
        except KeyError as exc:
            raise StorageKeyError(f"storage_key를 찾을 수 없습니다: {key!r}") from exc

    def delete(self, *, key: str) -> None:
        self._objects.pop(key, None)

    def exists(self, *, key: str) -> bool:
        return key in self._objects


def get_local_storage_adapter() -> LocalFilesystemStorageAdapter:
    """app/core/config.py의 DOCUMENT_STORAGE_DIR 설정으로 어댑터를 만든다 (FastAPI Depends용)."""

    from app.core.config import get_settings

    return LocalFilesystemStorageAdapter(get_settings().DOCUMENT_STORAGE_DIR)
