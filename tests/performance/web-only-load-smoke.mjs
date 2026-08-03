import { performance } from "node:perf_hooks";

const USER_WEB_BASE_URL = trimTrailingSlash(
  process.env.USER_WEB_BASE_URL ?? "http://127.0.0.1:3300",
);
const ADMIN_BASE_URL = trimTrailingSlash(
  process.env.ADMIN_BASE_URL ?? "http://127.0.0.1:3320",
);
const DURATION_SECONDS = Number.parseInt(process.env.LOAD_DURATION_SECONDS ?? "15", 10);
const CONCURRENCY = Number.parseInt(process.env.LOAD_CONCURRENCY ?? "4", 10);
const STRICT = process.env.LOAD_STRICT === "1";
const MAX_ERROR_RATE = Number.parseFloat(process.env.LOAD_MAX_ERROR_RATE ?? "0");

const targets = [
  {
    name: "registered-web-home",
    url: `${USER_WEB_BASE_URL}/home`,
    productionP95Ms: 1_000,
    localLoadP95Ms: 2_500,
    weight: 3,
  },
  {
    name: "registered-web-recommendations",
    url: `${USER_WEB_BASE_URL}/recommendations`,
    productionP95Ms: 3_000,
    localLoadP95Ms: 3_500,
    weight: 2,
  },
  {
    name: "guest-web-search",
    url: `${USER_WEB_BASE_URL}/search?q=${encodeURIComponent("목재")}&mode=GUEST_WEB`,
    productionP95Ms: 2_000,
    localLoadP95Ms: 3_500,
    weight: 2,
  },
  {
    name: "company-detail",
    url: `${USER_WEB_BASE_URL}/companies/11111111-1111-4111-8111-111111111111`,
    productionP95Ms: 1_000,
    localLoadP95Ms: 2_500,
    weight: 2,
  },
  {
    name: "admin-console",
    url: `${ADMIN_BASE_URL}/console`,
    productionP95Ms: 1_500,
    localLoadP95Ms: 3_000,
    weight: 1,
  },
];

const targetPlan = expandTargets(targets);
const results = new Map(
  targets.map((target) => [
    target.name,
    {
      ...target,
      durations: [],
      errors: 0,
    },
  ]),
);

let nextTargetIndex = 0;
const startedAt = performance.now();
const deadline = startedAt + DURATION_SECONDS * 1_000;

await Promise.all(
  Array.from({ length: CONCURRENCY }, (_, workerIndex) => runWorker(workerIndex)),
);

const failures = [];

for (const result of results.values()) {
  result.durations.sort((left, right) => left - right);
  const count = result.durations.length + result.errors;
  const p95 = percentile(result.durations, 95);
  const max = result.durations.at(-1) ?? 0;
  const errorRate = count === 0 ? 1 : result.errors / count;
  const threshold = STRICT ? result.productionP95Ms : result.localLoadP95Ms;
  const passed = p95 <= threshold && errorRate <= MAX_ERROR_RATE && result.durations.length > 0;

  console.log(
    [
      passed ? "PASS" : "FAIL",
      result.name,
      `requests=${count}`,
      `errors=${result.errors}`,
      `error_rate=${(errorRate * 100).toFixed(2)}%`,
      `p95=${formatMs(p95)}`,
      `max=${formatMs(max)}`,
      `threshold=${threshold}ms`,
      `mode=${STRICT ? "production-target" : "local-load"}`,
    ].join(" "),
  );

  if (!passed) {
    failures.push(
      `${result.name}: requests=${count}, errors=${result.errors}, p95=${formatMs(p95)}, threshold=${threshold}ms`,
    );
  }
}

if (failures.length > 0) {
  console.error(`\nLoad smoke failed:\n- ${failures.join("\n- ")}`);
  process.exit(1);
}

async function runWorker(workerIndex) {
  while (performance.now() < deadline) {
    const target = nextTarget(workerIndex);
    const result = results.get(target.name);
    const started = performance.now();
    try {
      const response = await fetch(target.url, {
        redirect: "follow",
        headers: { "User-Agent": "meet-ai-load-smoke/1.0" },
      });
      await response.arrayBuffer();
      const elapsedMs = performance.now() - started;
      if (!response.ok) {
        result.errors += 1;
      } else {
        result.durations.push(elapsedMs);
      }
    } catch {
      result.errors += 1;
    }
  }
}

function nextTarget(workerIndex) {
  const currentIndex = nextTargetIndex;
  nextTargetIndex = (nextTargetIndex + 1) % targetPlan.length;
  return targetPlan[(currentIndex + workerIndex) % targetPlan.length];
}

function expandTargets(items) {
  return items.flatMap((item) => Array.from({ length: item.weight }, () => item));
}

function trimTrailingSlash(value) {
  return value.replace(/\/+$/, "");
}

function percentile(samples, percentileValue) {
  if (samples.length === 0) {
    return Number.POSITIVE_INFINITY;
  }
  const index = Math.ceil((percentileValue / 100) * samples.length) - 1;
  return samples[Math.max(0, Math.min(index, samples.length - 1))] ?? 0;
}

function formatMs(value) {
  if (!Number.isFinite(value)) {
    return "Infinity";
  }
  return `${value.toFixed(1)}ms`;
}
