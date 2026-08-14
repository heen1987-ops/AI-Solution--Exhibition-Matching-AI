import type { Config, Context } from "@netlify/functions";
import OpenAI from "openai";

import catalog from "../../src/meet_ai/ontology/catalog.v1.json" with { type: "json" };
import { hasValidInternalToken } from "./_shared/internal-auth.js";

const MODEL = "gpt-5-mini";
const PROMPT_VERSION = "conversation-extract-v1.0";
const MAX_TEXT_LENGTH = 2_000;
const ALLOWED_INTENTS = [
  "INTENT.SET_GOAL",
  "INTENT.SET_PREFERENCE",
  "INTENT.SET_CONSTRAINT",
  "INTENT.EXCLUDE",
  "INTENT.MODIFY",
  "INTENT.REMOVE",
  "INTENT.REQUEST_RECOMMENDATION",
  "INTENT.COMPARE",
  "INTENT.ASK_REASON",
  "INTENT.ASK_ROUTE",
  "INTENT.REQUEST_MEETING",
  "INTENT.UNKNOWN",
] as const;
const ALLOWED_OPERATORS = [
  "EQUAL",
  "NOT_EQUAL",
  "IN",
  "NOT_IN",
  "GREATER_THAN",
  "GREATER_THAN_OR_EQUAL",
  "LESS_THAN",
  "LESS_THAN_OR_EQUAL",
  "BETWEEN",
  "APPROXIMATE",
] as const;
const ALLOWED_REQUIREMENTS = ["REQUIRED", "PREFERRED", "ACCEPTABLE", "EXCLUDED"] as const;
const ALLOWED_CONCEPT_TYPES = new Set([
  "VISIT_GOAL",
  "BUSINESS_GOAL",
  "PRODUCT_CATEGORY",
  "TASTE",
  "AROMA",
  "ALCOHOL_LEVEL",
  "PRICE_BAND",
  "USE_CASE",
  "CHANNEL",
  "REGION",
  "TRADE_TYPE",
  "MEETING_TOPIC",
]);

type Concept = {
  code: string;
  concept_type: string;
  label_ko: string;
  assignable?: boolean;
};

type Synonym = {
  text: string;
  concept_code: string;
  locale: string;
  context: string;
};

type ConversationRequest = {
  request_id: string;
  locale: string;
  user_type: "GENERAL_VISITOR" | "BUYER";
  masked_text: string;
  existing_codes: string[];
};

type ModelEntity = {
  attribute_code: string;
  operator: (typeof ALLOWED_OPERATORS)[number];
  value: string | number | boolean;
  unit: string | null;
  requirement_level: (typeof ALLOWED_REQUIREMENTS)[number];
  evidence: string;
  confidence: number;
  requires_confirmation: boolean;
};

type ModelResult = {
  intent_code: (typeof ALLOWED_INTENTS)[number];
  intent_confidence: number;
  entities: ModelEntity[];
  ambiguities: string[];
};

const concepts = (catalog.concepts as Concept[]).filter(
  (concept) => concept.assignable !== false && ALLOWED_CONCEPT_TYPES.has(concept.concept_type),
);
const synonyms = catalog.synonyms as Synonym[];
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

function parseRequest(value: unknown): ConversationRequest | null {
  if (!value || typeof value !== "object") return null;
  const input = value as Record<string, unknown>;
  if (
    typeof input.request_id !== "string" ||
    typeof input.locale !== "string" ||
    (input.user_type !== "GENERAL_VISITOR" && input.user_type !== "BUYER") ||
    typeof input.masked_text !== "string" ||
    !Array.isArray(input.existing_codes) ||
    input.existing_codes.some((item) => typeof item !== "string")
  ) {
    return null;
  }
  if (input.masked_text.length < 1 || input.masked_text.length > MAX_TEXT_LENGTH) return null;
  return input as ConversationRequest;
}

