"""Deterministic, privacy-minimized intent normalization for every input channel.

Natural-language text and canonical import rows terminate at the same versioned intent
structure.  Only concepts in the published ontology can enter the resolved MUST, PREFER,
or EXCLUDE buckets.  Ambiguous text remains unresolved, and model output remains a proposal
that is never promoted into a scoring or hard-filter input by this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from meet_ai.ontology import Catalog, load_catalog
from meet_ai.ontology.catalog import normalize_text

INTENT_NORMALIZATION_COMMAND_V1 = "matching-intent-command-v1.0"
INTENT_NORMALIZATION_RESULT_V1 = "matching-intent-result-v1.0"
INTENT_NORMALIZATION_POLICY_VERSION = "intent-normalization-v1.0"
INTENT_PROPOSAL_SCHEMA_V1 = "intent-proposal-v1.0"

_SAFE_UNKNOWN_FIELD = re.compile(r"^[A-Z][A-Z0-9_.-]{0,63}$")
_EMAIL = re.compile(r"(?i)\b[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
_PHONE = re.compile(
    r"(?<!\d)(?:\+?82[- .]?)?(?:0?1[016789]|0?2|0?[3-6][1-5])"
    r"[- .]?\d{3,4}[- .]?\d{4}(?!\d)"
)
_ONTOLOGY_CODE = re.compile(r"\b[A-Z][A-Z0-9_]*(?:\.[A-Z][A-Z0-9_]*)+\b")
_ASCII_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")
_NEGATIVE_AFTER = re.compile(
    r"^(?:\s|[,/])*(?:제외|빼고|말고|싫|원하지\s*않|exclude\b|except\b)"
)
_NEGATIVE_BEFORE = re.compile(r"(?:\bwithout|\bno|\bnot|\bexclude)\s*$")
_MUST_NEAR = re.compile(r"(?:반드시|필수|꼭|\bmust\b|\brequired\b)")


class IntentNormalizationValidationError(ValueError):
    """Raised when an intent command or proposal violates the fail-closed contract."""


class IntentSource(StrEnum):
    NATURAL_LANGUAGE = "NATURAL_LANGUAGE"
    CANONICAL_PROFILE = "CANONICAL_PROFILE"


class IntentRequirement(StrEnum):
    MUST = "MUST"
    PREFER = "PREFER"
    EXCLUDE = "EXCLUDE"


INTENT_PROPOSAL_JSON_SCHEMA: Mapping[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": INTENT_PROPOSAL_SCHEMA_V1,
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "items"],
    "properties": {
        "schema_version": {"const": INTENT_PROPOSAL_SCHEMA_V1},
        "items": {
            "type": "array",
            "maxItems": 50,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["concept_code", "requirement"],
                "properties": {
                    "concept_code": {"type": "string"},
                    "requirement": {
                        "enum": [item.value for item in IntentRequirement]
                    },
                },
            },
        },
    },
}


@dataclass(frozen=True, slots=True)
class ResolvedIntent:
    concept_code: str
    concept_type: str
    requirement: IntentRequirement
    provenance: str


@dataclass(frozen=True, slots=True)
class UnknownIntent:
    field_code: str
    knowledge_state: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class UnresolvedIntent:
    term_fingerprint: str
    reason_code: str
    candidate_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidatedIntentProposal:
    concept_code: str
    requirement: IntentRequirement
    proposal_state: str = "VALIDATED_PROPOSAL_ONLY"


@dataclass(frozen=True, slots=True, repr=False)
class NaturalLanguageIntentCommand:
    query: str = field(repr=False)
    locale: str = "ko-KR"
    context: str = "ANY"
    contract_version: str = INTENT_NORMALIZATION_COMMAND_V1

    def __post_init__(self) -> None:
        if self.contract_version != INTENT_NORMALIZATION_COMMAND_V1:
            raise IntentNormalizationValidationError(
                f"contract_version must be {INTENT_NORMALIZATION_COMMAND_V1}"
            )
        if not isinstance(self.query, str) or not self.query.strip():
            raise IntentNormalizationValidationError("query must be non-empty text")
        if len(self.query) > 2_000:
            raise IntentNormalizationValidationError("query exceeds 2,000 characters")
        if not re.fullmatch(r"[a-z]{2}(?:-[A-Z]{2})?", self.locale):
            raise IntentNormalizationValidationError("locale is invalid")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,31}", self.context):
            raise IntentNormalizationValidationError("context is invalid")


@dataclass(frozen=True, slots=True)
class CanonicalProfileIntentCommand:
    must_codes: tuple[str, ...] = ()
    prefer_codes: tuple[str, ...] = ()
    exclude_codes: tuple[str, ...] = ()
    unknown_fields: tuple[str, ...] = ()
    contract_version: str = INTENT_NORMALIZATION_COMMAND_V1

    def __post_init__(self) -> None:
        if self.contract_version != INTENT_NORMALIZATION_COMMAND_V1:
            raise IntentNormalizationValidationError(
                f"contract_version must be {INTENT_NORMALIZATION_COMMAND_V1}"
            )
        buckets = {
            IntentRequirement.MUST: tuple(self.must_codes),
            IntentRequirement.PREFER: tuple(self.prefer_codes),
            IntentRequirement.EXCLUDE: tuple(self.exclude_codes),
        }
        seen: dict[str, IntentRequirement] = {}
        for requirement, codes in buckets.items():
            if len(codes) != len(set(codes)):
                raise IntentNormalizationValidationError(
                    f"{requirement.value.lower()}_codes contains duplicates"
                )
            for code in codes:
                previous = seen.setdefault(code, requirement)
                if previous is not requirement:
                    raise IntentNormalizationValidationError(
                        f"concept {code} has conflicting requirements"
                    )
        if len(self.unknown_fields) != len(set(self.unknown_fields)):
            raise IntentNormalizationValidationError("unknown_fields contains duplicates")
        if any(not _SAFE_UNKNOWN_FIELD.fullmatch(value) for value in self.unknown_fields):
            raise IntentNormalizationValidationError(
                "unknown_fields must use privacy-safe field codes"
            )


@dataclass(frozen=True, slots=True)
class NormalizedIntent:
    contract_version: str
    policy_version: str
    ontology_version: str
    source: IntentSource
    must: tuple[ResolvedIntent, ...]
    prefer: tuple[ResolvedIntent, ...]
    exclude: tuple[ResolvedIntent, ...]
    unknown: tuple[UnknownIntent, ...]
    unresolved: tuple[UnresolvedIntent, ...]
    proposals: tuple[ValidatedIntentProposal, ...]
    redacted_input_kinds: tuple[str, ...]
    input_fingerprint: str
    result_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IntentProposalAdapter(Protocol):
    """Optional provider boundary. Returned data is validated but remains proposal-only."""

    def propose(
        self,
        *,
        redacted_query: str,
        locale: str,
        context: str,
        ontology_version: str,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class _TermMatch:
    start: int
    end: int
    term: str
    codes: tuple[str, ...]
    provenance: str


def _fingerprint(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _published_catalog(catalog: Catalog | None) -> Catalog:
    selected = catalog or load_catalog()
    selected.validate()
    if selected.metadata.get("status") != "PUBLISHED":
        raise IntentNormalizationValidationError(
            "intent normalization requires a published ontology"
        )
    return selected


def _redact_query(value: str) -> tuple[str, tuple[str, ...]]:
    kinds: set[str] = set()

    def replace_email(_: re.Match[str]) -> str:
        kinds.add("EMAIL")
        return " [redacted-email] "

    def replace_phone(_: re.Match[str]) -> str:
        kinds.add("PHONE")
        return " [redacted-phone] "

    redacted = _EMAIL.sub(replace_email, value)
    redacted = _PHONE.sub(replace_phone, redacted)
    return normalize_text(redacted), tuple(sorted(kinds))


def _assignable(catalog: Catalog, code: str) -> bool:
    concept = catalog.by_code.get(code)
    return concept is not None and concept.get("assignable", True) is not False


def _require_published_code(catalog: Catalog, code: str) -> dict[str, Any]:
    concept = catalog.by_code.get(code)
    if concept is None:
        raise IntentNormalizationValidationError(
            "intent contains a code outside the published ontology"
        )
    if concept.get("assignable", True) is False:
        raise IntentNormalizationValidationError(
            "intent contains a non-assignable ontology code"
        )
    return concept


def _phrase_spans(text: str, phrase: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        index = text.find(phrase, start)
        if index < 0:
            break
        end = index + len(phrase)
        before_ok = index == 0 or not text[index - 1].isalnum()
        after_ok = end == len(text) or not text[end].isalnum()
        if not after_ok and end < len(text) and text[end] in "은는이가을를과와도만":
            particle_end = end + 1
            after_ok = particle_end == len(text) or not text[particle_end].isalnum()
        if before_ok and after_ok:
            spans.append((index, end))
        start = index + 1
    return tuple(spans)


def _lexicon(catalog: Catalog, *, locale: str, context: str) -> dict[str, dict[str, set[str]]]:
    terms: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    if locale == "ko-KR":
        for concept in catalog.concepts:
            if concept.get("assignable", True) is False:
                continue
            label = normalize_text(str(concept.get("label_ko", "")))
            if label:
                terms[label]["PUBLISHED_LABEL"].add(str(concept["code"]))
    for synonym in catalog.synonyms:
        synonym_context = str(synonym.get("context", "ANY"))
        if synonym.get("locale", "ko-KR") != locale:
            continue
        if synonym_context not in {"ANY", context}:
            continue
        code = str(synonym["concept_code"])
        if _assignable(catalog, code):
            terms[normalize_text(str(synonym["text"]))]["PUBLISHED_SYNONYM"].add(code)
    return terms


def _acronym_candidates(catalog: Catalog, token: str) -> tuple[str, ...]:
    result: set[str] = set()
    upper = token.upper()
    for concept in catalog.concepts:
        code = str(concept.get("code", ""))
        if not _assignable(catalog, code):
            continue
        label = str(concept.get("label_ko", "")).upper()
        code_tokens = re.split(r"[._]", code.upper())
        label_tokens = re.findall(r"[A-Z][A-Z0-9]{1,9}", label)
        if upper in code_tokens or upper in label_tokens:
            result.add(code)
    return tuple(sorted(result))


def _term_matches(
    text: str, catalog: Catalog, *, locale: str, context: str
) -> tuple[_TermMatch, ...]:
    matches: list[_TermMatch] = []
    occupied: list[tuple[int, int]] = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < used_end and end > used_start for used_start, used_end in occupied)

    for match in _ONTOLOGY_CODE.finditer(text.upper()):
        code = match.group(0)
        if _assignable(catalog, code):
            matches.append(
                _TermMatch(match.start(), match.end(), code, (code,), "EXACT_CODE")
            )
            occupied.append((match.start(), match.end()))

    lexicon = _lexicon(catalog, locale=locale, context=context)
    for phrase in sorted(lexicon, key=lambda value: (-len(value), value)):
        provenance_map = lexicon[phrase]
        codes = tuple(sorted({code for values in provenance_map.values() for code in values}))
        provenance = "+".join(sorted(provenance_map))
        for start, end in _phrase_spans(text, phrase):
            if overlaps(start, end):
                continue
            matches.append(_TermMatch(start, end, phrase, codes, provenance))
            occupied.append((start, end))

    for match in _ASCII_TOKEN.finditer(text.upper()):
        if overlaps(match.start(), match.end()):
            continue
        codes = _acronym_candidates(catalog, match.group(0))
        if codes:
            matches.append(
                _TermMatch(
                    match.start(), match.end(), match.group(0), codes, "PUBLISHED_ACRONYM"
                )
            )
            occupied.append((match.start(), match.end()))
    return tuple(sorted(matches, key=lambda item: (item.start, item.end, item.codes)))


def _requirement(text: str, start: int, end: int) -> IntentRequirement:
    before = text[max(0, start - 24) : start]
    after = text[end : min(len(text), end + 24)]
    if _NEGATIVE_AFTER.search(after) or _NEGATIVE_BEFORE.search(before):
        return IntentRequirement.EXCLUDE
    if _MUST_NEAR.search(before[-16:]) or _MUST_NEAR.search(after[:16]):
        return IntentRequirement.MUST
    return IntentRequirement.PREFER


def validate_intent_proposal(
    value: Mapping[str, Any], *, catalog: Catalog | None = None
) -> tuple[ValidatedIntentProposal, ...]:
    """Validate a provider proposal without promoting it into resolved intent buckets."""

    selected = _published_catalog(catalog)
    if not isinstance(value, Mapping) or set(value) != {"schema_version", "items"}:
        raise IntentNormalizationValidationError("proposal must match the strict schema")
    if value.get("schema_version") != INTENT_PROPOSAL_SCHEMA_V1:
        raise IntentNormalizationValidationError(
            f"proposal schema_version must be {INTENT_PROPOSAL_SCHEMA_V1}"
        )
    raw_items = value.get("items")
    if not isinstance(raw_items, list) or len(raw_items) > 50:
        raise IntentNormalizationValidationError("proposal items must be an array of at most 50")
    proposals: list[ValidatedIntentProposal] = []
    seen: set[tuple[str, IntentRequirement]] = set()
    for item in raw_items:
        if not isinstance(item, Mapping) or set(item) != {"concept_code", "requirement"}:
            raise IntentNormalizationValidationError("proposal item must match the strict schema")
        code = item.get("concept_code")
        if not isinstance(code, str):
            raise IntentNormalizationValidationError("proposal concept_code must be text")
        _require_published_code(selected, code)
        try:
            requirement = IntentRequirement(item.get("requirement"))
        except ValueError as exc:
            raise IntentNormalizationValidationError(
                "proposal requirement must be MUST, PREFER, or EXCLUDE"
            ) from exc
        key = (code, requirement)
        if key not in seen:
            proposals.append(ValidatedIntentProposal(code, requirement))
            seen.add(key)
    return tuple(sorted(proposals, key=lambda item: (item.requirement.value, item.concept_code)))


def _resolved(
    catalog: Catalog,
    entries: Sequence[tuple[str, IntentRequirement, str]],
) -> tuple[tuple[ResolvedIntent, ...], tuple[UnresolvedIntent, ...]]:
    by_code: dict[str, list[tuple[IntentRequirement, str]]] = defaultdict(list)
    for code, requirement, provenance in entries:
        by_code[code].append((requirement, provenance))
    resolved: list[ResolvedIntent] = []
    unresolved: list[UnresolvedIntent] = []
    for code, values in sorted(by_code.items()):
        requirements = {item[0] for item in values}
        if len(requirements) != 1:
            unresolved.append(
                UnresolvedIntent(
                    _fingerprint({"code": code, "reason": "CONFLICTING_REQUIREMENTS"}),
                    "CONFLICTING_REQUIREMENTS",
                    (code,),
                )
            )
            continue
        requirement = next(iter(requirements))
        concept = _require_published_code(catalog, code)
        provenance = "+".join(sorted({item[1] for item in values}))
        resolved.append(
            ResolvedIntent(code, str(concept["concept_type"]), requirement, provenance)
        )
    return tuple(resolved), tuple(unresolved)


def _build_result(
    *,
    catalog: Catalog,
    source: IntentSource,
    resolved: Sequence[ResolvedIntent],
    unknown: Sequence[UnknownIntent],
    unresolved: Sequence[UnresolvedIntent],
    proposals: Sequence[ValidatedIntentProposal],
    redacted_input_kinds: Sequence[str],
    input_payload: object,
) -> NormalizedIntent:
    ordered = tuple(sorted(resolved, key=lambda item: (item.requirement.value, item.concept_code)))
    buckets = {
        requirement: tuple(item for item in ordered if item.requirement is requirement)
        for requirement in IntentRequirement
    }
    normalized_unknown = tuple(sorted(unknown, key=lambda item: item.field_code))
    normalized_unresolved = tuple(
        sorted(unresolved, key=lambda item: (item.reason_code, item.candidate_codes, item.term_fingerprint))
    )
    normalized_proposals = tuple(
        sorted(proposals, key=lambda item: (item.requirement.value, item.concept_code))
    )
    input_fingerprint = _fingerprint(input_payload)
    result_payload = {
        "contract_version": INTENT_NORMALIZATION_RESULT_V1,
        "policy_version": INTENT_NORMALIZATION_POLICY_VERSION,
        "ontology_version": catalog.version,
        "source": source.value,
        "must": [asdict(item) for item in buckets[IntentRequirement.MUST]],
        "prefer": [asdict(item) for item in buckets[IntentRequirement.PREFER]],
        "exclude": [asdict(item) for item in buckets[IntentRequirement.EXCLUDE]],
        "unknown": [asdict(item) for item in normalized_unknown],
        "unresolved": [asdict(item) for item in normalized_unresolved],
        "proposals": [asdict(item) for item in normalized_proposals],
        "redacted_input_kinds": sorted(set(redacted_input_kinds)),
        "input_fingerprint": input_fingerprint,
    }
    return NormalizedIntent(
        contract_version=INTENT_NORMALIZATION_RESULT_V1,
        policy_version=INTENT_NORMALIZATION_POLICY_VERSION,
        ontology_version=catalog.version,
        source=source,
        must=buckets[IntentRequirement.MUST],
        prefer=buckets[IntentRequirement.PREFER],
        exclude=buckets[IntentRequirement.EXCLUDE],
        unknown=normalized_unknown,
        unresolved=normalized_unresolved,
        proposals=normalized_proposals,
        redacted_input_kinds=tuple(sorted(set(redacted_input_kinds))),
        input_fingerprint=input_fingerprint,
        result_fingerprint=_fingerprint(result_payload),
    )


def normalize_natural_language_intent(
    command: NaturalLanguageIntentCommand,
    *,
    catalog: Catalog | None = None,
    proposal_adapter: IntentProposalAdapter | None = None,
) -> NormalizedIntent:
    selected = _published_catalog(catalog)
    redacted_query, redaction_kinds = _redact_query(command.query)
    matches = _term_matches(
        redacted_query, selected, locale=command.locale, context=command.context
    )
    entries: list[tuple[str, IntentRequirement, str]] = []
    unresolved: list[UnresolvedIntent] = []
    for match in matches:
        requirement = _requirement(redacted_query, match.start, match.end)
        if len(match.codes) != 1:
            unresolved.append(
                UnresolvedIntent(
                    _fingerprint(
                        {
                            "term": match.term,
                            "requirement": requirement.value,
                            "ontology_version": selected.version,
                        }
                    ),
                    "AMBIGUOUS_PUBLISHED_TERM",
                    match.codes,
                )
            )
            continue
        entries.append((match.codes[0], requirement, match.provenance))
    resolved, conflicts = _resolved(selected, entries)
    unresolved.extend(conflicts)
    if not matches:
        unresolved.append(
            UnresolvedIntent(
                _fingerprint(
                    {"query": redacted_query, "ontology_version": selected.version}
                ),
                "NO_PUBLISHED_MAPPING",
            )
        )
    proposals: tuple[ValidatedIntentProposal, ...] = ()
    if proposal_adapter is not None:
        raw_proposal = proposal_adapter.propose(
            redacted_query=redacted_query,
            locale=command.locale,
            context=command.context,
            ontology_version=selected.version,
        )
        proposals = validate_intent_proposal(raw_proposal, catalog=selected)
    return _build_result(
        catalog=selected,
        source=IntentSource.NATURAL_LANGUAGE,
        resolved=resolved,
        unknown=(),
        unresolved=unresolved,
        proposals=proposals,
        redacted_input_kinds=redaction_kinds,
        input_payload={
            "contract_version": command.contract_version,
            "source": IntentSource.NATURAL_LANGUAGE.value,
            "query": redacted_query,
            "locale": command.locale,
            "context": command.context,
            "ontology_version": selected.version,
        },
    )


def normalize_canonical_profile_intent(
    command: CanonicalProfileIntentCommand, *, catalog: Catalog | None = None
) -> NormalizedIntent:
    selected = _published_catalog(catalog)
    entries: list[tuple[str, IntentRequirement, str]] = []
    for requirement, codes in (
        (IntentRequirement.MUST, command.must_codes),
        (IntentRequirement.PREFER, command.prefer_codes),
        (IntentRequirement.EXCLUDE, command.exclude_codes),
    ):
        for code in codes:
            _require_published_code(selected, code)
            entries.append((code, requirement, "CANONICAL_PROFILE"))
    resolved, conflicts = _resolved(selected, entries)
    if conflicts:
        raise IntentNormalizationValidationError(
            "canonical profile contains conflicting requirements"
        )
    unknown = tuple(UnknownIntent(field_code) for field_code in command.unknown_fields)
    return _build_result(
        catalog=selected,
        source=IntentSource.CANONICAL_PROFILE,
        resolved=resolved,
        unknown=unknown,
        unresolved=(),
        proposals=(),
        redacted_input_kinds=(),
        input_payload={
            "contract_version": command.contract_version,
            "source": IntentSource.CANONICAL_PROFILE.value,
            "must_codes": sorted(command.must_codes),
            "prefer_codes": sorted(command.prefer_codes),
            "exclude_codes": sorted(command.exclude_codes),
            "unknown_fields": sorted(command.unknown_fields),
            "ontology_version": selected.version,
        },
    )
