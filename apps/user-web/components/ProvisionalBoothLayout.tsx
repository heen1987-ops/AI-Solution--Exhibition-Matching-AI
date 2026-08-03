import { PROVISIONAL_BOOTH_ZONES } from "@/lib/booth-layout";

const ZONE_STYLES = [
  "border-[#d7b58c] bg-[#f8ead9]",
  "border-[#9fc2d8] bg-[#e8f2f8]",
  "border-[#b7ceb9] bg-[#edf5ed]",
  "border-[#d4c38d] bg-[#f7f1dc]",
  "border-[#d7aeb2] bg-[#faecee]",
  "border-[#bdb2ca] bg-[#f2edf6]",
] as const;

export default function ProvisionalBoothLayout() {
  return (
    <section aria-labelledby="booth-map-heading" className="overflow-hidden border border-[var(--color-border)] bg-white backju-panel">
      <div className="border-b border-[var(--color-border)] p-5 md:p-7">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="backju-eyebrow text-brand-600">EXCO 3홀 · ZONE PLAN</p>
            <h2 id="booth-map-heading" className="mt-2 text-2xl font-black tracking-[-0.03em] text-[#302f2c]">부스 배치 검토안</h2>
          </div>
          <span className="rounded-full bg-[#eee0b7] px-3 py-1 text-xs font-black text-[#594f32]">확정 배치 아님</span>
        </div>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--color-text-muted)]">
          참고 배치도의 공간 구성을 바탕으로 입구, 중앙 체류공간, 프로그램 공간과 관심분야별 예상 구역만 정리했습니다. 실제 업체명과 부스번호는 운영 승인 후 연결됩니다.
        </p>
      </div>

      <div className="overflow-x-auto bg-[#f7f3eb] p-4 md:p-7" role="region" aria-label="검토용 부스 배치도" tabIndex={0}>
        <div className="mx-auto min-w-[680px] max-w-[920px] border-2 border-[#b6a985] bg-[#fffdf8] p-4 shadow-[0_14px_30px_rgba(72,58,34,0.08)]">
          <div className="grid grid-cols-2 gap-3">
            <div className="border border-[#91bad3] bg-[#dcecf6] px-4 py-3 text-center">
              <strong className="block text-sm text-[#263d4b]">세미나 · 프로그램</strong>
              <span className="text-xs text-[#536b79]">예상 운영 공간</span>
            </div>
            <div className="border border-[#91bad3] bg-[#dcecf6] px-4 py-3 text-center">
              <strong className="block text-sm text-[#263d4b]">시음 · 이벤트 무대</strong>
              <span className="text-xs text-[#536b79]">예상 운영 공간</span>
            </div>
          </div>

          <div className="mt-5 grid grid-cols-6 grid-rows-[repeat(3,minmax(92px,auto))] gap-3" aria-label="관심분야별 예상 구역">
            {PROVISIONAL_BOOTH_ZONES.map((zone, index) => {
              const positions = [
                "col-span-2 col-start-1 row-start-1",
                "col-span-2 col-start-3 row-start-1",
                "col-span-2 col-start-5 row-start-1",
                "col-span-2 col-start-1 row-start-2",
                "col-span-2 col-start-5 row-start-2",
                "col-span-2 col-start-1 row-start-3",
              ] as const;

              return (
                <div key={zone.id} className={`${positions[index]} ${ZONE_STYLES[index]} flex flex-col justify-center border px-3 py-3 text-center`}>
                  <span className="text-[0.62rem] font-black tracking-[0.16em] text-[#786c5b]">예상 구역 {zone.id}</span>
                  <strong className="mt-1 text-sm text-[#383630]">{zone.title}</strong>
                  <small className="mt-1 text-[0.68rem] leading-4 text-[#69645a]">{zone.detail}</small>
                </div>
              );
            })}

            <div className="col-span-2 col-start-3 row-span-2 row-start-2 flex flex-col items-center justify-center border-2 border-[#d8a83c] bg-[#f5c762] px-4 text-center">
              <span className="text-[0.62rem] font-black tracking-[0.15em] text-[#6d5219]">CENTRAL COMMUNITY</span>
              <strong className="mt-1 text-base text-[#3f341d]">중앙 체류 · 교류 공간</strong>
              <small className="mt-1 text-xs text-[#68552a]">휴식 · 시음 · 만남 기준점</small>
            </div>
            <div className="col-span-2 col-start-5 row-start-3 flex flex-col items-center justify-center border border-[#d6b75b] bg-[#f5dda0] px-3 text-center">
              <strong className="text-sm text-[#4c4124]">휴게 · 안내 구역</strong>
              <span className="mt-1 text-xs text-[#76683e]">추천 동선의 중간 기준점</span>
            </div>
          </div>

          <div className="mt-5 flex items-end justify-center gap-2" aria-label="행사장 입구 기준점">
            <span aria-hidden="true" className="text-xl font-black text-brand-700">↑</span>
            <div className="border-t-4 border-brand-600 px-10 pt-1 text-center text-xs font-black tracking-[0.14em] text-brand-700">입구 · 안내</div>
            <span aria-hidden="true" className="text-xl font-black text-brand-700">↑</span>
          </div>
        </div>
      </div>

      <div className="grid gap-4 p-5 md:grid-cols-3 md:p-7">
        <div className="border-l-4 border-[#c7b173] bg-[#faf7f0] px-4 py-3">
          <strong className="block text-sm text-[#3f3b33]">현재 표시</strong>
          <span className="mt-1 block text-xs leading-5 text-[var(--color-text-muted)]">카테고리별 예상 구역과 공간 기준점</span>
        </div>
        <div className="border-l-4 border-[#d8a8ad] bg-[#fcf5f6] px-4 py-3">
          <strong className="block text-sm text-[#3f3b33]">아직 미표시</strong>
          <span className="mt-1 block text-xs leading-5 text-[var(--color-text-muted)]">업체명 · 부스번호 · 정확한 실내 위치</span>
        </div>
        <div className="border-l-4 border-[#a8c6aa] bg-[#f1f7f1] px-4 py-3">
          <strong className="block text-sm text-[#3f3b33]">승인 후 연결</strong>
          <span className="mt-1 block text-xs leading-5 text-[var(--color-text-muted)]">추천 카드에서 부스 강조와 지도 이동</span>
        </div>
      </div>
    </section>
  );
}
