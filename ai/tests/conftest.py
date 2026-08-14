"""ai/tests 전용 pytest 부트스트랩.

이 저장소는 여러 pyproject.toml(루트 meet-ai, apps/api backju-backend)이 공존하는 모노레포라
루트 pytest 설정(testpaths=["tests"])이 ai/tests를 자동으로 잡지 못한다. ai/tests를 단독으로
실행할 때도(``pytest ai/tests``) `import ai...`가 항상 되도록, 이 저장소 루트를 sys.path 맨
앞에 넣어준다 - 다른 트랙의 공유 설정 파일(pyproject.toml 등)을 건드리지 않고 ai/** 안에서만
해결한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
