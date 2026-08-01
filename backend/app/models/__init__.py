"""도메인 SQLAlchemy 모델 패키지.

각 도메인 에이전트가 자신의 스키마에 해당하는 모듈(profile.py, identity.py, exhibition.py 등)을
이 패키지 아래에 추가한다. 여러 에이전트가 동시에 작업 중이므로 이 __init__.py는 의도적으로
비워 둔다 - 특정 도메인 모듈을 여기서 import하면 다른 에이전트의 동시 작업과 충돌하기 쉽다.

alembic autogenerate가 모든 모델을 인식하게 하려면(수동 작성 마이그레이션에는 필수가 아니지만)
통합 단계에서 backend/alembic/env.py에 다음과 같은 import를 추가해야 한다:

    from app.models import profile  # noqa: F401
    from app.models import identity  # noqa: F401
    ...

이 파일은 그 통합 작업 범위 밖이므로 여기서는 손대지 않는다.
"""
