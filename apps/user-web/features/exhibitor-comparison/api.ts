/**
 * 업체 비교 화면 전용 API 계층. 각 필드의 출처·공백은 `types.ts` 상단 주석 참고.
 */

import { getExhibitorAvailability } from "@/features/meeting/api";
import { apiGet } from "@/lib/api-client";

import type { ComparisonExhibitor, ComparisonProductSummary } from "./types";

interface RawPublicExhibitorDetail {
  exhibitor_id: string;
  company_name: string;
  company_summary: string | null;
  // 아래 필드들은 오늘 시점 공개 API 응답에는 없다(types.ts 상단 주석 참고). 백엔드가
  // 나중에 추가하면 그대로 읽히도록 옵셔널로 미리 선언해 둔다.
  channels?: string[];
  moq?: { min: number | null; max: number | null };
  regions?: string[];
  oem_available?: boolean;
  private_label_available?: boolean;
  export_available?: boolean;
}

interface RawPublicProductDetail {
  product_name: string;
  category_code: string | null;
}

function todayIso(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

async function fetchMeetingAvailableToday(exhibitorId: string): Promise<boolean | null> {
  try {
    const response = await getExhibitorAvailability(exhibitorId, { date: todayIso() });
    // 조회 자체가 성공했으면 결과가 0건이어도 "실제로 아는 값"(오늘은 상담 슬롯 없음)이다.
    return response.items.length > 0;
  } catch {
    // 조회 실패(권한/네트워크 등)만 UNKNOWN으로 남긴다 - 값을 지어내지 않는다.
    return null;
  }
}

export async function fetchComparisonExhibitor(exhibitorId: string): Promise<ComparisonExhibitor> {
  const [detail, products, meetingAvailableToday] = await Promise.all([
    apiGet<RawPublicExhibitorDetail>(`/exhibitors/${encodeURIComponent(exhibitorId)}`),
    apiGet<RawPublicProductDetail[]>(`/exhibitors/${encodeURIComponent(exhibitorId)}/products`).catch(
      () => [] as RawPublicProductDetail[],
    ),
    fetchMeetingAvailableToday(exhibitorId),
  ]);

  const productSummaries: ComparisonProductSummary[] = products.map((product) => ({
    product_name: product.product_name,
    category_code: product.category_code,
  }));

  return {
    exhibitor_id: detail.exhibitor_id,
    company_name: detail.company_name,
    company_summary: detail.company_summary,
    products: productSummaries,
    channels: detail.channels ?? null,
    moq: detail.moq ?? null,
    regions: detail.regions ?? null,
    oemAvailable: detail.oem_available ?? null,
    privateLabelAvailable: detail.private_label_available ?? null,
    exportAvailable: detail.export_available ?? null,
    meetingAvailableToday,
  };
}

export interface ComparisonFetchResult {
  exhibitors: ComparisonExhibitor[];
  failedIds: string[];
}

/** 개별 업체 조회가 실패해도(예: 부스가 비공개로 전환됨) 나머지 업체 비교는 그대로
 * 보여준다 - 하나가 실패했다고 화면 전체를 에러로 만들지 않는다. */
export async function fetchComparisonExhibitors(exhibitorIds: string[]): Promise<ComparisonFetchResult> {
  const settled = await Promise.allSettled(exhibitorIds.map((id) => fetchComparisonExhibitor(id)));
  const exhibitors: ComparisonExhibitor[] = [];
  const failedIds: string[] = [];
  settled.forEach((result, index) => {
    if (result.status === "fulfilled") {
      exhibitors.push(result.value);
    } else {
      failedIds.push(exhibitorIds[index]);
    }
  });
  return { exhibitors, failedIds };
}
