/**
 * ADMIN-ANALYTICS 대시보드 순수 로직 (React 무관, 단위테스트 대상).
 *
 * 세 가지 책임:
 *  1. 필터 → 기간 계산 (오늘 / 행사기간 / 최근 7일 / 직접 지정)
 *  2. 억제(suppressed) 지표 표기·집계 CSV 생성 — 개인 단위 데이터가 구조적으로
 *     들어갈 수 없는 label/value 스칼라 행만 다룬다.
 *  3. PII 이중 방어 — 백엔드가 실수로 이메일·전화번호·연락처 필드를 흘려보내도
 *     UI에 도달하기 전에 마스킹/제거한다. 백엔드(app/services/analytics/
 *     suppression.py)에도 같은 방어가 있지만, 이 대시보드의 작업 지시가 "버그
 *     있는 백엔드 응답이 와도 UI 레이어에서 한 번 더" 를 명시적으로 요구한다.
 */

import type {
  AggregateCsvRow,
  AnalyticsFilter,
  DateRangePreset,
  Metric,
  ResolvedDateRange,
} from "./types";

// ---------------------------------------------------------------------------
// 1. 기간 계산
// ---------------------------------------------------------------------------

export const DATE_RANGE_PRESET_LABELS: Record<DateRangePreset, string> = {
  TODAY: "오늘",
  EVENT_PERIOD: "행사 기간 전체",
  LAST_7_DAYS: "최근 7일",
  CUSTOM: "직접 지정",
};

function toIsoDate(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export interface EventPeriod {
  startDate: string;
  endDate: string;
}

/**
 * 필터를 period_start/period_end(YYYY-MM-DD)로 확정한다.
 *
 * - EVENT_PERIOD인데 행사 기간 정보가 없으면(행사 API 미연동) 최근 7일로
 *   안전하게 폴백한다 — 화면은 폴백 사실을 표기해야 한다.
 * - CUSTOM인데 시작/끝이 비면 오늘 하루로 폴백한다.
 * - 시작 > 끝이면 뒤집어서 항상 start <= end를 보장한다.
 */
export function resolveDateRange(
  filter: Pick<AnalyticsFilter, "preset" | "customStart" | "customEnd">,
  eventPeriod: EventPeriod | null,
  now: Date = new Date(),
): ResolvedDateRange {
  const today = toIsoDate(now);
  switch (filter.preset) {
    case "TODAY":
      return { periodStart: today, periodEnd: today };
    case "EVENT_PERIOD":
      if (eventPeriod) {
        return { periodStart: eventPeriod.startDate, periodEnd: eventPeriod.endDate };
      }
      return lastNDays(7, now);
    case "LAST_7_DAYS":
      return lastNDays(7, now);
    case "CUSTOM": {
      const start = filter.customStart || today;
      const end = filter.customEnd || today;
      return start <= end
        ? { periodStart: start, periodEnd: end }
        : { periodStart: end, periodEnd: start };
    }
  }
}

function lastNDays(n: number, now: Date): ResolvedDateRange {
  const end = toIsoDate(now);
  const startDate = new Date(now);
  startDate.setDate(startDate.getDate() - (n - 1));
  return { periodStart: toIsoDate(startDate), periodEnd: end };
}

// ---------------------------------------------------------------------------
// 2. 지표 표기 + 집계 CSV
// ---------------------------------------------------------------------------

/** 소수집단 억제 표기 — 정확한 수 대신 항상 이 문자열을 쓴다. */
export const SUPPRESSED_LABEL = "5 미만";

export function formatMetric(
  metric: Metric | null | undefined,
  options: { percent?: boolean; unit?: string } = {},
): string {
  if (!metric) return "—";
  if (metric.suppressed) return SUPPRESSED_LABEL;
  if (metric.value === null || metric.value === undefined) return "—";
  if (options.percent) return `${(metric.value * 100).toFixed(1)}%`;
  const formatted = Number.isInteger(metric.value)
    ? metric.value.toLocaleString("ko-KR")
    : metric.value.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
  return options.unit ? `${formatted}${options.unit}` : formatted;
}

/** 초 단위 지표를 "n분 m초"로. 억제 규칙은 formatMetric과 동일. */
export function formatDurationMetric(metric: Metric | null | undefined): string {
  if (!metric) return "—";
  if (metric.suppressed) return SUPPRESSED_LABEL;
  if (metric.value === null || metric.value === undefined) return "—";
  const totalSeconds = Math.round(metric.value);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}분 ${seconds}초` : `${seconds}초`;
}

function csvEscape(value: string): string {
  if (/[",\n]/.test(value)) return `"${value.replace(/"/g, '""')}"`;
  return value;
}

/**
 * 집계 CSV 생성 — AggregateCsvRow(섹션/지표명/값 스칼라)만 받으므로 개인 단위
 * 행(연락처, 개별 사용자/바이어 행)이 구조적으로 들어갈 수 없다. 값 문자열에도
 * PII 마스킹을 한 번 더 적용한다(입력 실수 이중 방어).
 */
