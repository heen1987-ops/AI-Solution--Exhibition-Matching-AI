import type { LocalPersonalizationPreview } from "@/lib/personalization-preview";

export default function KakaoTestPreview({ preview }: { preview: LocalPersonalizationPreview }) {
  return (
    <section
      aria-labelledby="kakao-test-preview-heading"
      className="backju-panel border p-5 md:p-7"
      style={{ borderColor: "var(--color-border)", backgroundColor: "#fff" }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="backju-eyebrow" style={{ color: "#805f32" }}>KAKAO DELIVERY CHECK</p>
          <h2 id="kakao-test-preview-heading" className="backju-section-title mt-1 text-lg font-extrabold">
            카카오 알림톡 테스트 준비
          </h2>
        </div>
        <span className="rounded-full bg-[#f4efe3] px-3 py-1 text-xs font-extrabold text-[#6c5a3b]">발송 안 함</span>
      </div>

      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs font-bold text-[#766d5e]">테스트 대상</dt>
          <dd className="mt-1 font-extrabold">{preview.displayName} · {preview.maskedPhone}</dd>
        </div>
        <div>
          <dt className="text-xs font-bold text-[#766d5e]">안내 수신</dt>
          <dd className="mt-1 font-extrabold">{preview.notificationConsent ? "동의 확인" : "발송 제외"}</dd>
        </div>
        <div>
          <dt className="text-xs font-bold text-[#766d5e]">추천 결과</dt>
          <dd className="mt-1 font-extrabold">참가업체 {preview.recommendations.length}곳 준비</dd>
        </div>
      </dl>

      <div className="mt-5 rounded-sm border border-[#e1d3b6] bg-[#fffaf0] p-4 text-sm leading-6">
        <p className="font-extrabold">[2026 대한민국 백주대간]</p>
        <p className="mt-2">
          {preview.displayName} 님의 사전등록 정보를 바탕으로 관심 분야와 관련된 참가업체 {preview.recommendations.length}곳을
          추천했습니다.
        </p>
        <p className="mt-2">추천 이유와 행사장 정보를 나의 행사 페이지에서 확인해 주세요.</p>
        <span className="mt-3 inline-flex rounded-sm bg-[#f6dc00] px-4 py-2 font-extrabold text-[#29251d]">
          나의 추천 업체 확인
        </span>
      </div>
      <p className="mt-3 text-xs leading-5" style={{ color: "var(--color-text-muted)" }}>
        실제 전화번호·개인 링크·업체 순위는 화면이나 로그에 저장하지 않습니다. 공식 딜러와 승인 템플릿이 준비되기 전에는
        외부 발송하지 않습니다.
      </p>
    </section>
  );
}
