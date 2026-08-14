"use client";

import { useEffect } from "react";

import { useKioskSession } from "@/lib/kiosk-session-context";

/** <html lang>을 현재 키오스크 이용자의 선택 언어와 맞춘다 (스크린리더 접근성). */
export default function LangSync() {
  const { language } = useKioskSession();
  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);
  return null;
}
