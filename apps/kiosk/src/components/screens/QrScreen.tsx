import Link from "next/link";

/**
 * K-S7 QR 화면 골격.
 *
 * K-1-service-scope.md §5: QR 스캔은 새 GuestSession을 만들지 않고 "마지막 검색
 * 결과 목록"만 entry_channel='QR' 세션으로 인계한다 - 검색어나 그 이전 상호작용은
 * 인계하지 않는다. 전화번호/이메일로 링크를 보내는 방식은 절대 쓰지 않는다
 * (PROJECT_SCOPE.md 제외범위: 전화번호·이메일 입력 금지) - 오직 스캔 방식만 제공한다.
 * 실제 단기 토큰 발급 프로토콜은 K-5에서 상세화하며, 이번 웨이브는 자리표시자
 * QR 이미지와 안내 문구만 렌더링한다(Mock, 실제 세션 인계 없음).
 */
export function QrScreen() {
  return (
    <main
      data-testid="screen-qr"
      className="flex min-h-screen flex-col items-center justify-center gap-8 bg-slate-950 px-8 py-16 text-center text-white"
    >
      <h1 className="text-kiosk-lg font-bold">모바일로 이어보기</h1>
      <p className="max-w-md text-kiosk text-slate-300">
        휴대폰 카메라로 아래 QR코드를 스캔하면 지금까지 본 검색 결과를 이어서
        볼 수 있습니다. 전화번호나 이메일 입력은 필요하지 않습니다.
      </p>

      <div
        data-testid="qr-placeholder"
        role="img"
        aria-label="모바일 인계용 QR코드(자리표시자)"
        className="grid h-56 w-56 grid-cols-6 grid-rows-6 gap-1 rounded-2xl bg-white p-4"
      >
        {Array.from({ length: 36 }).map((_, index) => (
          <span
            key={index}
            className={(index * 7) % 3 === 0 ? "bg-slate-950" : "bg-white"}
          />
        ))}
      </div>

      <Link
        href="/results"
        className="min-h-touch rounded-2xl bg-slate-800 px-8 py-4 text-kiosk font-semibold"
      >
        결과 목록으로 돌아가기
      </Link>
    </main>
  );
}
