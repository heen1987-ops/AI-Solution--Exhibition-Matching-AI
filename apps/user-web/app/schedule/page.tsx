"use client";

/**
 * U-18 나의 일정.
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md
 *     5.1절 라우트 표: `/schedule`, 핵심 API `GET /schedule`, 진입조건 "인증 또는 로컬 세션".
 *     U-18절: "방문·상담·프로그램을 하나의 타임라인에 표시한다. 상담 일정은 시간 충돌을
 *     허용하지 않고, 일반 부스 방문은 예상시간이 겹치면 경고만 제공한다."
 *     9.2절 상태 배지 표 - 상담(응답 대기/변경 제안/확정/완료/취소), 방문(경로 추가/방문
 *     완료/피드백 완료) 그룹의 1차 근거.
 * - docs/frontend-backend-ai-interface-spec.md 5절(권한·스코프) - "서버 저장·일정 |
 *   PHONE_VERIFIED" - 이 화면이 인증 오류를 만나면 차단 대신 인증 유도 위젯을 보여주는 이유.
 *
 * 백엔드 구현 상태에 대한 메모 (중요)
 * ------------------------------------
 * `GET /schedule`(방문·프로그램 통합 일정)은 이 저장소에 아직 라우터가 구현되지 않았다
 * (백엔드 저장소 전체를 검색해도 `app/api/v1/routers/schedule.py` 같은 파일이 없다). 반면
 * 상담(`GET /meetings`, `backend/app/api/v1/routers/meetings.py`)은 이미 구현돼 있다. 그래서
 * 이 화면은:
 *   1) `GET /schedule`을 시도해 방문·프로그램 항목을 얻는다. 아직 없는 API라 실패할 수 있고,
 *      그 경우 "방문·프로그램 일정 연동 준비 중"이라는 정상 상태로 처리하고 화면을 막지 않는다
 *      (와이어프레임 1.1절 7번 원칙: "오류·정보 부족·네트워크 단절도 정상 상태로 설계한다").
 *   2) 이미 구현된 `GET /meetings`로 상담 일정은 항상 실제로 가져온다.
 * `GET /schedule`의 정확한 응답 필드는 인터페이스 명세에 예시 JSON이 없어(U-18 행에 API
 * 경로만 있음) 아래 `ScheduleAuxResponse`는 화면이 필요로 하는 최소 필드로 잠정 정의했다.
 * TODO(백엔드 /schedule 라우터 구현 후 대조): 실제 응답 스키마가 나오면 이 타입을 맞춘다.
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import InlinePhoneVerify from "@/components/InlinePhoneVerify";
import { apiGet, ApiClientError, listMeetings } from "@/lib/api-client";
import { resetAuthStateToGuest } from "@/lib/auth-state";
import type { MeetingResponse, MeetingStatus, RecommendableObjectType } from "@/lib/types";

// ---------------------------------------------------------------------------
// GET /schedule 잠정 타입 (파일 상단 주석 참고)
// ---------------------------------------------------------------------------

type ScheduleAuxItemType = "VISIT" | "PROGRAM";

interface ScheduleAuxItem {
  schedule_item_id: string;
  item_type: ScheduleAuxItemType;
  title: string;
  object_type?: RecommendableObjectType | null;
  object_id?: string | null;
  zone?: string | null;
  start_at: string | null;
  end_at: string | null;
  status?: string | null;
}

interface ScheduleAuxResponse {
  visit_date: string | null;
  items: ScheduleAuxItem[];
}

// ---------------------------------------------------------------------------
// 통합 타임라인 모델
// ---------------------------------------------------------------------------

type TimelineKind = "VISIT" | "MEETING" | "PROGRAM";

interface TimelineEntry {
  id: string;
  kind: TimelineKind;
  title: string;
  subtitle: string | null;
  zone: string | null;
  statusLabel: string;
  start: Date | null;
  end: Date | null;
  href: string | null;
  conflict: "hard" | "soft" | null;
}

// 상담 상태는 db-erd/interface-spec이 이미 고정한 닫힌 집합이라 라벨 매핑을 하드코딩해도
// "6단계 온톨로지 코드값 하드코딩 금지" 원칙에 해당하지 않는다 (열린 taxonomy 코드가 아님).
const MEETING_STATUS_LABEL: Record<MeetingStatus, string> = {
  DRAFT: "작성 중",
  REQUESTED: "응답 대기",
  CONFIRMED: "확정",
  COMPLETED: "완료",
  COUNTER_PROPOSED: "시간 변경 제안",
  REJECTED: "거절됨",
  CANCELLED_BY_BUYER: "취소됨",
  CANCELLED_BY_EXHIBITOR: "취소됨",
  NO_SHOW: "노쇼",
};

const TIMELINE_KIND_LABEL: Record<TimelineKind, string> = {
  VISIT: "방문",
  MEETING: "상담",
  PROGRAM: "프로그램",
};

function meetingToEntry(meeting: MeetingResponse): TimelineEntry {
  const earliestCandidate = [...meeting.candidate_slots].sort(
    (a, b) => new Date(a.start_at).getTime() - new Date(b.start_at).getTime(),
  )[0];
  const tentative = !meeting.confirmed_start && Boolean(earliestCandidate);
  const startIso = meeting.confirmed_start ?? earliestCandidate?.start_at ?? null;
  const endIso = meeting.confirmed_end ?? earliestCandidate?.end_at ?? null;

  return {
    id: `meeting_${meeting.meeting_id}`,
    kind: "MEETING",
    title: `${meeting.topic_code ?? "상담"} 상담${tentative ? " (제안 시간)" : ""}`,
    // TODO(업체명 표시): 공개 업체 조회 API(예: GET /exhibitors/{id})가 아직 api-client에
    // 없어 exhibitor_id를 그대로 보여준다. 추가되면 업체명으로 교체한다.
    subtitle: `참가업체 ${meeting.exhibitor_id}`,
    zone: null,
    statusLabel: MEETING_STATUS_LABEL[meeting.status] ?? meeting.status,
    start: startIso ? new Date(startIso) : null,
    end: endIso ? new Date(endIso) : null,
    href: `/meetings/${meeting.meeting_id}`,
    conflict: null,
  };
}

function auxItemHref(item: ScheduleAuxItem): string | null {
  if (!item.object_type || !item.object_id) return null;
  if (item.object_type === "BOOTH") return `/booths/${item.object_id}`;
  if (item.object_type === "PRODUCT") return `/products/${item.object_id}`;
  return null;
}

function auxItemToEntry(item: ScheduleAuxItem): TimelineEntry {
  return {
    id: `aux_${item.schedule_item_id}`,
    kind: item.item_type,
    title: item.title,
    subtitle: null,
    zone: item.zone ?? null,
    statusLabel: item.status ?? "예정",
    start: item.start_at ? new Date(item.start_at) : null,
    end: item.end_at ? new Date(item.end_at) : null,
    href: auxItemHref(item),
    conflict: null,
  };
}

/** 상담 일정은 겹침을 허용하지 않으므로(hard) 강조하고, 일반 방문 간 겹침은 경고만(soft)
 * 표시한다 (U-18절). */
