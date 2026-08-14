import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  // Vite 8/vitest 4 default to an oxc-based transform that reads tsconfig.json's
  // `compilerOptions.jsx` directly - here that's "preserve" (Next.js's own SWC does the
  // real JSX transform at build time, tsc never emits). oxc's transform can't handle
  // "preserve" and fails every .tsx test file with "Unexpected JSX expression". Disabling
  // oxc falls back to the legacy esbuild-based transform, which respects the `esbuild.jsx`
  // override below regardless of tsconfig - this is a real, pre-existing baseline defect in
  // this repo's pinned toolchain (vitest 4.1.10 -> vite 8.2.0), not something the port
  // introduced; apps/kiosk's own pre-merge test (tests/kiosk-ui.test.tsx) fails identically
  // without this fix.
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
  },
});
