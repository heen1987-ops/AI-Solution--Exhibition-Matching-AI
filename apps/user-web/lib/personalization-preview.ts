export interface LocalRecommendationPreview {
  exhibitorName: string;
  productName: string;
  categoryLabel: string;
  boothLabel: string;
  matchLabel: "매우 잘 맞음" | "잘 맞음" | "함께 살펴볼 만함";
  reasons: string[];
  informationStatus: "확인됨" | "부스 미정" | "정보 확인 필요";
}

export interface LocalPersonalizationPreview {
  displayName: string;
  maskedPhone: string;
  registeredAt: string;
  sourceLabel: string;
  interests: string[];
  goals: string[];
  needsReview: boolean;
  notificationConsent: boolean;
  recommendations: LocalRecommendationPreview[];
}

function cleanText(value: unknown, maxLength: number): string | null {
  if (typeof value !== "string") return null;
  const cleaned = value.replace(/\s+/g, " ").trim();
  if (!cleaned || cleaned.length > maxLength) return null;
  return cleaned;
}

function cleanTextList(value: unknown, maxItems: number, maxLength: number): string[] | null {
  if (!Array.isArray(value) || value.length > maxItems) return null;
  const result = value.map((item) => cleanText(item, maxLength));
  return result.every((item): item is string => item !== null) ? result : null;
}

function isMaskedContact(value: string): boolean {
  return !value.includes("@") && value.includes("*") && !/\d{8,}/.test(value.replace(/[^\d*]/g, ""));
}

function parseRecommendation(value: unknown): LocalRecommendationPreview | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  const exhibitorName = cleanText(item.exhibitorName, 80);
  const productName = cleanText(item.productName, 120);
  const categoryLabel = cleanText(item.categoryLabel, 60);
  const boothLabel = cleanText(item.boothLabel, 40);
  const reasons = cleanTextList(item.reasons, 3, 140);
  const matchLabel = item.matchLabel;
  const informationStatus = item.informationStatus;

  if (
    !exhibitorName ||
    !productName ||
    !categoryLabel ||
    !boothLabel ||
    !reasons ||
    !["매우 잘 맞음", "잘 맞음", "함께 살펴볼 만함"].includes(String(matchLabel)) ||
    !["확인됨", "부스 미정", "정보 확인 필요"].includes(String(informationStatus))
  ) {
    return null;
  }

  return {
    exhibitorName,
    productName,
    categoryLabel,
    boothLabel,
    reasons,
    matchLabel: matchLabel as LocalRecommendationPreview["matchLabel"],
    informationStatus: informationStatus as LocalRecommendationPreview["informationStatus"],
  };
}

/**
 * 운영 발송 전 화면 검수용 로컬 어댑터.
 *
 * 값은 커밋하지 않은 `NEXT_PUBLIC_PERSONALIZATION_PREVIEW_JSON`에서만 읽는다. 실제 연락처,
 * 이메일, Magic Link 토큰은 거부하며 외부 전송이나 서버 저장을 수행하지 않는다.
 */
export function parseLocalPersonalizationPreview(
  raw: string | undefined = process.env.NEXT_PUBLIC_PERSONALIZATION_PREVIEW_JSON,
): LocalPersonalizationPreview | null {
  if (!raw) return null;

  try {
    const value = JSON.parse(raw) as Record<string, unknown>;
    const displayName = cleanText(value.displayName, 30);
    const maskedPhone = cleanText(value.maskedPhone, 30);
    const registeredAt = cleanText(value.registeredAt, 40);
    const sourceLabel = cleanText(value.sourceLabel, 60);
    const interests = cleanTextList(value.interests, 8, 60);
    const goals = cleanTextList(value.goals, 6, 60);
    const recommendations = Array.isArray(value.recommendations)
      ? value.recommendations.slice(0, 10).map(parseRecommendation)
      : null;

    if (
      !displayName ||
      !maskedPhone ||
      !isMaskedContact(maskedPhone) ||
      !registeredAt ||
      !sourceLabel ||
      !interests ||
      !goals ||
      !recommendations ||
      recommendations.some((item) => item === null) ||
      typeof value.needsReview !== "boolean" ||
      typeof value.notificationConsent !== "boolean"
    ) {
      return null;
    }

    return {
      displayName,
      maskedPhone,
      registeredAt,
      sourceLabel,
      interests,
      goals,
      needsReview: value.needsReview,
      notificationConsent: value.notificationConsent,
      recommendations: recommendations as LocalRecommendationPreview[],
    };
  } catch {
    return null;
  }
}
