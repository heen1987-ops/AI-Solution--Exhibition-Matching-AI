import { describe, expect, it } from "vitest";

import { authApiUrl, getDefaultSession, hasCapability } from "./auth-state";

describe("verified admin session policy", () => {
  it("fails closed before a verified role grant is loaded", () => {
    const session = getDefaultSession();
    expect(session.state).toBe("ANONYMOUS");
    expect(session.role).toBeNull();
    expect(hasCapability(session.role, "AUDIT_VIEW")).toBe(false);
  });

  it("keeps role capabilities scoped to the frozen role map", () => {
    expect(hasCapability("EVENT_ADMIN", "EVENT_MANAGE")).toBe(true);
    expect(hasCapability("DATA_REVIEWER", "EVENT_MANAGE")).toBe(false);
    expect(hasCapability("EXHIBITOR_ADMIN", "EXHIBITOR_EDIT_OWN")).toBe(true);
    expect(hasCapability("EXHIBITOR_ADMIN", "EXHIBITOR_APPROVE")).toBe(false);
  });

  it("uses the shared v1 authentication path", () => {
    expect(authApiUrl("/auth/session")).toMatch(/\/api\/v1\/auth\/session$/);
  });
});
