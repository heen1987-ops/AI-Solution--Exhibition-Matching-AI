import { describe, expect, it } from "vitest";

import { resolveNotificationTarget } from "../target";
import type { NotificationTarget } from "../types";

describe("resolveNotificationTarget (internal-route-only navigation guard)", () => {
  it("maps fixed-destination target types to their known internal path", () => {
    expect(resolveNotificationTarget({ target_type: "RECOMMENDATION", target_id: null })).toBe(
      "/recommendations",
    );
    expect(resolveNotificationTarget({ target_type: "PROFILE", target_id: null })).toBe(
      "/profile/preferences",
    );
    expect(resolveNotificationTarget({ target_type: "BUYER_MATCHES", target_id: null })).toBe(
      "/buyer/matches",
    );
  });

  it("maps id-based target types to their detail route with the id encoded", () => {
    expect(resolveNotificationTarget({ target_type: "MEETING", target_id: "m1" })).toBe("/meetings/m1");
    expect(resolveNotificationTarget({ target_type: "BOOTH", target_id: "b1" })).toBe("/booths/b1");
    expect(resolveNotificationTarget({ target_type: "PRODUCT", target_id: "p1" })).toBe("/products/p1");
    // EXHIBITOR has no dedicated detail route yet - maps to the closest existing screen (booth detail).
    expect(resolveNotificationTarget({ target_type: "EXHIBITOR", target_id: "e1" })).toBe("/booths/e1");
  });

  it("returns null for a missing target", () => {
    expect(resolveNotificationTarget(null)).toBeNull();
    expect(resolveNotificationTarget(undefined)).toBeNull();
  });

  it("returns null when the server marks the target as deleted, even for an otherwise valid target", () => {
    const target: NotificationTarget = { target_type: "MEETING", target_id: "m1", target_deleted: true };
    expect(resolveNotificationTarget(target)).toBeNull();
  });

  it("returns null for a target type outside the internal-route allowlist (never falls back to a raw value)", () => {
    expect(resolveNotificationTarget({ target_type: "EXTERNAL_LINK", target_id: "anything" })).toBeNull();
    expect(resolveNotificationTarget({ target_type: "http://evil.example/phish", target_id: null })).toBeNull();
  });

  it("returns null for an id-based type missing its id", () => {
    expect(resolveNotificationTarget({ target_type: "MEETING", target_id: null })).toBeNull();
  });

  it("rejects ids that look like an attempt to smuggle a path or protocol", () => {
    expect(resolveNotificationTarget({ target_type: "MEETING", target_id: "../../admin" })).toBeNull();
    expect(resolveNotificationTarget({ target_type: "MEETING", target_id: "http://evil.example" })).toBeNull();
    expect(resolveNotificationTarget({ target_type: "BOOTH", target_id: "b1/../../secret" })).toBeNull();
  });

  it("accepts a plain alphanumeric/uuid-shaped id", () => {
    expect(
      resolveNotificationTarget({ target_type: "MEETING", target_id: "3f9b6b0e-24b6-4c2b-9b7a-000000000001" }),
    ).toBe("/meetings/3f9b6b0e-24b6-4c2b-9b7a-000000000001");
  });
});
