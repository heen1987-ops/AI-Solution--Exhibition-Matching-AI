import { PROVISIONAL_BOOTH_COLUMNS, type ProvisionalBoothColumn } from "@/lib/booth-layout";

const COLUMN_STYLES = {
  Q: "border-[#d9afb3] bg-[#f8dfe1]",
  R: "border-[#cba9ad] bg-[#f3d6d9]",
  S: "border-[#d9afb3] bg-[#f8dfe1]",
} as const;

function BoothColumn({ column }: { column: ProvisionalBoothColumn }) {
  return (
    <section aria-label={column.label} className="min-w-0">
      <div className="mb-2 flex items-center justify-between border-b border-[#c8b9a6] pb-1">
        <strong className="text-sm text-[#3b3935]">{column.id}</strong>
        <span className="text-[0.6rem] font-bold tracking-[0.12em] text-[#81786c]">PLANNING</span>
      </div>
      <div className="grid grid-cols-2 content-start gap-1.5">
        {column.booths.map((cell) => (
          <div
            key={cell.code}
            className={`${cell.width === "DOUBLE" ? "col-span-2" : "col-span-1"} ${COLUMN_STYLES[column.id]} flex min-h-10 items-center justify-center border px-1.5 py-2 text-center text-[0.66rem] font-extrabold text-[#4d3b3d]`}
          >
            {cell.code}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function ProvisionalBoothLayout() {
  return (
    <section aria-labelledby="booth-map-heading" className="overflow-hidden border border-[var(--color-border)] bg-white backju-panel">
      <div className="border-b border-[var(--color-border)] p-5 md:p-7">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="backju-eyebrow text-brand-600">EXCO 3홀 · SINGLE HALL PLAN</p>
            <h2 id="booth-map-heading" className="mt-2 text-2xl font-black tracking-[-0.03em] text-[#302f2c]">3홀 단독 사용 검토안</h2>
          </div>
          <span className="rounded-full bg-[#eee0b7] px-3 py-1 text-xs font-black text-[#594f32]">확정 배치 아님</span>
        </div>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--color-text-muted)]">
          제공된 참고 도면의 사용 범위를 기준으로 바이어 라운지, Q·R·S 부스열과 하단 입구를 반영했습니다. 표시된 코드는 공간 검토용 계획값이며 참가업체 배정을 의미하지 않습니다.
        </p>
      </div>

      <div className="overflow-x-auto bg-[#f7f3eb] p-4 md:p-7" role="region" aria-label="3홀 단독 사용 검토용 부스 배치도" tabIndex={0}>
        <div className="mx-auto min-w-[700px] max-w-[860px] border-2 border-[#9f9c93] bg-[#fffdf8] p-4 shadow-[0_14px_30px_rgba(72,58,34,0.08)]">
          <div className="grid grid-cols-[150px_repeat(3,minmax(0,1fr))] items-stretch gap-5">
            <aside className="flex min-h-[520px] flex-col items-center justify-center border border-[#cbd2d4] bg-[#e4eaeb] px-3 text-center">
              <span className="text-[0.62rem] font-black tracking-[0.14em] text-[#5e6a6d]">BUYER LOUNGE</span>
              <strong className="mt-2 text-sm text-[#343b3d]">백주 사랑방</strong>
              <small className="mt-1 text-xs leading-5 text-[#657174]">바이어 상담 · 대기 공간</small>
            </aside>

            {PROVISIONAL_BOOTH_COLUMNS.map((column) => (
              <BoothColumn key={column.id} column={column} />
            ))}
          </div>

          <div className="mt-5 grid grid-cols-[150px_1fr] gap-5">
            <div aria-hidden="true" />
            <div className="flex items-end justify-center gap-2" aria-label="행사장 입구 기준점">
              <span aria-hidden="true" className="text-xl font-black text-brand-700">↑</span>
              <div className="border-t-4 border-brand-600 px-12 pt-1 text-center text-xs font-black tracking-[0.14em] text-brand-700">입구</div>
              <span aria-hidden="true" className="text-xl font-black text-brand-700">↑</span>
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-4 p-5 md:grid-cols-3 md:p-7">
        <div className="border-l-4 border-[#aebfc2] bg-[#f2f6f6] px-4 py-3">
          <strong className="block text-sm text-[#3f3b33]">공간 기준</strong>
          <span className="mt-1 block text-xs leading-5 text-[var(--color-text-muted)]">왼쪽 바이어 라운지 · 하단 중앙 입구</span>
        </div>
        <div className="border-l-4 border-[#d8a8ad] bg-[#fcf5f6] px-4 py-3">
          <strong className="block text-sm text-[#3f3b33]">부스 계획</strong>
          <span className="mt-1 block text-xs leading-5 text-[var(--color-text-muted)]">Q·R·S 부스열과 참고용 계획 코드</span>
        </div>
        <div className="border-l-4 border-[#a8c6aa] bg-[#f1f7f1] px-4 py-3">
          <strong className="block text-sm text-[#3f3b33]">확정 후 연결</strong>
          <span className="mt-1 block text-xs leading-5 text-[var(--color-text-muted)]">승인 업체 · 추천 카드 · 부스 강조 표시</span>
        </div>
      </div>
    </section>
  );
}
