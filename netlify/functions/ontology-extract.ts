import type { Config, Context } from "@netlify/functions";
import OpenAI from "openai";

import catalog from "../../src/meet_ai/ontology/catalog.v1.json" with { type: "json" };
import { hasValidInternalToken } from "./_shared/internal-auth.js";

const MODEL = "gpt-5-mini";
const MAX_TEXT_LENGTH = 4_000;
const OBJECT_TYPES = new Set(["USER_REQUIREMENT", "PRODUCT", "EXHIBITOR"]);

type Concept = {
  code: string;
  concept_type: string;
  label_ko: string;
  assignable?: boolean;
  data_type?: "CODE" | "NUMBER" | "BOOLEAN" | "TEXT";
  validation?: { min?: number; max?: number };
};

type ExtractionRequest = {
  request_id: string;
  taxonomy_version: string;
  object_type: string;
  locale: string;
  text: string;
  allowed_concept_types?: string[];
};

type ExtractedAttribute = {
  concept_code: string;
  value: string | number | boolean;
  confidence: number;
  evidence: string;
  requirement_level: "REQUIRED" | "PREFERRED" | "ACCEPTABLE" | "EXCLUDED" | null;
  requires_confirmation: boolean;
};

type ExtractionResult = {
  attributes: ExtractedAttribute[];
  unknown_terms: string[];
};

const concepts = catalog.concepts as Concept[];
const conceptByCode = new Map(concepts.map((concept) => [concept.code, concept]));

function json(status: number, body: unknown, requestId: string): Response {
  return Response.json(body, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "X-Request-ID": requestId,
    },
  });
}

function parseRequest(value: unknown): ExtractionRequest | null {
  if (!value || typeof value !== "object") return null;
  const input = value as Record<string, unknown>;
  if (
    typeof input.request_id !== "string" ||
    typeof input.taxonomy_version !== "string" ||
    typeof input.object_type !== "string" ||
    typeof input.locale !== "string" ||
    typeof input.text !== "string"
  ) {
    return null;
  }
  if (!OBJECT_TYPES.has(input.object_type)) return null;
  if (input.text.length < 1 || input.text.length > MAX_TEXT_LENGTH) return null;
  if (input.taxonomy_version !== catalog.metadata.version) return null;
  if (
    input.allowed_concept_types !== undefined &&
    (!Array.isArray(input.allowed_concept_types) ||
      input.allowed_concept_types.some((item) => typeof item !== "string"))
  ) {
    return null;
  }
  return input as ExtractionRequest;
}

function allowedConcepts(input: ExtractionRequest): Concept[] {
  const allowedTypes = new Set(input.allowed_concept_types ?? []);
  return concepts.filter(
    (concept) =>
      concept.assignable !== false &&
      (allowedTypes.size === 0 || allowedTypes.has(concept.concept_type)),
  );
}

function outputSchema(codes: string[]) {
  return {
    type: "object",
    additionalProperties: false,
    required: ["attributes", "unknown_terms"],
    properties: {
      attributes: {
        type: "array",
        maxItems: 30,
        items: {
          type: "object",
          additionalProperties: false,
          required: [
            "concept_code",
            "value",
            "confidence",
            "evidence",
            "requirement_level",
            "requires_confirmation",
          ],
          properties: {
            concept_code: { type: "string", enum: codes },
            value: { anyOf: [{ type: "string" }, { type: "number" }, { type: "boolean" }] },
            confidence: { type: "number", minimum: 0, maximum: 1 },
            evidence: { type: "string", maxLength: 300 },
            requirement_level: {
              anyOf: [
                { type: "string", enum: ["REQUIRED", "PREFERRED", "ACCEPTABLE", "EXCLUDED"] },
                { type: "null" },
              ],
            },
            requires_confirmation: { type: "boolean" },
          },
        },
      },
      unknown_terms: { type: "array", maxItems: 20, items: { type: "string", maxLength: 100 } },
    },
  } as const;
}

function validateResult(result: ExtractionResult, allowedCodes: Set<string>): ExtractionResult {
  const attributes = result.attributes.filter((attribute) => {
    if (!allowedCodes.has(attribute.concept_code)) return false;
    if (attribute.confidence < 0 || attribute.confidence > 1) return false;
    const concept = conceptByCode.get(attribute.concept_code);
    if (!concept) return false;
    if (concept.data_type === "NUMBER") {
      if (typeof attribute.value !== "number") return false;
      if (concept.validation?.min !== undefined && attribute.value < concept.validation.min) return false;
      if (concept.validation?.max !== undefined && attribute.value > concept.validation.max) return false;
    }
    return true;
  });
  return {
    attributes: attributes.map((attribute) => ({
      ...attribute,
      requires_confirmation:
        attribute.requires_confirmation ||
        attribute.requirement_level === "REQUIRED" ||
        attribute.confidence < 0.7,
    })),
    unknown_terms: result.unknown_terms,
  };
}

export default async (req: Request, context: Context) => {
  const requestId = context.requestId;
  if (req.method !== "POST") {
    return json(405, { success: false, error: { code: "METHOD_NOT_ALLOWED" } }, requestId);
  }
  if (!(await hasValidInternalToken(req))) {
    return json(401, { success: false, error: { code: "UNAUTHORIZED" } }, requestId);
  }

  let input: ExtractionRequest | null;
  try {
    input = parseRequest(await req.json());
  } catch {
    input = null;
  }
  if (!input) {
    return json(400, { success: false, error: { code: "INVALID_REQUEST" } }, requestId);
  }

  const allowed = allowedConcepts(input);
  if (allowed.length === 0) {
    return json(400, { success: false, error: { code: "NO_ALLOWED_CONCEPTS" } }, requestId);
  }

  const allowedCodes = allowed.map((concept) => concept.code);
  const compactCatalog = allowed.map((concept) => ({
    code: concept.code,
    type: concept.concept_type,
    label: concept.label_ko,
    value_type: concept.data_type ?? "CODE",
    validation: concept.validation ?? null,
  }));

  try {
    const client = new OpenAI();
    const completion = await client.chat.completions.create({
      model: MODEL,
      store: false,
      messages: [
        {
          role: "system",
          content:
            "Extract only facts supported by the supplied Korean text. Use only allowed codes. " +
            "Never infer sensitive traits. A required condition is only a suggestion and must set " +
            "requires_confirmation=true. Put ambiguous or unsupported expressions in unknown_terms.",
        },
        {
          role: "user",
          content: JSON.stringify({
            object_type: input.object_type,
            locale: input.locale,
            text: input.text,
            allowed_concepts: compactCatalog,
          }),
        },
      ],
      response_format: {
        type: "json_schema",
        json_schema: {
          name: "ontology_extraction",
          strict: true,
          schema: outputSchema(allowedCodes),
        },
      },
    });
    const content = completion.choices[0]?.message.content;
    if (!content) throw new Error("empty model response");
    const result = validateResult(JSON.parse(content) as ExtractionResult, new Set(allowedCodes));
    return json(
      200,
      {
        success: true,
        data: result,
        meta: {
          request_id: input.request_id,
          provider_request_id: completion._request_id ?? null,
          model: MODEL,
          taxonomy_version: input.taxonomy_version,
        },
      },
      requestId,
    );
  } catch (error) {
    console.error("ontology extraction failed", {
      requestId,
      errorType: error instanceof Error ? error.name : "UnknownError",
    });
    return json(
      502,
      { success: false, error: { code: "AI_PROVIDER_UNAVAILABLE", retryable: true } },
      requestId,
    );
  }
};

export const config: Config = {
  path: "/internal/ai/ontology/extract",
  method: "POST",
};

