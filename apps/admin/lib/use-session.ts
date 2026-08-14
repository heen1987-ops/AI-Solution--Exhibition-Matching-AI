"use client";

import { useCallback, useEffect, useState } from "react";

import {
  fetchVerifiedSession,
  getDefaultSession,
  setRuntimeSession,
} from "./auth-state";
import type { AdminSession } from "./types";

export function useSession(): [AdminSession, (next: AdminSession) => void] {
  const [session, setSessionState] = useState<AdminSession>(getDefaultSession());

  useEffect(() => {
    let active = true;
    fetchVerifiedSession().then((verified) => {
      if (active) setSessionState(verified);
    });
    return () => {
      active = false;
    };
  }, []);

  const setSession = useCallback((next: AdminSession) => {
    setRuntimeSession(next);
    setSessionState(next);
  }, []);
  return [session, setSession];
}
