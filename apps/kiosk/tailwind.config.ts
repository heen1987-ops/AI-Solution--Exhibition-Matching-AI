import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      // 키오스크는 터치 화면 기준 - 버튼 타깃을 크게 잡기 위한 최소 크기 토큰만 확장.
      minHeight: {
        touch: "72px",
      },
      fontSize: {
        kiosk: ["1.5rem", { lineHeight: "2rem" }],
        "kiosk-lg": ["2.5rem", { lineHeight: "3rem" }],
      },
    },
  },
  plugins: [],
};

export default config;
