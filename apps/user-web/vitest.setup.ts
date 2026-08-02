import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import "@testing-library/jest-dom/vitest";

// vitest.config.mts에서 test.globals를 켜지 않았으므로(암묵적 전역 주입을 피하려는
// 선택), @testing-library/react의 자동 cleanup이 afterEach를 찾지 못해 동작하지
// 않는다 - 각 테스트 사이 DOM이 누적되는 것을 막기 위해 명시적으로 등록한다.
afterEach(() => {
  cleanup();
});
