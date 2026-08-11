import { describe, expect, it } from "vitest";

import { MESSAGE_TYPES } from "../../event-message/types";
import { findTemplate, STARTER_TEMPLATES, templatesForMessageType } from "../logic";

describe("STARTER_TEMPLATES", () => {
  it("provides at least one starter template for every operator-authorable message type", () => {
    for (const messageType of MESSAGE_TYPES) {
      expect(templatesForMessageType(messageType).length).toBeGreaterThan(0);
    }
  });

  it("never includes a disallowed tag in any starter body (script/img/etc)", () => {
    const disallowedTagPattern = /<(script|img|iframe|style|object|embed|form|svg)[\s>]/i;
    for (const template of STARTER_TEMPLATES) {
      expect(disallowedTagPattern.test(template.body)).toBe(false);
    }
  });

  it("every starter destination_screen is an internal route", () => {
    for (const template of STARTER_TEMPLATES) {
      expect(template.destination_screen.startsWith("/")).toBe(true);
      expect(template.destination_screen.startsWith("//")).toBe(false);
      expect(template.destination_screen.includes("://")).toBe(false);
    }
  });

  it("findTemplate resolves a known id and returns undefined for an unknown one", () => {
    expect(findTemplate("event-operation-notice-default")?.message_type).toBe(
      "EVENT_OPERATION_NOTICE",
    );
    expect(findTemplate("does-not-exist")).toBeUndefined();
  });
});
