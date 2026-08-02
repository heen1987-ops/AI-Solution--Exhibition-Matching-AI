"use client";

/**
 * U-19 관심목록(저장).
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md
 *     5.1절 라우트 표: `/saved`, 핵심 API `GET /saved-items`(실제 구현 경로는 인터페이스
 *     명세 6절 `/favorites` - 문서 우선순위: 인터페이스 명세 > 와이어프레임), 진입조건
 *     "인증 또는 로컬 세션".
 *     U-19절: "부스·제품·상담을 구분하고 `미방문`, `방문 완료`, `상담 예정`, `운영 종료` 상태를
 *     보여준다. 익명 사용자의 저장목록은 브라우저 로컬에 보관하고 인증 시 명시적으로 계정에
 *     합친다."
 * - docs/frontend-backend-ai-interface-spec.md 5절(권한·스코프) - "로컬 저장 | GUEST 가능",
 *   "서버 저장·일정 | PHONE_VERIFIED".
 * - 작업 지시: "익명 사용자의 저장목록은 브라우저 로컬(localStorage)에 보관하고 인증 시
 *   합치는 로직을 실제로 구현하라." -> `frontend/lib/local-favorites.ts`가 그 로직이고, 이
 *   화면이 그것을 실제로 사용한다.
 *
 * 상태 배지에 대한 메모
 * ---------------------
 * `방문 완료` 판정에는 사용자별 체크인 이력을 조회하는 API가 필요하지만 아직 없다
 * (`POST /check-ins`만 있고 목록 조회 GET이 없다 - `frontend/lib/api-client.ts` 13절 주석
 * 참고). 그래서 이 화면은 대상이 `CLOSED`/이용 불가면 `운영 종료`, 그 외에는 `미방문`을
 * 기본값으로 보여준다. TODO(체크인 이력 조회 API 도입 후): 실제 방문 여부로 교체한다.
 *
 * 빠른 저장 폼에 대한 메모
 * ------------------------
 * 부스·제품 상세(U-10/U-11)의 "저장" 버튼은 이 작업 범위 밖이라 아직 없다. 이 화면 하단의
 * "직접 추가" 폼은 그 버튼들이 생기기 전까지 `local-favorites`/`favorites` 저장 경로를 실제로
 * 실행해 볼 수 있게 하는 임시 진입점이다 - 나중에 U-10/U-11이 같은
 * `frontend/lib/local-favorites.ts`를 재사용하면 자연히 대체된다.
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";

import InlinePhoneVerify from "@/components/InlinePhoneVerify";
import {
  ApiClientError,
  createFavorite,
  deleteFavorite,
  getBooth,
  getProduct,
  listFavorites,
  listMeetings,
} from "@/lib/api-client";
import {
  getAuthState,
  isAtLeastPhoneVerified,
  resetAuthStateToGuest,
  subscribeAuthState,
} from "@/lib/auth-state";
import {
  addLocalFavorite,
  hasLocalFavorites,
  listLocalFavorites,
  mergeLocalFavoritesToServer,
  removeLocalFavorite,
  subscribeLocalFavorites,
} from "@/lib/local-favorites";
import type { FavoriteSource, MeetingResponse, MeetingStatus, RecommendableObjectType } from "@/lib/types";

type SavedTab = "BOOTH" | "PRODUCT" | "MEETING";

interface NormalizedFavorite {
  key: string;
  object_type: RecommendableObjectType;
  object_id: string;
  isLocal: boolean;
  favorite_id: string | null;
  local_id: string | null;
}

interface SavedEntry extends NormalizedFavorite {
  title: string;
  subtitle: string | null;
  statusLabel: string;
  href: string;
  loadError: boolean;
}

const MEETING_STATUS_LABEL: Record<MeetingStatus, string> = {
  DRAFT: "작성 중",
  REQUESTED: "상담 예정",
  CONFIRMED: "상담 예정",
  COMPLETED: "완료",
  COUNTER_PROPOSED: "상담 예정",
  REJECTED: "거절됨",
  CANCELLED_BY_BUYER: "취소됨",
  CANCELLED_BY_EXHIBITOR: "취소됨",
  NO_SHOW: "노쇼",
};

function StatusBadge({ children, tone = "default" }: { children: ReactNode; tone?: "default" | "closed" }) {
  return (
    <span
      className="rounded-full border px-2 py-0.5 text-xs font-medium"
      style={{
        borderColor: tone === "closed" ? "var(--color-text-muted)" : "var(--color-border)",
        color: tone === "closed" ? "var(--color-text-muted)" : "var(--color-text)",
      }}
    >
      {children}
    </span>
  );
}

async function enrichFavorite(favorite: NormalizedFavorite): Promise<SavedEntry> {
  if (favorite.object_type === "BOOTH") {
    try {
      const detail = await getBooth(favorite.object_id);
      return {
        ...favorite,
        title: detail.exhibitor.name,
        subtitle: `부스 ${detail.booth_number}`,
        statusLabel: detail.operating_status === "CLOSED" ? "운영 종료" : "미방문",
        href: `/booths/${favorite.object_id}`,
        loadError: false,
      };
    } catch {
      return {
        ...favorite,
        title: `부스 ${favorite.object_id}`,
        subtitle: "정보를 불러오지 못했어요",
        statusLabel: "정보 없음",
        href: `/booths/${favorite.object_id}`,
        loadError: true,
      };
    }
  }

  if (favorite.object_type === "PRODUCT") {
    try {
      const detail = await getProduct(favorite.object_id);
      const available = detail.availability.tasting || detail.availability.purchase || detail.availability.delivery;
      return {
        ...favorite,
        title: detail.product_name,
        subtitle: detail.exhibitor.name,
        statusLabel: available ? "미방문" : "운영 종료",
        href: `/products/${favorite.object_id}`,
        loadError: false,
      };
    } catch {
      return {
        ...favorite,
        title: `제품 ${favorite.object_id}`,
        subtitle: "정보를 불러오지 못했어요",
        statusLabel: "정보 없음",
        href: `/products/${favorite.object_id}`,
        loadError: true,
      };
    }
  }

  // EXHIBITOR/PROGRAM 저장은 U-19 와이어프레임이 명시한 3개 탭(부스/제품/상담) 밖이라
  // 목록에는 노출하되 상세 링크는 제공하지 않는다.
  return {
    ...favorite,
    title: `${favorite.object_type} ${favorite.object_id}`,
    subtitle: null,
    statusLabel: "미방문",
    href: "#",
    loadError: false,
  };
}

export default function SavedPage() {
  const [authState, setLocalAuthState] = useState(() => getAuthState().state);
  const [tab, setTab] = useState<SavedTab>("BOOTH");

  const [entries, setEntries] = useState<SavedEntry[]>([]);
  const [entriesLoadState, setEntriesLoadState] = useState<"loading" | "loaded" | "error">("loading");
  const [entriesError, setEntriesError] = useState<string | null>(null);
  const [mergeNotice, setMergeNotice] = useState<string | null>(null);

  const [meetings, setMeetings] = useState<MeetingResponse[]>([]);
  const [meetingsLoadState, setMeetingsLoadState] = useState<"loading" | "loaded" | "error" | "needs_auth">(
    "loading",
  );

  const [showVerify, setShowVerify] = useState(false);

  const [qaType, setQaType] = useState<Extract<RecommendableObjectType, "BOOTH" | "PRODUCT">>("BOOTH");
  const [qaId, setQaId] = useState("");
  const [qaBusy, setQaBusy] = useState(false);
  const [qaError, setQaError] = useState<string | null>(null);

  useEffect(() => subscribeAuthState(() => setLocalAuthState(getAuthState().state)), []);

  const loadFavorites = useCallback(async () => {
    setEntriesLoadState("loading");
    setEntriesError(null);
    try {
      let normalized: NormalizedFavorite[];

      if (isAtLeastPhoneVerified(authState)) {
        if (hasLocalFavorites()) {
          const result = await mergeLocalFavoritesToServer();
          if (result.mergedCount > 0) {
            setMergeNotice(`이 브라우저에 저장했던 관심목록 ${result.mergedCount}건을 계정에 합쳤어요.`);
          }
        }
        const response = await listFavorites();
        normalized = response.items.map((favorite) => ({
          key: `server_${favorite.favorite_id}`,
          object_type: favorite.object_type,
          object_id: favorite.object_id,
          isLocal: false,
          favorite_id: favorite.favorite_id,
          local_id: null,
        }));
      } else {
        normalized = listLocalFavorites().map((favorite) => ({
          key: `local_${favorite.local_id}`,
          object_type: favorite.object_type,
          object_id: favorite.object_id,
          isLocal: true,
          favorite_id: null,
          local_id: favorite.local_id,
        }));
      }

      const enriched = await Promise.all(normalized.map(enrichFavorite));
      setEntries(enriched);
      setEntriesLoadState("loaded");
    } catch (err) {
      setEntriesLoadState("error");
      setEntriesError(err instanceof ApiClientError ? err.message : "관심목록을 불러오지 못했습니다.");
    }
  }, [authState]);

  const loadMeetings = useCallback(async () => {
    setMeetingsLoadState("loading");
    try {
      const response = await listMeetings({ limit: 50 });
      setMeetings(response.items);
      setMeetingsLoadState("loaded");
    } catch (err) {
      if (err instanceof ApiClientError && (err.code === "AUTH_REQUIRED" || err.code === "SESSION_EXPIRED")) {
        resetAuthStateToGuest();
        setLocalAuthState("GUEST");
        setMeetingsLoadState("needs_auth");
      } else {
        setMeetingsLoadState("error");
      }
    }
  }, []);

  useEffect(() => {
    loadFavorites();
  }, [loadFavorites]);

  useEffect(() => subscribeLocalFavorites(() => loadFavorites()), [loadFavorites]);

  useEffect(() => {
    if (tab === "MEETING") loadMeetings();
  }, [tab, loadMeetings]);

  const boothEntries = useMemo(() => entries.filter((entry) => entry.object_type === "BOOTH"), [entries]);
  const productEntries = useMemo(() => entries.filter((entry) => entry.object_type === "PRODUCT"), [entries]);

  async function handleRemove(entry: SavedEntry) {
    try {
      if (entry.isLocal && entry.local_id) {
        removeLocalFavorite(entry.local_id);
      } else if (entry.favorite_id) {
        await deleteFavorite(entry.favorite_id);
      }
      setEntries((prev) => prev.filter((item) => item.key !== entry.key));
    } catch (err) {
      setEntriesError(err instanceof ApiClientError ? err.message : "삭제하지 못했습니다.");
    }
  }

  async function handleQuickAdd(event: FormEvent) {
    event.preventDefault();
    setQaError(null);
    const trimmed = qaId.trim();
    if (!trimmed) {
      setQaError("ID를 입력해 주세요.");
      return;
    }
    setQaBusy(true);
    try {
      const source: FavoriteSource = "SEARCH";
      if (isAtLeastPhoneVerified(authState)) {
        await createFavorite({ object_type: qaType, object_id: trimmed, source });
      } else {
        addLocalFavorite({ object_type: qaType, object_id: trimmed, source });
      }
      setQaId("");
      await loadFavorites();
    } catch (err) {
      setQaError(err instanceof ApiClientError ? err.message : "저장하지 못했습니다.");
    } finally {
      setQaBusy(false);
    }
  }

  function renderEntryList(list: SavedEntry[]) {
    if (entriesLoadState === "loading") {
      return (
        <p role="status" aria-live="polite" className="py-8 text-center text-sm" style={{ color: "var(--color-text-muted)" }}>
          불러오는 중이에요...
        </p>
      );
    }
    if (list.length === 0) {
      return (
        <div className="rounded-xl border p-6 text-center" style={{ borderColor: "var(--color-border)" }}>
          <p className="font-semibold">저장한 항목이 없어요.</p>
          <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
            마음에 드는 부스나 제품을 저장하면 여기에서 모아볼 수 있어요.
          </p>
        </div>
      );
    }
    return (
      <ul className="flex flex-col gap-2">
        {list.map((entry) => (
          <li
            key={entry.key}
            className="rounded-xl border p-3"
            style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
          >
            <div className="flex items-start justify-between gap-2">
              <Link href={entry.href} className="min-w-0 flex-1">
                <p className="truncate font-semibold">{entry.title}</p>
                {entry.subtitle ? (
                  <p className="truncate text-sm" style={{ color: "var(--color-text-muted)" }}>
                    {entry.subtitle}
                  </p>
                ) : null}
              </Link>
              <button
                type="button"
                onClick={() => handleRemove(entry)}
                className="tap-target rounded-lg border px-3 text-xs font-semibold"
                style={{ borderColor: "var(--color-border)" }}
                aria-label={`${entry.title} 관심목록에서 삭제`}
              >
                삭제
              </button>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <StatusBadge tone={entry.statusLabel === "운영 종료" ? "closed" : "default"}>
                {entry.statusLabel}
              </StatusBadge>
              {entry.isLocal ? <StatusBadge>이 브라우저에만 저장됨</StatusBadge> : null}
            </div>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-4 px-4 py-4">
      <header>
        <h1 className="text-xl font-bold">관심목록</h1>
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
          저장한 부스, 제품, 상담을 한곳에서 확인해요.
        </p>
      </header>

      {mergeNotice ? (
        <p role="status" className="rounded-lg border px-3 py-2 text-sm" style={{ borderColor: "var(--color-success)", color: "var(--color-success)" }}>
          {mergeNotice}
        </p>
      ) : null}

      {authState === "GUEST" && hasLocalFavorites() ? (
        <div className="rounded-xl border p-3" style={{ borderColor: "var(--color-border)" }}>
          <p className="text-sm">
            지금은 이 브라우저에만 저장돼요. 휴대전화 인증을 하면 다른 기기에서도 볼 수 있게 계정에
            합쳐드려요.
          </p>
          {!showVerify ? (
            <button
              type="button"
              onClick={() => setShowVerify(true)}
              className="tap-target mt-2 rounded-lg px-4 text-sm font-semibold"
              style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
            >
              휴대전화로 인증하기
            </button>
          ) : (
            <div className="mt-3">
              <InlinePhoneVerify
                onVerified={() => {
                  setShowVerify(false);
                  loadFavorites();
                }}
              />
            </div>
          )}
        </div>
      ) : null}

      <div role="tablist" aria-label="관심목록 종류" className="flex gap-2 border-b" style={{ borderColor: "var(--color-border)" }}>
        {([
          { id: "BOOTH", label: `부스 (${boothEntries.length})` },
          { id: "PRODUCT", label: `제품 (${productEntries.length})` },
          { id: "MEETING", label: `상담 (${meetings.length})` },
        ] as const).map((item) => (
          <button
            key={item.id}
            role="tab"
            type="button"
            aria-selected={tab === item.id}
            onClick={() => setTab(item.id)}
            className="tap-target -mb-px border-b-2 px-2 text-sm font-semibold"
            style={{
              borderColor: tab === item.id ? "var(--color-brand)" : "transparent",
              color: tab === item.id ? "var(--color-brand)" : "var(--color-text-muted)",
            }}
          >
            {item.label}
          </button>
        ))}
      </div>

      {entriesLoadState === "error" ? (
        <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
          {entriesError}
        </p>
      ) : null}

      {tab === "BOOTH" ? renderEntryList(boothEntries) : null}
      {tab === "PRODUCT" ? renderEntryList(productEntries) : null}

      {tab === "MEETING" ? (
        <>
          {meetingsLoadState === "loading" ? (
            <p role="status" aria-live="polite" className="py-8 text-center text-sm" style={{ color: "var(--color-text-muted)" }}>
              불러오는 중이에요...
            </p>
          ) : null}
          {meetingsLoadState === "needs_auth" ? (
            <InlinePhoneVerify
              title="상담 내역을 보려면 본인 인증이 필요해요"
              onVerified={() => loadMeetings()}
            />
          ) : null}
          {meetingsLoadState === "error" ? (
            <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
              상담 내역을 불러오지 못했습니다.
            </p>
          ) : null}
          {meetingsLoadState === "loaded" && meetings.length === 0 ? (
            <div className="rounded-xl border p-6 text-center" style={{ borderColor: "var(--color-border)" }}>
              <p className="font-semibold">요청한 상담이 없어요.</p>
            </div>
          ) : null}
          {meetingsLoadState === "loaded" && meetings.length > 0 ? (
            <ul className="flex flex-col gap-2">
              {meetings.map((meeting) => (
                <li
                  key={meeting.meeting_id}
                  className="rounded-xl border p-3"
                  style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
                >
                  <Link href={`/meetings/${meeting.meeting_id}`}>
                    <p className="font-semibold">{meeting.topic_code ?? "상담"} 상담</p>
                    <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
                      참가업체 {meeting.exhibitor_id}
                    </p>
                    <div className="mt-2">
                      <StatusBadge>{MEETING_STATUS_LABEL[meeting.status] ?? meeting.status}</StatusBadge>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}

      {tab !== "MEETING" ? (
        <details className="rounded-xl border p-3" style={{ borderColor: "var(--color-border)" }}>
          <summary className="cursor-pointer text-sm font-semibold">직접 추가 (부스·제품 ID)</summary>
          <form className="mt-3 flex flex-col gap-2 sm:flex-row" onSubmit={handleQuickAdd}>
            <select
              value={qaType}
              onChange={(event) => setQaType(event.target.value as "BOOTH" | "PRODUCT")}
              className="min-h-[44px] rounded-lg border px-2 text-sm"
              style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
              aria-label="저장할 대상 종류"
            >
              <option value="BOOTH">부스</option>
              <option value="PRODUCT">제품</option>
            </select>
            <input
              type="text"
              value={qaId}
              onChange={(event) => setQaId(event.target.value)}
              placeholder="ID 입력"
              className="min-h-[44px] flex-1 rounded-lg border px-3 text-sm"
              style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
              aria-label="저장할 대상 ID"
            />
            <button
              type="submit"
              disabled={qaBusy}
              className="tap-target rounded-lg px-4 text-sm font-semibold"
              style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
            >
              {qaBusy ? "저장 중..." : "저장"}
            </button>
          </form>
          {qaError ? (
            <p role="alert" className="mt-2 text-xs" style={{ color: "var(--color-danger)" }}>
              {qaError}
            </p>
          ) : null}
        </details>
      ) : null}
    </div>
  );
}
