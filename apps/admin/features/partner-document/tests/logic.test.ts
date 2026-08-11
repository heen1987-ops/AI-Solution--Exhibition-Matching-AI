import { describe, expect, it } from "vitest";

import {
  computeExtractionProgress,
  documentStatusLabel,
  documentTypeLabel,
  filterOwnCompanyOnly,
} from "../logic";
import type { DocumentRead, ProcessingJobRead } from "../types";

function makeDocument(overrides: Partial<DocumentRead> = {}): DocumentRead {
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

describe("documentStatusLabel / documentTypeLabel", () => {
  it("maps known statuses to Korean labels", () => {
    expect(documentStatusLabel("UPLOADED")).toBe("업로드됨");
    expect(documentStatusLabel("PROCESSING")).toBe("AI 처리중");
    expect(documentStatusLabel("PROCESSED")).toBe("처리 완료");
    expect(documentStatusLabel("PROCESSING_FAILED")).toBe("처리 실패");
  });

  it("falls back to the raw code for an unknown status/type (open enum)", () => {
    expect(documentStatusLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW");
    expect(documentTypeLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW");
  });
});

describe("computeExtractionProgress", () => {
  it("derives progress from document status when no job list is available", () => {
    expect(computeExtractionProgress("PROCESSED", undefined)).toMatchObject({
      percent: 100,
      hasError: false,
    });
    expect(computeExtractionProgress("PROCESSING_FAILED", undefined)).toMatchObject({
      percent: 0,
      hasError: true,
    });
    expect(computeExtractionProgress("UPLOADED", undefined)).toMatchObject({
      percent: 0,
      hasError: false,
    });
  });

  it("reports 100% and no error once every processing job has completed", () => {
    const jobs: ProcessingJobRead[] = [
      { processing_job_id: "j1", document_id: "d1", status: "COMPLETED", created_at: "2026-08-01T00:00:00Z" },
    ];
    const progress = computeExtractionProgress("PROCESSED", jobs);
    expect(progress.percent).toBe(100);
    expect(progress.hasError).toBe(false);
  });

  it("surfaces a failure even while percent-complete looks high (does not hide errors behind %)", () => {
    const jobs: ProcessingJobRead[] = [
      { processing_job_id: "j1", document_id: "d1", status: "COMPLETED", created_at: "2026-08-01T00:00:00Z" },
      { processing_job_id: "j2", document_id: "d1", status: "FAILED", created_at: "2026-08-01T00:05:00Z" },
    ];
    const progress = computeExtractionProgress("PROCESSING_FAILED", jobs);
    expect(progress.hasError).toBe(true);
  });

  it("shows an in-progress state while the latest job is still running", () => {
    const jobs: ProcessingJobRead[] = [
      { processing_job_id: "j1", document_id: "d1", status: "RUNNING", created_at: "2026-08-01T00:00:00Z" },
    ];
    const progress = computeExtractionProgress("PROCESSING", jobs);
    expect(progress.label).toContain("처리중");
    expect(progress.hasError).toBe(false);
  });
});

describe("filterOwnCompanyOnly", () => {
  const items = [
    makeDocument({ document_id: "doc-a", exhibitor_id: "exhibitor-a" }),
    makeDocument({ document_id: "doc-b", exhibitor_id: "exhibitor-b" }),
  ];

  it("restricts EXHIBITOR_ADMIN to documents belonging to the session's own exhibitor_id", () => {
    const result = filterOwnCompanyOnly(items, "EXHIBITOR_ADMIN", "exhibitor-a");
    expect(result.map((d) => d.document_id)).toEqual(["doc-a"]);
  });

  it("returns an empty list for EXHIBITOR_ADMIN with no exhibitorId set (never leaks another company's data)", () => {
    const result = filterOwnCompanyOnly(items, "EXHIBITOR_ADMIN", null);
    expect(result).toEqual([]);
  });

  it("does not restrict operator roles (EVENT_ADMIN/DATA_REVIEWER can review any company)", () => {
    expect(filterOwnCompanyOnly(items, "EVENT_ADMIN", null)).toHaveLength(2);
    expect(filterOwnCompanyOnly(items, "DATA_REVIEWER", "exhibitor-a")).toHaveLength(2);
  });
});
