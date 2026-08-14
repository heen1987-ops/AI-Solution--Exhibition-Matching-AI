import type { Config } from "tailwindcss";

/**
 * 근거: docs/vibe-coding-master-spec-v1.md 19~26절(키오스크 화면·설정), PROJECT_SCOPE.md.
 * 키오스크는 대형 터치스크린 전제 - 최소 터치영역(44px)과 대형 글자 유틸리티를 확장한다.
 */
const config: Config = {
  darkMode: "media",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    screens: {
      sm: "360px",
      md: "768px",
      lg: "1024px",
      xl: "1280px",
      "2xl": "1536px",
    },
    extend: {
      colors: {
        brand: {
          50: "#fdf4ec",
          100: "#f8e3cd",
          300: "#e8ad70",
          500: "#c97a2b",
          600: "#a65f1e",
          700: "#804a18",
        },
      },
      spacing: {
        // 키오스크 최소 터치 영역 44x44px (실제 버튼은 이보다 훨씬 크게 만든다).
        "tap-min": "44px",
        "safe-bottom": "env(safe-area-inset-bottom, 0px)",
        "safe-top": "env(safe-area-inset-top, 0px)",
      },
      fontSize: {
        base: ["1.125rem", { lineHeight: "1.6" }],
      },
      maxWidth: {
        "screen-content": "1280px",
      },
    },
  },
  plugins: [],
};

export default config;
