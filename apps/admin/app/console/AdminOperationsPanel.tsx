"use client";

import { FormEvent, useState } from "react";
import {
  submitBoothStatus,
  submitContentApproval,
  type BoothStatusPayload,
  type ContentApprovalPayload,
} from "../../lib/admin-api";

type SubmitState = {
  status: "idle" | "submitting" | "success" | "error";
  message: string;
};

const initialState: SubmitState = { status: "idle", message: "" };

export function AdminOperationsPanel() {
  const [approvalState, setApprovalState] = useState<SubmitState>(initialState);
  const [boothState, setBoothState] = useState<SubmitState>(initialState);

  async function handleApprovalSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload: ContentApprovalPayload = {
      exhibitor_id: String(form.get("exhibitor_id") ?? "").trim(),
      decision: String(form.get("decision")) as ContentApprovalPayload["decision"],
      note: String(form.get("note") ?? "").trim() || undefined,
    };

    setApprovalState({ status: "submitting", message: "처리 중" });
    try {
      const response = await submitContentApproval(payload);
      setApprovalState({
        status: "success",
        message: `승인 이력 ${response.content_approval_id} 생성`,
      });
    } catch (error) {
      setApprovalState({ status: "error", message: (error as Error).message });
    }
  }

  async function handleBoothSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const boothId = String(form.get("booth_id") ?? "").trim();
    const rowVersion = String(form.get("row_version") ?? "").trim();
    const payload: BoothStatusPayload = {
      operating_status: String(
        form.get("operating_status"),
      ) as BoothStatusPayload["operating_status"],
      congestion_level: String(
        form.get("congestion_level"),
      ) as BoothStatusPayload["congestion_level"],
      row_version: rowVersion ? Number(rowVersion) : undefined,
    };

    setBoothState({ status: "submitting", message: "처리 중" });
    try {
      const response = await submitBoothStatus(boothId, payload);
      setBoothState({
        status: "success",
        message: `부스 ${response.booth_id} 상태 ${response.operating_status}`,
      });
    } catch (error) {
      setBoothState({ status: "error", message: (error as Error).message });
    }
  }

  return (
    <section className="grid gap-4 lg:grid-cols-2" aria-label="운영 작업">
      <form
        onSubmit={handleApprovalSubmit}
        className="flex flex-col gap-4 rounded-lg border border-black/10 bg-white p-5 dark:border-white/10 dark:bg-white/5"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">업체정보 승인</h2>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
              POST /api/v1/admin/content-approvals
            </p>
          </div>
          <StatusPill label="실 API" tone="live" />
        </div>

        <Field label="Exhibitor ID" name="exhibitor_id" placeholder="UUID" required />
        <label className="flex flex-col gap-1 text-sm font-medium">
          결정
          <select
            name="decision"
            className="rounded-md border border-slate-300 bg-white px-3 py-2 font-normal dark:border-slate-700 dark:bg-slate-950"
            defaultValue="APPROVED"
          >
            <option value="APPROVED">승인</option>
            <option value="REJECTED">반려</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          메모
          <textarea
            name="note"
            rows={3}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 font-normal dark:border-slate-700 dark:bg-slate-950"
          />
        </label>
        <SubmitButton disabled={approvalState.status === "submitting"}>
          승인 처리
        </SubmitButton>
        <FormStatus state={approvalState} />
      </form>

      <form
        onSubmit={handleBoothSubmit}
        className="flex flex-col gap-4 rounded-lg border border-black/10 bg-white p-5 dark:border-white/10 dark:bg-white/5"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">부스 운영상태</h2>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
              PATCH /api/v1/admin/booths/:id/status
            </p>
          </div>
          <StatusPill label="실 API" tone="live" />
        </div>

        <Field label="Booth ID" name="booth_id" placeholder="UUID" required />
        <label className="flex flex-col gap-1 text-sm font-medium">
          운영 상태
          <select
            name="operating_status"
            className="rounded-md border border-slate-300 bg-white px-3 py-2 font-normal dark:border-slate-700 dark:bg-slate-950"
            defaultValue="OPEN"
          >
            <option value="OPEN">OPEN</option>
            <option value="PAUSED">PAUSED</option>
            <option value="CLOSED">CLOSED</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          혼잡도
          <select
            name="congestion_level"
            className="rounded-md border border-slate-300 bg-white px-3 py-2 font-normal dark:border-slate-700 dark:bg-slate-950"
            defaultValue="UNKNOWN"
          >
            <option value="UNKNOWN">UNKNOWN</option>
            <option value="LOW">LOW</option>
            <option value="MEDIUM">MEDIUM</option>
            <option value="HIGH">HIGH</option>
          </select>
        </label>
        <Field label="Row version" name="row_version" placeholder="선택" inputMode="numeric" />
        <SubmitButton disabled={boothState.status === "submitting"}>상태 저장</SubmitButton>
        <FormStatus state={boothState} />
      </form>
    </section>
  );
}

export function ContractPendingPanel() {
  return (
    <section className="grid gap-4 lg:grid-cols-2" aria-label="계약 대기 작업">
      <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-5 dark:border-slate-700 dark:bg-slate-900">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-base font-semibold">바이어 검증</h2>
          <StatusPill label="계약 대기" tone="pending" />
        </div>
        <dl className="mt-4 grid gap-3 text-sm">
          <div className="flex justify-between gap-4">
            <dt className="text-slate-500">business_email_verified</dt>
            <dd className="font-medium">API 미노출</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-slate-500">company_verified</dt>
            <dd className="font-medium">API 미노출</dd>
          </div>
        </dl>
      </div>

      <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-5 dark:border-slate-700 dark:bg-slate-900">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-base font-semibold">운영 통계 집계</h2>
          <StatusPill label="계약 대기" tone="pending" />
        </div>
        <ul className="mt-4 flex flex-col gap-2 text-sm text-slate-600 dark:text-slate-300">
          <li>사전등록 연계 건수</li>
          <li>프로파일 완성도 분포</li>
          <li>상담 요청/수락 건수</li>
        </ul>
      </div>
    </section>
  );
}

function Field({
  label,
  name,
  placeholder,
  required,
  inputMode,
}: {
  label: string;
  name: string;
  placeholder?: string;
  required?: boolean;
  inputMode?: "numeric";
}) {
  return (
    <label className="flex flex-col gap-1 text-sm font-medium">
      {label}
      <input
        name={name}
        required={required}
        placeholder={placeholder}
        inputMode={inputMode}
        className="rounded-md border border-slate-300 bg-white px-3 py-2 font-normal dark:border-slate-700 dark:bg-slate-950"
      />
    </label>
  );
}

function SubmitButton({
  children,
  disabled,
}: {
  children: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="submit"
      disabled={disabled}
      className="w-fit rounded-md bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:cursor-wait disabled:opacity-60 dark:bg-white dark:text-slate-950"
    >
      {children}
    </button>
  );
}

function StatusPill({
  label,
  tone,
}: {
  label: string;
  tone: "live" | "pending";
}) {
  return (
    <span
      className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${
        tone === "live"
          ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
          : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200"
      }`}
    >
      {label}
    </span>
  );
}

function FormStatus({ state }: { state: SubmitState }) {
  if (state.status === "idle") {
    return null;
  }
  return (
    <p
      role="status"
      className={`text-sm ${
        state.status === "error"
          ? "text-red-700 dark:text-red-300"
          : "text-slate-600 dark:text-slate-300"
      }`}
    >
      {state.message}
    </p>
  );
}
