import type { Config } from "tailwindcss";

/**
 * 근거: docs/user-ia-wireframes.md 13절(반응형·접근성).
 * - 13.1절 모바일 폭 360~430px 기준 컨테이너/브레이크포인트.
 * - 13.2절 접근성 완료 조건(본문 16px 이상, 터치영역 44x44px 이상, 대비 4.5:1 이상)을
 *   테마 토큰과 유틸리티로 뒷받침한다(구체적 강제는 frontend/app/globals.css).
 */
const config: Config = {
  darkMode: "media",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    // 13.1절: 모바일 360~430px, 태블릿·키오스크, 데스크톱 3단 반응형 기준.
    screens: {
      sm: "360px",
      md: "768px",
      lg: "1024px",
      xl: "1280px",
    },
    extend: {
      colors: {
        brand: {
          50: "#f5f1e8",
          100: "#eee8dc",
          300: "#c9b98f",
          500: "#927a49",
          600: "#7a663d",
          700: "#5d4d2e",
        },
      },
      spacing: {
        // 13.2절 최소 터치 영역 44x44px.
        "tap-min": "44px",
        "safe-bottom": "env(safe-area-inset-bottom, 0px)",
        "safe-top": "env(safe-area-inset-top, 0px)",
      },
      fontSize: {
        // 13.2절: 기본 본문 16px 이상.
        base: ["1rem", { lineHeight: "1.6" }],
      },
      maxWidth: {
        "screen-content": "1024px",
      },
    },
  },
  plugins: [],
};

export default config;
