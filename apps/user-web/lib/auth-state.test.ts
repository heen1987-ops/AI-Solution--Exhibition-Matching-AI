import { describe, expect, it } from "vitest";

import { isAtLeastPhoneVerified, isAuthenticationState } from "./auth-state";

describe("user authentication UI hints", () => {
  it("accepts only the published authentication states", () => {
    expect(isAuthenticationState("GUEST")).toBe(true);
    expect(isAuthenticationState("PHONE_VERIFIED")).toBe(true);
    expect(isAuthenticationState("ACCOUNT_AUTHENTICATED")).toBe(true);
    expect(isAuthenticationState("ADMIN")).toBe(false);
  });

  it("does not treat a guest hint as phone verification", () => {
    expect(isAtLeastPhoneVerified("GUEST")).toBe(false);
    expect(isAtLeastPhoneVerified("PHONE_VERIFIED")).toBe(true);
    expect(isAtLeastPhoneVerified("ACCOUNT_AUTHENTICATED")).toBe(true);
  });
});
