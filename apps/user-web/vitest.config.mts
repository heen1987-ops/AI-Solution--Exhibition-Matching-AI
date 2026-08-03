import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Vitest 선택 근거: 이 저장소에 기존 TS 테스트 러너 관행이 없어(루트 tsconfig는
// netlify/**/*.ts만 대상), Next.js/React 생태계 표준으로 자리잡은 Vitest +
// @testing-library/react를 채택한다(다른 apps/* 앱이 생기면 동일 관행을 따를 것을 권장).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    css: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./"),
    },
  },
});
