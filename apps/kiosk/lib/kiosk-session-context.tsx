"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { kioskClose, getKioskConfig } from "./api-client";
import { clampIdleTimeoutSeconds, DEFAULT_SUPPORTED_LANGUAGES, KIOSK_ID } from "./config";
import { clearKioskState, loadKioskState, saveKioskState } from "./storage";
import type {
  KioskConfig,
  KioskHandoffResponse,
  KioskLanguage,
  KioskSession,
  SearchResult,
} from "./types";

interface KioskSessionValue {
  kioskId: string;
  config: KioskConfig | null;
  configStatus: "loading" | "ready" | "error";
  idleTimeoutSeconds: number;

  language: KioskLanguage;
  setLanguage: (language: KioskLanguage) => void;

  session: KioskSession | null;
  setSession: (session: KioskSession | null) => void;

  query: string;
  setQuery: (query: string) => void;
  categoryCodes: string[];
  setCategoryCodes: (codes: string[]) => void;

  results: SearchResult[];
  interpretedConcepts: string[];
  applySearchResults: (results: SearchResult[], concepts: string[]) => void;
  handoff: KioskHandoffResponse | null;
  setHandoff: (handoff: KioskHandoffResponse | null) => void;

  /** 검색어·결과·선택업체·언어설정·QR토큰·로컬스토리지를 전부 지운다 (idle 타임아웃,
   * 이용 종료 버튼, 세션 만료 처리 공통 진입점). */
  resetAll: (options?: { notifyServer?: boolean }) => void;
}

const KioskSessionContext = createContext<KioskSessionValue | null>(null);

export function KioskSessionProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<KioskConfig | null>(null);
  const [configStatus, setConfigStatus] = useState<"loading" | "ready" | "error">("loading");

  const stored = useRef(loadKioskState());
  const [language, setLanguageState] = useState<KioskLanguage>(stored.current?.language ?? "ko");
  const [session, setSessionState] = useState<KioskSession | null>(stored.current?.session ?? null);
  const [query, setQueryState] = useState(stored.current?.query ?? "");
  const [categoryCodes, setCategoryCodesState] = useState<string[]>(
    stored.current?.categoryCodes ?? [],
  );
  const [results, setResults] = useState<SearchResult[]>(stored.current?.results ?? []);
  const [interpretedConcepts, setInterpretedConcepts] = useState<string[]>(
    stored.current?.interpretedConcepts ?? [],
  );
  const [handoff, setHandoffState] = useState<KioskHandoffResponse | null>(
    stored.current?.handoff ?? null,
  );

  const sessionRef = useRef(session);
  sessionRef.current = session;

  useEffect(() => {
    let active = true;
    getKioskConfig(KIOSK_ID)
      .then((next) => {
        if (!active) return;
        setConfig(next);
        setConfigStatus("ready");
      })
      .catch(() => {
        if (!active) return;
        setConfigStatus("error");
      });
    return () => {
      active = false;
    };
  }, []);

  // 개인 식별 정보가 없는 익명 세션 상태만 sessionStorage에 반영한다 (탭 종료 시 소멸).
  useEffect(() => {
    if (
      session === null &&
      query === "" &&
      categoryCodes.length === 0 &&
      results.length === 0 &&
      interpretedConcepts.length === 0 &&
      handoff === null
    ) {
      clearKioskState();
      return;
    }
    saveKioskState({
      language,
      session,
      query,
      categoryCodes,
      results,
      interpretedConcepts,
      handoff,
      savedAt: new Date().toISOString(),
    });
  }, [language, session, query, categoryCodes, results, interpretedConcepts, handoff]);

  const setLanguage = useCallback((next: KioskLanguage) => setLanguageState(next), []);
  const setSession = useCallback((next: KioskSession | null) => setSessionState(next), []);
  const setQuery = useCallback((next: string) => setQueryState(next), []);
  const setCategoryCodes = useCallback((next: string[]) => setCategoryCodesState(next), []);
  const setHandoff = useCallback(
    (next: KioskHandoffResponse | null) => setHandoffState(next),
    [],
  );

  const applySearchResults = useCallback((next: SearchResult[], concepts: string[]) => {
    setResults(next);
    setInterpretedConcepts(concepts);
  }, []);

  const resetAll = useCallback((options?: { notifyServer?: boolean }) => {
    const activeSessionId = sessionRef.current?.session_id;
    if ((options?.notifyServer ?? true) && activeSessionId) {
      void kioskClose(activeSessionId).catch(() => undefined);
    }
    sessionRef.current = null;
    setSessionState(null);
    setLanguageState(config?.default_language ?? "ko");
    setQueryState("");
    setCategoryCodesState([]);
    setResults([]);
    setInterpretedConcepts([]);
    setHandoffState(null);
    clearKioskState();
  }, [config?.default_language]);

  const idleTimeoutSeconds = clampIdleTimeoutSeconds(
    config?.session_timeout_seconds ?? session?.session_timeout_seconds,
  );

  const value = useMemo<KioskSessionValue>(
    () => ({
      kioskId: KIOSK_ID,
      config,
      configStatus,
      idleTimeoutSeconds,
      language,
      setLanguage,
      session,
      setSession,
      query,
      setQuery,
      categoryCodes,
      setCategoryCodes,
      results,
      interpretedConcepts,
      applySearchResults,
      handoff,
      setHandoff,
      resetAll,
    }),
    [
      config,
      configStatus,
      idleTimeoutSeconds,
      language,
      setLanguage,
      session,
      setSession,
      query,
      setQuery,
      categoryCodes,
      setCategoryCodes,
      results,
      interpretedConcepts,
      applySearchResults,
      handoff,
      setHandoff,
      resetAll,
    ],
  );

  return <KioskSessionContext.Provider value={value}>{children}</KioskSessionContext.Provider>;
}

export function useKioskSession(): KioskSessionValue {
  const ctx = useContext(KioskSessionContext);
  if (!ctx) {
    throw new Error("useKioskSession은 KioskSessionProvider 내부에서만 사용할 수 있습니다.");
  }
  return ctx;
}

export function supportedLanguages(config: KioskConfig | null): KioskLanguage[] {
  return config?.supported_languages ?? [...DEFAULT_SUPPORTED_LANGUAGES];
}
