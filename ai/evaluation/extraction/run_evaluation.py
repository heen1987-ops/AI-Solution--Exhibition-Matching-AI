"""독립 실행형 평가 리포트.

    python -m ai.evaluation.extraction.run_evaluation

저장소 루트에서 실행한다(``ai/tests/conftest.py``와 같은 이유로, 이 모듈이 직접
``sys.path``를 보정한다 - 다른 진입점 없이 단독 스크립트로도 동작해야 하므로).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ai.evaluation.extraction.scenarios import SCENARIOS, run_scenario


def main() -> int:
    failures: list[tuple[str, Exception]] = []
    for scenario in SCENARIOS:
        try:
            run_scenario(scenario)
        except AssertionError as exc:
            failures.append((scenario.id, exc))
        else:
            print(f"PASS  {scenario.id:40s} {scenario.description}")

    for scenario_id, exc in failures:
        print(f"FAIL  {scenario_id:40s} {exc}")

    total = len(SCENARIOS)
    passed = total - len(failures)
    print(f"\n{passed}/{total} scenarios passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
