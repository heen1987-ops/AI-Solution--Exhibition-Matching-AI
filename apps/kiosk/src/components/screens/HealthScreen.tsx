"use client";

import { useEffect, useState } from "react";
import { resolveIdleTimeoutMs } from "@/lib/session/session-machine";

/**
 * 키오스크 설정·API 연결상태 화면.
 *
 * BAC-001이 노출하는 공통 헬스체크(/health/live, /health/ready)에 대한
 * 연결 확인은 이 화면의 본래 목적이므로(단순 Mock 스크린이 아님) 실제로 fetch를
 * 시도한다. 단, 백엔드가 떠 있지 않은 환경(로컬 스캐폴드/CI)에서도 화면이 멈추지
 * 않도록 짧은 타임아웃을 두고, 실패 시 "연결 안됨" 상태로 표시할 뿐 예외를
 * 던지지 않는다. 키오스크 회원가입/로그인이 없으므로 이 화면에는 인증 정보가
 * 전혀 없다 - 표시하는 것은 디바이스 설정(zone/id/idle timeout)뿐이다.
 */

type ConnectivityStatus = "checking" | "connected" | "error";

const CHECK_TIMEOUT_MS = 3000;

async function checkApiHealth(baseUrl: string): Promise<ConnectivityStatus> {
  try {
    const response = await fetch(`${baseUrl.replace(/\/$/, "")}/health/live`, {
      method: "GET",
      signal: AbortSignal.timeout(CHECK_TIMEOUT_MS),
    });
    return response.ok ? "connected" : "error";
  } catch {
    return "error";
  }
}

const STATUS_LABEL: Record<ConnectivityStatus, string> = {
  checking: "확인 중…",
  connected: "연결됨",
  error: "연결 안됨",
};

export function HealthScreen() {
  const [status, setStatus] = useState<ConnectivityStatus>("checking");

  const apiBaseUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  const deviceId = process.env.NEXT_PUBLIC_KIOSK_DEVICE_ID ?? "(미설정)";
  const deviceZone = process.env.NEXT_PUBLIC_KIOSK_DEVICE_ZONE ?? "(미설정)";
  const idleTimeoutMs = resolveIdleTimeoutMs(
    process.env.NEXT_PUBLIC_KIOSK_IDLE_TIMEOUT_MS
  );

  useEffect(() => {
    let cancelled = false;
    setStatus("checking");
    checkApiHealth(apiBaseUrl).then((result) => {
      if (!cancelled) {
        setStatus(result);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl]);

  return (
    <main
      data-testid="screen-health"
      className="flex min-h-screen flex-col gap-8 bg-slate-950 px-8 py-16 text-white"
    >
      <h1 className="text-kiosk-lg font-bold">키오스크 설정 · 연결상태</h1>

      <section
        aria-labelledby="connectivity-heading"
        className="rounded-2xl bg-slate-900 p-6"
      >
        <h2 id="connectivity-heading" className="text-kiosk font-semibold">
          공통 백엔드 API 연결상태
        </h2>
        <p className="mt-2 text-sm text-slate-400">GET {apiBaseUrl}/health/live</p>
        <p
          data-testid="connectivity-status"
          data-status={status}
          className="mt-4 text-kiosk font-semibold"
        >
          {STATUS_LABEL[status]}
        </p>
      </section>

      <section
        aria-labelledby="device-config-heading"
        className="rounded-2xl bg-slate-900 p-6"
      >
        <h2 id="device-config-heading" className="text-kiosk font-semibold">
          디바이스 설정
        </h2>
        <dl className="mt-4 grid grid-cols-2 gap-4 text-sm text-slate-300">
          <dt className="text-slate-500">디바이스 ID</dt>
          <dd>{deviceId}</dd>
          <dt className="text-slate-500">설치 구역(zone)</dt>
          <dd>{deviceZone}</dd>
          <dt className="text-slate-500">유휴 타임아웃</dt>
          <dd>{Math.round(idleTimeoutMs / 1000)}초</dd>
        </dl>
      </section>

      <p className="text-sm text-slate-500">
        이 화면은 회원가입/로그인 계정 정보를 다루지 않습니다 - 디바이스
        설정값과 공통 백엔드 연결상태만 표시합니다.
      </p>
    </main>
  );
}
