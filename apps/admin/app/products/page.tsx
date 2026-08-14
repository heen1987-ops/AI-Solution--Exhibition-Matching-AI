"use client";

/**
 * A05 제품·서비스 검수. §43절. 작업 지시 필수 요구사항: 제품 등록/수정 폼.
 *
 * 업체 전체를 아우르는 관리자용 제품 목록 API는 아직 없다(§40.9절에 문서화조차 안 됨).
 * 대신 실제로 동작하는 `GET /exhibitors/{id}/products`(공개, 승인된 제품만)로 업체
 * 단위 조회를 제공한다 - 검수 대기 중인(미승인) 제품은 이 경로로 보이지 않는다는 한계를
 * 화면에 명시한다.
 */

import Link from "next/link";
import { useState } from "react";

import { listPublicExhibitorProducts } from "@/lib/api-client";
import type { PublicProductSummary } from "@/lib/types";
import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";
import RoleGate from "@/components/RoleGate";

export default function ProductsPage() {
  const [exhibitorId, setExhibitorId] = useState("");
  const [products, setProducts] = useState<PublicProductSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  const search = async () => {
    if (!exhibitorId.trim()) return;
    setLoading(true);
    setError(null);
    setProducts(null);
    try {
      const res = await listPublicExhibitorProducts(exhibitorId.trim());
      setProducts(res);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">제품·서비스</h1>
        <RoleGate capability="PRODUCT_MANAGE_OWN">
          <Link href="/products/new" className="tap-target rounded-md bg-[var(--color-brand)] px-3 py-2 text-sm font-medium text-[var(--color-brand-contrast)]">
            제품 등록
          </Link>
        </RoleGate>
        <RoleGate capability="PRODUCT_MANAGE_ANY">
          <Link href="/products/new" className="tap-target rounded-md bg-[var(--color-brand)] px-3 py-2 text-sm font-medium text-[var(--color-brand-contrast)]">
            제품 등록
          </Link>
        </RoleGate>
      </div>

      <p className="text-sm text-[var(--color-text-muted)]">
        업체 전체를 훑는 관리자 제품 목록 API가 아직 없어, 업체 ID로 조회합니다(실제 동작하는{" "}
        <code>GET /exhibitors/&#123;id&#125;/products</code>). 이 경로는 <b>승인되어 공개된
        제품만</b> 보여줍니다 - 검수 대기중(미승인) 제품 확인은 업체 검수 화면(§업체 검수)의
        AI 추출 근거 영역에서 진행하세요.
      </p>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void search();
        }}
        className="flex flex-wrap items-end gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
      >
        <div className="min-w-[260px]">
          <Field label="업체 ID">
            <input
              value={exhibitorId}
              onChange={(event) => setExhibitorId(event.target.value)}
              className="input font-mono text-xs"
              placeholder="UUID"
            />
          </Field>
        </div>
        <button
          type="submit"
          className="tap-target rounded-md border border-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand)]"
        >
          조회
        </button>
      </form>

      {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {!loading && error ? <ErrorBanner error={error} onRetry={search} /> : null}
      {!loading && !error && products && products.length === 0 && (
        <p className="text-sm text-[var(--color-text-muted)]">공개된 제품이 없습니다.</p>
      )}
      {!loading && !error && products && products.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--color-surface-muted)] text-xs uppercase text-[var(--color-text-muted)]">
              <tr>
                <th className="px-3 py-2">제품명</th>
                <th className="px-3 py-2">도수</th>
                <th className="px-3 py-2">시음</th>
                <th className="px-3 py-2">구매</th>
              </tr>
            </thead>
            <tbody>
              {products.map((product) => (
                <tr key={product.product_id} className="border-t border-[var(--color-border)]">
                  <td className="px-3 py-2 font-medium">{product.name}</td>
                  <td className="px-3 py-2">
                    {product.alcohol_percentage != null ? `${product.alcohol_percentage}%` : "-"}
                  </td>
                  <td className="px-3 py-2">{product.tasting_status}</td>
                  <td className="px-3 py-2">{product.purchase_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
