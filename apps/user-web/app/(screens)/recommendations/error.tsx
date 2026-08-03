"use client";

import { ErrorNotice } from "@/components/StateViews";

export default function RecommendationsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <ErrorNotice
      title="추천 목록을 불러오지 못했습니다"
      description={`Mock 오류 시나리오: ${error.message}`}
      onRetry={reset}
    />
  );
}