function computeConflicts(entries: TimelineEntry[]): TimelineEntry[] {
  const timed = entries
    .filter((entry): entry is TimelineEntry & { start: Date; end: Date } => Boolean(entry.start && entry.end))
    .sort((a, b) => a.start.getTime() - b.start.getTime());

  const severityById = new Map<string, "hard" | "soft">();

  for (let i = 0; i < timed.length; i += 1) {
    for (let j = i + 1; j < timed.length; j += 1) {
      if (timed[j].start.getTime() >= timed[i].end.getTime()) break;
      const severity: "hard" | "soft" =
        timed[i].kind === "MEETING" || timed[j].kind === "MEETING" ? "hard" : "soft";
      for (const id of [timed[i].id, timed[j].id]) {
        const previous = severityById.get(id);
        if (!previous || (previous === "soft" && severity === "hard")) {
          severityById.set(id, severity);
        }
      }
    }
  }

  return entries.map((entry) => ({ ...entry, conflict: severityById.get(entry.id) ?? null }));
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

function formatDateHeading(dateKey: string): string {
  if (dateKey === "unscheduled") return "날짜 미정";
  const date = new Date(`${dateKey}T00:00:00`);
  return date.toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "short" });
}

function dateKeyOf(entry: TimelineEntry): string {
  if (!entry.start) return "unscheduled";
  const y = entry.start.getFullYear();
  const m = String(entry.start.getMonth() + 1).padStart(2, "0");
  const d = String(entry.start.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function KindIcon({ kind }: { kind: TimelineKind }) {
  if (kind === "MEETING") {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} width={18} height={18} aria-hidden="true">
        <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
      </svg>
    );
  }
  if (kind === "PROGRAM") {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} width={18} height={18} aria-hidden="true">
        <circle cx="12" cy="12" r="10" />
        <polygon points="10 8 16 12 10 16 10 8" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} width={18} height={18} aria-hidden="true">
      <path d="M3 11.5 12 4l9 7.5" />
      <path d="M5 10v9a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1v-9" />
    </svg>
  );
}

