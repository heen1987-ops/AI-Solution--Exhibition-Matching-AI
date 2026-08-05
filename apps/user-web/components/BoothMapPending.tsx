export default function BoothMapPending() {
  return (
    <section aria-labelledby="booth-map-heading" className="overflow-hidden border border-[var(--color-border)] bg-white backju-panel">
      <div className="p-5 md:p-7">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="backju-eyebrow text-brand-600">BOOTH MAP</p>
            <h2 id="booth-map-heading" className="mt-2 text-2xl font-black tracking-[-0.03em] text-[#302f2c]">
              부스 배치도 준비 중
            </h2>
          </div>
          <span className="rounded-full bg-[#eee0b7] px-3 py-1 text-xs font-black text-[#594f32]">
            공식 배치 확정 전
          </span>
        </div>

        <div className="mt-5 grid min-h-52 place-items-center border border-dashed border-[#cdbf9e] bg-[#faf7f0] px-6 py-10 text-center">
          <div className="max-w-xl">
            <span aria-hidden="true" className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-white text-2xl shadow-[0_8px_24px_rgba(72,58,34,0.08)]">
              ◫
            </span>
            <strong className="mt-4 block text-lg text-[#3f3b33]">추천 업체의 부스 위치를 준비하고 있습니다</strong>
            <p className="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">
              공식 부스 배치도와 참가업체 부스번호가 확정되면, 나에게 추천된 업체의 위치를 배치도에서 바로 확인할 수 있습니다.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