function outputSchema(codes: string[]) {
  return {
    type: "object",
    additionalProperties: false,
    required: ["intent_code", "intent_confidence", "entities", "ambiguities"],
    properties: {
      intent_code: { type: "string", enum: ALLOWED_INTENTS },
      intent_confidence: { type: "number", minimum: 0, maximum: 1 },
      entities: {
        type: "array",
        maxItems: 20,
        items: {
          type: "object",
          additionalProperties: false,
          required: [
            "attribute_code",
            "operator",
            "value",
            "unit",
            "requirement_level",
            "evidence",
            "confidence",
            "requires_confirmation",
          ],
          properties: {
            attribute_code: { type: "string", enum: codes },
            operator: { type: "string", enum: ALLOWED_OPERATORS },
            value: {
              anyOf: [{ type: "string" }, { type: "number" }, { type: "boolean" }],
            },
            unit: { anyOf: [{ type: "string", maxLength: 20 }, { type: "null" }] },
            requirement_level: { type: "string", enum: ALLOWED_REQUIREMENTS },
            evidence: { type: "string", minLength: 1, maxLength: 120 },
            confidence: { type: "number", minimum: 0, maximum: 1 },
            requires_confirmation: { type: "boolean" },
          },
        },
      },
      ambiguities: {
        type: "array",
        maxItems: 10,
        items: { type: "string", minLength: 1, maxLength: 80 },
      },
    },
  } as const;
}

function validateResult(result: ModelResult, input: ConversationRequest): ModelResult {
  const visibleText = input.masked_text.toLocaleLowerCase(input.locale);
  const seen = new Set<string>();
  const entities = result.entities.filter((entity) => {
    if (!conceptByCode.has(entity.attribute_code) || seen.has(entity.attribute_code)) return false;
    if (!visibleText.includes(entity.evidence.toLocaleLowerCase(input.locale))) return false;
    if (entity.confidence < 0 || entity.confidence > 1) return false;
    seen.add(entity.attribute_code);
    return true;
  });
  return {
    intent_code: ALLOWED_INTENTS.includes(result.intent_code) ? result.intent_code : "INTENT.UNKNOWN",
    intent_confidence: Math.min(Math.max(result.intent_confidence, 0), 1),
    entities: entities.map((entity) => ({
      ...entity,
      requires_confirmation: true,
    })),
    ambiguities: result.ambiguities,
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

  let input: ConversationRequest | null;
  try {
    input = parseRequest(await req.json());
  } catch {
    input = null;
  }
  if (!input) {
    return json(400, { success: false, error: { code: "INVALID_REQUEST" } }, requestId);
  }

  const compactCatalog = concepts.map((concept) => ({
    code: concept.code,
    type: concept.concept_type,
    label: concept.label_ko,
    synonyms: synonyms
      .filter((synonym) => synonym.concept_code === concept.code)
      .map((synonym) => synonym.text),
  }));
  const allowedCodes = concepts.map((concept) => concept.code);

  try {
    const client = new OpenAI();
    const completion = await client.chat.completions.create({
      model: MODEL,
      store: false,
      messages: [
        {
          role: "system",
          content:
            "Extract only conditions explicitly supported by the masked user text. " +
            "Never infer age, gender, health, income, identity, or contact information. " +
            "Use only the supplied ontology codes. Copy a short exact evidence substring. " +
            "Do not rank or recommend candidates. Every extraction requires user confirmation. " +
            "When a Korean expression is ambiguous, omit the entity and report the ambiguity.",
        },
        {
          role: "user",
          content: JSON.stringify({
            locale: input.locale,
            user_type: input.user_type,
            masked_text: input.masked_text,
            existing_codes: input.existing_codes,
            allowed_concepts: compactCatalog,
          }),
        },
      ],
      response_format: {
        type: "json_schema",
        json_schema: {
          name: "conversation_extraction",
          strict: true,
          schema: outputSchema(allowedCodes),
        },
      },
    });
    const content = completion.choices[0]?.message.content;
    if (!content) throw new Error("empty model response");
    const result = validateResult(JSON.parse(content) as ModelResult, input);
    return json(
      200,
      {
        success: true,
        data: result,
        meta: {
          request_id: input.request_id,
          provider_request_id: completion._request_id ?? null,
          model: MODEL,
          prompt_version: PROMPT_VERSION,
          taxonomy_version: catalog.metadata.version,
        },
      },
      requestId,
    );
  } catch (error) {
    console.error("conversation extraction failed", {
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
  path: "/internal/ai/conversation/extract",
  method: "POST",
};
