/**
 * 매칭 온톨로지(taxonomy) 개념 조회 - 얇은 fetch 래퍼.
 *
 * 근거 문서
 * ---------
 * - frontend/lib/types.ts 상단 주석과 `TaxonomyRef` 주석: "화면은
 *   `GET /api/v1/ontology/concepts`로 선택지를 채운 뒤 이 값을 채워야 한다."
 * - frontend/lib/api-client.ts 상단 주석: "`GET /api/v1/ontology/*` 계열은 이 파일이 쓰는
 *   표준 성공/오류 봉투를 따르지 않는 기존 구현이라 의도적으로 이 클라이언트 범위 밖에
 *   둔다. 필요한 화면 에이전트는 별도로 얇은 fetch를 작성하거나..." - 이 파일이 그 역할이다.
 * - backend/app/api/v1/endpoints/ontology.py - 실제 라우트(`GET /api/v1/ontology/concepts`)와
 *   원시 dict 응답 형태(`{taxonomy_version, items: [...]}`)의 1차 근거. 표준 성공 봉투
 *   (`{success, data, meta}`)를 쓰지 않으므로 `frontend/lib/api-client.ts`의 `apiGet`을 쓰지
 *   않고 이 파일에서 직접 `fetch`한다.
 * - 작업 지시: "6단계 매칭 온톨로지 문서가 아직 없다. 태그·속성 코드값 목록이 필요한 곳은
 *   유연하게 받고 하드코딩 enum을 피한다." - 이 모듈이 화면에 정적 Korean 라벨을 하드코딩하는
 *   대신 실제 서비스 중인 온톨로지 카탈로그에서 코드·라벨을 동적으로 가져오는 이유다.
 */

export interface OntologyConcept {
  code: string;
  concept_type: string;
  label_ko: string;
  parent?: string | null;
  assignable?: boolean;
  data_type?: string;
}

interface OntologyConceptsRaw {
  taxonomy_version: string;
  items: OntologyConcept[];
}

const API_ORIGIN = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");

export class OntologyFetchError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "OntologyFetchError";
    this.status = status;
  }
}

/**
 * `GET /api/v1/ontology/concepts`를 호출한다. 화면은 반환된 `items`를 선택지(칩·드롭다운)로
 * 렌더링하고, 사용자가 고른 `code` 값을 그대로 저장 요청에 실어 보낸다.
 *
 * @param conceptType 예: `VISIT_GOAL`, `BUSINESS_GOAL`, `PRODUCT_CATEGORY`, `TASTE`.
 *   (docs/06-matching-ontology.md 온톨로지 카탈로그의 concept_type 값 - 이 문서 자체가
 *   6단계 산출물이며, 정확한 concept_type 철자는 이 API 응답을 그대로 신뢰한다.)
 */
export async function fetchOntologyConcepts(
  params: { conceptType: string; parentCode?: string; assignableOnly?: boolean },
  options?: { signal?: AbortSignal },
): Promise<OntologyConcept[]> {
  const query = new URLSearchParams();
  query.set("concept_type", params.conceptType);
  if (params.parentCode) query.set("parent_code", params.parentCode);
  query.set("assignable_only", String(params.assignableOnly ?? true));

  const url = `${API_ORIGIN}/api/v1/ontology/concepts?${query.toString()}`;

  let response: Response;
  try {
    response = await fetch(url, {
      credentials: "include",
      headers: { Accept: "application/json" },
      signal: options?.signal,
    });
  } catch {
    throw new OntologyFetchError("온톨로지 코드 목록을 불러올 수 없습니다.", 0);
  }

  if (!response.ok) {
    throw new OntologyFetchError(
      `온톨로지 코드 목록 조회에 실패했습니다. (HTTP ${response.status})`,
      response.status,
    );
  }

  const payload = (await response.json()) as OntologyConceptsRaw;
  return Array.isArray(payload.items) ? payload.items : [];
}
