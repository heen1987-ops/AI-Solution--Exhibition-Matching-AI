import "@testing-library/jest-dom/vitest";

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import DocumentsTable from "../components/DocumentsTable";
import type { DocumentRead } from "../types";

// See features/partner-ai-review/tests/AttributeCard.test.tsx for why cleanup is explicit here
// (shared vitest.config.ts does not set test.globals, so RTL's auto-cleanup never registers).
afterEach(() => {
  cleanup();
});

function makeDocument(overrides: Partial<DocumentRead>): DocumentRead {
  return {
    document_id: "doc-1",
    exhibitor_id: "exhibitor-a",
    event_id: null,
    document_type: "CATALOG",
    status: "PROCESSED",
    filename: "catalog.pdf",
    mime_type: "application/pdf",
    size_bytes: 1024,
    content_hash: "hash",
    version_count: 1,
    is_published: false,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

describe("DocumentsTable", () => {
  it("renders an empty-state message instead of an empty table", () => {
    render(<DocumentsTable items={[]} />);
    expect(screen.getByText("등록된 문서가 없습니다.")).toBeInTheDocument();
  });

  it("renders one row per document with name, type, and status", () => {
    render(
      <DocumentsTable
        items={[
          makeDocument({ document_id: "doc-a", filename: "가격표.pdf", document_type: "PRICE_LIST", status: "UPLOADED" }),
          makeDocument({ document_id: "doc-b", filename: "카탈로그.pdf", document_type: "CATALOG", status: "PROCESSED" }),
        ]}
      />,
    );
    expect(screen.getByText("가격표.pdf")).toBeInTheDocument();
    expect(screen.getByText("카탈로그.pdf")).toBeInTheDocument();
    expect(screen.getByText("가격표")).toBeInTheDocument();
    expect(screen.getByText("카탈로그")).toBeInTheDocument();
  });

  it("shows a processing-failed row with an error-toned progress label, not a hidden/silent failure", () => {
    render(<DocumentsTable items={[makeDocument({ status: "PROCESSING_FAILED", filename: "failed.pdf" })]} />);
    expect(screen.getByText(/실패/)).toBeInTheDocument();
  });

  it('only offers the "AI 검수" action once a document has finished processing', () => {
    render(
      <DocumentsTable
        items={[
          makeDocument({ document_id: "doc-processing", status: "PROCESSING", filename: "processing.pdf" }),
          makeDocument({ document_id: "doc-done", status: "PROCESSED", filename: "done.pdf" }),
        ]}
      />,
    );
    const reviewLinks = screen.getAllByRole("link", { name: "AI 검수" });
    expect(reviewLinks).toHaveLength(1);
    expect(reviewLinks[0]).toHaveAttribute("href", "/partner/ai-review/doc-done");
  });

  it("keeps the table horizontally scrollable in its own container instead of the whole page (mobile-minimal smoke)", () => {
    const { container } = render(<DocumentsTable items={[makeDocument({})]} />);
    expect(container.querySelector(".overflow-x-auto")).not.toBeNull();
  });
});
