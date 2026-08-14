import path from "node:path";

import { defineConfig } from "vitest/config";

/**
 * `apps/kiosk/vitest.config.ts`와 동일한 최소 구성. include는 두 계보의 테스트를 모두
 * 살리기 위해 MERGE했다 - main 쪽 `lib/*.test.ts`(7개)와 워크트리 쪽
 * `features/**\/__tests__/**`·`tests/**` 계열을 하나로 합치지 않으면 어느 한쪽이 파일을
 * 복사해오는 순간 조용히 실행에서 빠진다.
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
    // lib/customer-copy.test.ts overrides this back to "node" via a `@vitest-environment`
    // docblock - it reads source files with real Node file:// URL semantics
    // (fileURLToPath) that jsdom's environment does not reproduce.
    setupFiles: ["./tests/setup.ts"],
    clearMocks: true,
    include: [
      "lib/**/*.test.{ts,tsx}",
      "**/__tests__/**/*.test.{ts,tsx}",
      "tests/**/*.test.{ts,tsx}",
    ],
  },
});
