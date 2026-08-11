import path from "node:path";

import { defineConfig } from "vitest/config";

/**
 * `apps/kiosk/vitest.config.ts`와 동일한 골격. include는 main 쪽 `lib/*.test.ts`(1개,
 * auth-state.test.ts)와 WAVE 2C/2D/2E가 들여온 `features/**\/*.test.{ts,tsx}` 계열을 모두
 * 살리도록 MERGE했다 - 워크트리 쪽 config를 그대로 복사하면 include가
 * `features/**`로만 좁혀져 있어 main의 기존 테스트가 조용히 실행에서 빠진다.
 */
export default defineConfig({
  // apps/kiosk/vitest.config.ts 참고 - Vite 8/vitest 4가 기본으로 쓰는 oxc 변환은
  // tsconfig.json의 jsx: "preserve"(Next.js 자체 SWC가 실제 변환을 담당하므로 tsc는
  // emit하지 않는다)를 못 다뤄 모든 .tsx 테스트가 "Unexpected JSX expression"으로
  // 실패한다 - 포팅과 무관한 이 저장소 고정 툴체인의 사전 결함이다. oxc를 끄면 아래
  // esbuild.jsx 오버라이드가 다시 적용되는 예전 esbuild 변환으로 되돌아간다.
  oxc: false,
  esbuild: {
    jsx: "automatic",
    jsxImportSource: "react",
  },
  resolve: {
    alias: { "@": path.resolve(__dirname) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    clearMocks: true,
    include: [
      "lib/**/*.test.{ts,tsx}",
      "features/**/*.test.{ts,tsx}",
      "**/__tests__/**/*.test.{ts,tsx}",
      "tests/**/*.test.{ts,tsx}",
    ],
  },
});
