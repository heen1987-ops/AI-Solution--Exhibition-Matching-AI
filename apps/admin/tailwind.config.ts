import type { Config } from "tailwindcss";

/**
 * 관리자 앱은 데스크톱 중심 업무 도구다(운영자·검수자·업체담당자가 PC에서 사용).
 * apps/user-web/tailwind.config.ts와 톤을 맞추되(같은 브랜드 색), 데스크톱 표를 위한
 * 넓은 컨테이너를 기본으로 둔다.
 */
const config: Config = {
  darkMode: "media",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
    "./features/**/*.{ts,tsx}",
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
        "tap-min": "44px",
      },
      fontSize: {
        base: ["0.9375rem", { lineHeight: "1.6" }],
      },
      maxWidth: {
        "screen-content": "1440px",
      },
    },
  },
  plugins: [],
};

export default config;
