import { getAdminEnvInfo } from "./env";

export type DataSource = "api" | "fallback";

export interface AdminConsoleSnapshot {
  source: DataSource;
  apiStatus: "online" | "offline";
  notice?: string;
  metrics: Array<{
    key: string;
    label: string;
    value: string;
    status: "live" | "contract_pending";
  }>;
}

export interface ContentApprovalPayload {
  exhibitor_id: string;
  decision: "APPROVED" | "REJECTED";
  note?: string;
}

export interface ContentApprovalResponse {
  content_approval_id: string;
  exhibitor_id: string;
  decision: "APPROVED" | "REJECTED";
  approved_at: string;
}

export interface BoothStatusPayload {
  operating_status: "OPEN" | "PAUSED" | "CLOSED";
  congestion_level?: "LOW" | "MEDIUM" | "HIGH" | "UNKNOWN";
  row_version?: number;
}

export interface BoothDetailResponse {
  booth_id: string;
  exhibitor_id: string;
  operating_status: string;
  congestion_level: string;
  row_version: number;
}

type ApiErrorBody = {
  error?: {
    code?: string;
    message?: string;
  };
};

export function adminApiBaseUrl(): string | null {
  const raw =
    process.env.MEETAI_API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "";
  const trimmed = raw.trim().replace(/\/+$/, "");
  return trimmed || null;
}

export function adminHeaders(): HeadersInit {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const userId =
    process.env.MEETAI_ADMIN_USER_ID ??
    process.env.NEXT_PUBLIC_ADMIN_USER_ID ??
    "";
  const actorRole =
    process.env.MEETAI_ADMIN_ACTOR_ROLE ??
    process.env.NEXT_PUBLIC_ADMIN_ACTOR_ROLE ??
    "OPERATOR";
  if (userId.trim()) {
    headers["X-MeetAI-User-Id"] = userId.trim();
  }
  if (actorRole.trim()) {
    headers["X-MeetAI-Actor-Role"] = actorRole.trim();
  }
  return headers;
}

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const baseUrl = adminApiBaseUrl();
  if (!baseUrl) {
    throw new Error("API_BASE_URL_NOT_CONFIGURED");
  }

  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      ...adminHeaders(),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      body = undefined;
    }
    throw new Error(body?.error?.code ?? `HTTP_${response.status}`);
  }
  return (await response.json()) as T;
}

export async function loadAdminConsoleSnapshot(): Promise<AdminConsoleSnapshot> {
  const env = getAdminEnvInfo();
  try {
    await apiFetch("/api/v1/system/info");
    return {
      source: "api",
      apiStatus: "online",
      metrics: baseMetrics(env.contractVersion),
    };
  } catch (error) {
    return {
      source: "fallback",
      apiStatus: "offline",
      notice: (error as Error).message,
      metrics: baseMetrics(env.contractVersion),
    };
  }
}

export async function submitContentApproval(
  payload: ContentApprovalPayload,
): Promise<ContentApprovalResponse> {
  return apiFetch<ContentApprovalResponse>("/api/v1/admin/content-approvals", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function submitBoothStatus(
  boothId: string,
  payload: BoothStatusPayload,
): Promise<BoothDetailResponse> {
  return apiFetch<BoothDetailResponse>(
    `/api/v1/admin/booths/${encodeURIComponent(boothId)}/status`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

function baseMetrics(contractVersion: string): AdminConsoleSnapshot["metrics"] {
  return [
    {
      key: "pre-registration",
      label: "사전등록 연계",
      value: "집계 API 대기",
      status: "contract_pending",
    },
    {
      key: "profile-completeness",
      label: "프로파일 완성도",
      value: "분포 API 대기",
      status: "contract_pending",
    },
    {
      key: "meeting-conversion",
      label: "상담 요청/수락",
      value: "상담 집계 API 대기",
      status: "contract_pending",
    },
    {
      key: "contract",
      label: "계약 버전",
      value: contractVersion,
      status: "live",
    },
  ];
}