export default function SchedulePage() {
  const [meetings, setMeetings] = useState<MeetingResponse[]>([]);
  const [auxItems, setAuxItems] = useState<ScheduleAuxItem[]>([]);
  const [auxAvailable, setAuxAvailable] = useState(true);
  const [loadState, setLoadState] = useState<"loading" | "loaded" | "error">("loading");
  const [needsAuth, setNeedsAuth] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadState("loading");
    setErrorMessage(null);

    let auxOk = true;
    try {
      const aux = await apiGet<ScheduleAuxResponse>("/schedule");
      setAuxItems(Array.isArray(aux.items) ? aux.items : []);
    } catch (err) {
      if (err instanceof ApiClientError && (err.code === "AUTH_REQUIRED" || err.code === "SESSION_EXPIRED")) {
        resetAuthStateToGuest();
        setNeedsAuth(true);
        setLoadState("loaded");
        return;
      }
      // /schedule은 아직 구현되지 않았을 수 있다 (파일 상단 주석) - 정상 상태로 흡수한다.
      auxOk = false;
      setAuxItems([]);
    }
    setAuxAvailable(auxOk);

    try {
      const response = await listMeetings({ limit: 50 });
      setMeetings(response.items);
      setNeedsAuth(false);
    } catch (err) {
      if (err instanceof ApiClientError && (err.code === "AUTH_REQUIRED" || err.code === "SESSION_EXPIRED")) {
        // 일반 관람객은 애초에 상담이 없을 수 있으므로 전체 화면을 막지 않고 상담만 비운다.
        setMeetings([]);
      } else if (err instanceof ApiClientError) {
        setLoadState("error");
        setErrorMessage(err.message);
        return;
      } else {
        setLoadState("error");
        setErrorMessage("일정을 불러오지 못했습니다.");
        return;
      }
    }

    setLoadState("loaded");
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const groups = useMemo(() => {
    const entries = computeConflicts([...meetings.map(meetingToEntry), ...auxItems.map(auxItemToEntry)]);
    const byDate = new Map<string, TimelineEntry[]>();
    for (const entry of entries) {
      const key = dateKeyOf(entry);
      const bucket = byDate.get(key) ?? [];
      bucket.push(entry);
      byDate.set(key, bucket);
    }
    for (const bucket of byDate.values()) {
      bucket.sort((a, b) => {
        if (!a.start && !b.start) return 0;
        if (!a.start) return 1;
        if (!b.start) return -1;
        return a.start.getTime() - b.start.getTime();
      });
    }
    return [...byDate.entries()].sort(([a], [b]) => {
      if (a === "unscheduled") return 1;
      if (b === "unscheduled") return -1;
      return a.localeCompare(b);
    });
  }, [meetings, auxItems]);

  const totalCount = meetings.length + auxItems.length;

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-4 px-4 py-4">
      <header>
        <h1 className="text-xl font-bold">나의 일정</h1>
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
          방문, 상담, 프로그램을 한 타임라인에서 확인해요.
        </p>
      </header>

      {needsAuth ? (
        <InlinePhoneVerify
          title="일정을 보려면 본인 인증이 필요해요"
          description="서버에 저장된 일정은 휴대전화 인증 후 확인할 수 있어요."
          onVerified={() => {
            setNeedsAuth(false);
            load();
          }}
        />
      ) : null}

      {!auxAvailable ? (
        <p
          role="status"
          className="rounded-lg border px-3 py-2 text-sm"
          style={{ borderColor: "var(--color-border)", color: "var(--color-text-muted)" }}
        >
          방문·프로그램 일정 연동은 준비 중이에요. 상담 일정은 아래에서 바로 확인할 수 있어요.
        </p>
      ) : null}

      {loadState === "loading" ? (
        <p role="status" aria-live="polite" className="py-8 text-center text-sm" style={{ color: "var(--color-text-muted)" }}>
          일정을 불러오는 중이에요...
        </p>
      ) : null}

      {loadState === "error" ? (
        <div role="alert" className="rounded-lg border p-4 text-sm" style={{ borderColor: "var(--color-danger)" }}>
          <p style={{ color: "var(--color-danger)" }}>{errorMessage ?? "일정을 불러오지 못했습니다."}</p>
          <button
            type="button"
            onClick={load}
            className="tap-target mt-2 rounded-lg border px-3 text-sm font-semibold"
            style={{ borderColor: "var(--color-border)" }}
          >
            다시 시도
          </button>
        </div>
      ) : null}

      {loadState === "loaded" && !needsAuth && totalCount === 0 ? (
        <div className="rounded-xl border p-6 text-center" style={{ borderColor: "var(--color-border)" }}>
          <p className="font-semibold">아직 일정이 없어요.</p>
          <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
            추천에서 부스를 저장하거나 상담을 요청하면 여기에 나타나요.
          </p>
          <Link
            href="/home"
            className="tap-target mt-3 inline-flex items-center rounded-lg px-4 font-semibold"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            추천 홈으로 가기
          </Link>
        </div>
      ) : null}

      {loadState === "loaded" && totalCount > 0
        ? groups.map(([dateKey, entries]) => (
            <section key={dateKey} className="flex flex-col gap-2">
              <h2 className="text-sm font-bold" style={{ color: "var(--color-text-muted)" }}>
                {formatDateHeading(dateKey)}
              </h2>
              <ol className="flex flex-col gap-2">
                {entries.map((entry) => {
                  const content = (
                    <>
                      <div className="flex items-center justify-between gap-2">
                        <span
                          className="inline-flex items-center gap-1 text-xs font-semibold"
                          style={{ color: "var(--color-brand)" }}
                        >
                          <KindIcon kind={entry.kind} />
                          {TIMELINE_KIND_LABEL[entry.kind]}
                        </span>
                        <span className="text-xs font-medium">
                          {entry.start ? formatTime(entry.start) : "시간 미정"}
                          {entry.end ? ` - ${formatTime(entry.end)}` : ""}
                        </span>
                      </div>
                      <p className="mt-1 font-semibold">{entry.title}</p>
                      {entry.subtitle ? (
                        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
                          {entry.subtitle}
                        </p>
                      ) : null}
                      {entry.zone ? (
                        <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
                          구역 {entry.zone}
                        </p>
                      ) : null}
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span
                          className="rounded-full border px-2 py-0.5 text-xs font-medium"
                          style={{ borderColor: "var(--color-border)" }}
                        >
                          {entry.statusLabel}
                        </span>
                        {entry.conflict === "hard" ? (
                          <span
                            className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold"
                            style={{ backgroundColor: "var(--color-danger)", color: "#fff" }}
                          >
                            ! 상담 시간과 겹쳐요
                          </span>
                        ) : null}
                        {entry.conflict === "soft" ? (
                          <span
                            className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold"
                            style={{ borderColor: "var(--color-brand)", color: "var(--color-brand)" }}
                          >
                            방문 시간이 겹쳐요
                          </span>
                        ) : null}
                      </div>
                    </>
                  );

                  return (
                    <li
                      key={entry.id}
                      className="rounded-xl border p-3"
                      style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
                    >
                      {entry.href ? (
                        <Link href={entry.href} className="block focus-visible:outline-none">
                          {content}
                        </Link>
                      ) : (
                        <div>{content}</div>
                      )}
                    </li>
                  );
                })}
              </ol>
            </section>
          ))
        : null}
    </div>
  );
}
