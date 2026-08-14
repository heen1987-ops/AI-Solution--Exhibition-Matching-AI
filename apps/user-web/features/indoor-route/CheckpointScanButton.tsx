"use client";

/**
 * 부스 체크포인트 확인 - "지금 이 부스에 있어요"를 서버에 알려 남은 동선을 현재 위치
 * 기준으로 다시 계산시킨다 (`POST /routes/checkpoint-scans`,
 * `apps/api/app/services/routing/positioning.py` QrCheckpointProvider).
 *
 * 카메라 QR 리더는 아직 없다. `apps/user-web/app/check-in/[qrToken]/page.tsx`의 기존
 * 체크인 흐름도 이 저장소에서는 자체 카메라 판독 위젯을 만들지 않고, 부스에 표시된 코드를
 * 직접 입력하는 대체 경로(`ManualCodeEntry`)를 항상 갖춘다 - 이 버튼은 같은 관례를 따라
 * 수동 코드 입력만 제공한다. 카메라 기반 QR 스캔 UI는 후속 작업이다(작업 지시에 명시된
 * "카메라 QR 스캐너를 정직하게 스코프 밖으로 남긴다" 원칙 - 없는 카메라 기능을 있는 척
 * 꾸미지 않는다).
 */

import { useState } from "react";

import { ApiClientError, checkpointScan, generateClientId } from "@/lib/api-client";

import type { CheckpointScanButtonProps } from "./types";

export default function CheckpointScanButton({ onScanned, disabled }: CheckpointScanButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [code, setCode] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmedMessage, setConfirmedMessage] = useState<string | null>(null);

  async function submit() {
    if (isSubmitting) return;
    const trimmed = code.trim();
    if (!trimmed) {
      setError("부스에 표시된 체크포인트 코드를 입력해 주세요.");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const result = await checkpointScan(
        { qr_token: trimmed },
        { idempotencyKey: generateClientId() },
      );
      setCode("");
      setIsOpen(false);
      setConfirmedMessage(
        result.route
          ? "체크포인트가 기록되었습니다. 남은 동선을 현재 위치 기준으로 다시 계산했어요."
          : "체크포인트가 기록되었습니다. 진행 중인 동선이 없어 별도로 다시 계산할 내용은 없어요.",
      );
      onScanned(result.route);
    } catch (err) {
      if (err instanceof ApiClientError && err.code === "INVALID_QR") {
        setError("유효하지 않거나 만료된 코드입니다. 부스 안내를 다시 확인해 주세요.");
      } else if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("체크포인트를 확인하지 못했습니다.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  if (!isOpen) {
    return (
      <div className="flex flex-col gap-1">
        <button
          type="button"
          onClick={() => {
            setIsOpen(true);
            setConfirmedMessage(null);
          }}
          disabled={disabled}
          className="tap-target w-fit border px-4 text-sm font-semibold disabled:opacity-60"
          style={{ borderColor: "var(--color-border)" }}
        >
          지금 이 부스에 도착했어요
        </button>
        {confirmedMessage ? (
          <p role="status" aria-live="polite" className="text-xs" style={{ color: "var(--color-success)" }}>
            {confirmedMessage}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 border p-3" style={{ borderColor: "var(--color-border)" }}>
      <label className="flex flex-col gap-1 text-sm">
        <span>체크포인트 코드</span>
        <input
          type="text"
          value={code}
          onChange={(event) => setCode(event.target.value)}
          className="rounded-lg border px-3 py-2 text-base"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
          aria-describedby={error ? "checkpoint-scan-error" : undefined}
          placeholder="부스에 표시된 코드를 입력하세요"
        />
      </label>
      <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
        카메라로 QR을 찍는 기능은 아직 없어요. 부스 안내판이나 QR 옆에 적힌 코드를 그대로
        입력해 주세요.
      </p>

      {error ? (
        <p id="checkpoint-scan-error" role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
          {error}
        </p>
      ) : null}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={submit}
          disabled={isSubmitting}
          className="tap-target w-fit rounded-lg px-4 text-sm font-semibold disabled:opacity-60"
          style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
        >
          {isSubmitting ? "확인 중..." : "도착 확인"}
        </button>
        <button
          type="button"
          onClick={() => {
            setIsOpen(false);
            setError(null);
          }}
          className="tap-target w-fit border px-4 text-sm font-semibold"
          style={{ borderColor: "var(--color-border)" }}
        >
          취소
        </button>
      </div>
    </div>
  );
}