export function buildAggregateCsv(rows: AggregateCsvRow[]): string {
  const header = "section,label,value";
  const body = rows.map((row) =>
    [row.section, row.label, row.value].map((cell) => csvEscape(redactPiiText(cell))).join(","),
  );
  return [header, ...body].join("\n");
}

// ---------------------------------------------------------------------------
// 3. PII 이중 방어 (마스킹·제거)
// ---------------------------------------------------------------------------

/** 이메일. */
const EMAIL_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
/** 전화번호 — 한국 휴대폰/유선(01x-xxxx-xxxx, 02-xxx-xxxx, +82 ...) 및
 * 구분자 없는 10~11자리 연속 숫자. 4자리 이하 카운트 수치는 건드리지 않는다. */
const PHONE_RE = /(\+?82[-.\s]?)?0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}|\b0\d{9,10}\b/g;

export const PII_REDACTED_PLACEHOLDER = "[비공개]";

/** 자유 텍스트(검색어 등)에 사용자가 입력했을 수 있는 이메일/전화번호를 마스킹. */
export function redactPiiText(text: string): string {
  return text.replace(EMAIL_RE, PII_REDACTED_PLACEHOLDER).replace(PHONE_RE, PII_REDACTED_PLACEHOLDER);
}

/** 키 이름 자체가 개인 연락처/식별 정보를 시사하면 값 전체를 제거한다.
 * (집계 대시보드에 이런 키가 올 이유가 없다 — 존재 자체가 백엔드 버그) */
const FORBIDDEN_KEY_RE =
  /(^|_)(email|e_mail|phone|mobile|tel|telephone|contact|address|birth|ssn|resident|passport|full_name|person_name|buyer_name|user_name)(_|$)/i;

/**
 * 응답 페이로드 심층 정화. 모든 문자열 값에 redactPiiText를 적용하고,
 * 금지 키는 통째로 제거한다. api.ts가 모든 analytics 응답에 적용하므로
 * 화면 컴포넌트는 정화된 데이터만 받는다.
 */
export function sanitizeAnalyticsPayload<T>(payload: T): T {
  return deepSanitize(payload) as T;
}

function deepSanitize(value: unknown): unknown {
  if (typeof value === "string") return redactPiiText(value);
  if (Array.isArray(value)) return value.map(deepSanitize);
  if (value !== null && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      if (FORBIDDEN_KEY_RE.test(key)) continue; // 금지 키는 값 자체를 버린다
      out[key] = deepSanitize(child);
    }
    return out;
  }
  return value;
}

// ---------------------------------------------------------------------------
// 4. 신선도 표기
// ---------------------------------------------------------------------------

/**
 * "데이터 기준 시각" 라벨. 백엔드가 data_as_of를 주면 그 값을, 아니면 응답
 * 수신 시각을 기준으로 쓰되 두 경우 모두 "집계 지연 가능" 문구를 붙인다.
 */
export function freshnessLabel(dataAsOf: string | null | undefined, fetchedAt: Date): string {
  const base = dataAsOf ? new Date(dataAsOf) : fetchedAt;
  const stamp = Number.isNaN(base.getTime()) ? fetchedAt : base;
  const formatted = stamp.toLocaleString("ko-KR", { hour12: false });
  const sourceNote = dataAsOf ? "데이터 기준" : "조회 시각 기준";
  return `${sourceNote} ${formatted} · 집계는 실제 활동보다 지연될 수 있습니다`;
}

// ---------------------------------------------------------------------------
// 5. 역할별 섹션 접근 (백엔드 access.py의 ENDPOINT_ALLOWED_ROLES와 정합)
// ---------------------------------------------------------------------------

export type AnalyticsSection = "overview" | "web" | "kiosk" | "buyer";

/** lib/types.ts AdminRole 기준. 백엔드 app/services/analytics/access.py와 동일한
 * 정책: EXHIBITOR_ADMIN은 자사 범위가 자연스러운 buyer 섹션만, 행사 전체
 * 지표(overview/web/kiosk)는 스태프 역할만. 서버가 최종 강제하며 이 함수는
 * 버튼/링크 노출 제어용이다.
 *
 * 통합 시 재작성(fail-closed): 원래 시그니처는 `role`이 세 값 중 하나라고 가정해
 * `EXHIBITOR_ADMIN`이 아닌 모든 값(하이드레이션 전의 `null` 포함)을 "전체 노출"로
 * 취급했다 - 로그인 전 익명 방문자에게 잠깐이라도 모든 분석 탭이 보이는 fail-OPEN
 * 결함이었다. `role`이 없으면(세션 확인 전/실패) 무조건 false로 막는다. */
export function canViewAnalyticsSection(
  role: "EVENT_ADMIN" | "DATA_REVIEWER" | "EXHIBITOR_ADMIN" | null,
  section: AnalyticsSection,
): boolean {
  if (!role) return false;
  if (role === "EXHIBITOR_ADMIN") return section === "buyer";
  return true;
}
