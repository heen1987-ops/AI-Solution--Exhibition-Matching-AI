import { performance } from "node:perf_hooks";

const USER_WEB_BASE_URL = trimTrailingSlash(
  process.env.USER_WEB_BASE_URL ?? "http://127.0.0.1:3300",
);
const ADMIN_BASE_URL = trimTrailingSlash(
  process.env.ADMIN_BASE_URL ?? "http://127.0.0.1:3320",
);
const ITERATIONS = Number.parseInt(process.env.PERF_ITERATIONS ?? "8", 10);
const WARMUP_ITERATIONS = Number.parseInt(process.env.PERF_WARMUP_ITERATIONS ?? "2", 10);
const STRICT = process.env.PERF_STRICT === "1";

const targets = [
  {
    name: "registered-web-home",
    url: `${USER_WEB_BASE_URL}/home`,
    productionP95Ms: 1_000,
    localSmokeP95Ms: 2_500,
  },
  {
    name: "registered-web-recommendations",
    url: `${USER_WEB_BASE_URL}/recommendations`,
    productionP95Ms: 3_000,
    localSmokeP95Ms: 3_500,
  },
  {
    name: "guest-web-search",
    url: `${USER_WEB_BASE_URL}/search?q=${encodeURIComponent("목재")}&mode=GUEST_WEB`,
    productionP95Ms: 2_000,
    localSmokeP95Ms: 3_500,
  },
  {
    name: "company-detail",
    url: `${USER_WEB_BASE_URL}/companies/11111111-1111-4111-8111-111111111111`,
    productionP95Ms: 1_000,
    localSmokeP95Ms: 2_500,
  },
  {
    name: "admin-console",
    url: `${ADMIN_BASE_URL}/console`,
    productionP95Ms: 1_500,
    localSmokeP95Ms: 3_000,
  },
];

const failures = [];
const results = [];

for (const target of targets) {
  await warmup(target);
  const samples = [];
  for (let index = 0; index < ITERATIONS; index += 1) {
    samples.push(await measure(target));
  }
  samples.sort((left, right) => left - right);
  const p95 = percentile(samples, 95);
  const max = samples.at(-1) ?? 0;
  const threshold = STRICT ? target.productionP95Ms : target.localSmokeP95Ms;
  const passed = p95 <= threshold;
  results.push({
    ...target,
    p95,
    max,
    threshold,
    mode: STRICT ? "production-target" : "local-smoke",
    passed,
  });
  if (!passed) {
    failures.push(
      `${target.name}: p95=${formatMs(p95)} exceeded ${STRICT ? "production" : "local smoke"} threshold ${threshold}ms`,
    );
  }
}

for (const result of results) {
  console.log(
    [
      result.passed ? "PASS" : "FAIL",
      result.name,
      `p95=${formatMs(result.p95)}`,
      `max=${formatMs(result.max)}`,
      `threshold=${result.threshold}ms`,
      `production_target=${result.productionP95Ms}ms`,
      `mode=${result.mode}`,
    ].join(" "),
  );
}

if (failures.length > 0) {
  console.error(`\nPerformance smoke failed:\n- ${failures.join("\n- ")}`);
  process.exit(1);
}

function trimTrailingSlash(value) {
  return value.replace(/\/+$/, "");
}

async function warmup(target) {
  for (let index = 0; index < WARMUP_ITERATIONS; index += 1) {
    await measure(target);
  }
}

async function measure(target) {
  const startedAt = performance.now();
  const response = await fetch(target.url, {
    redirect: "follow",
    headers: { "User-Agent": "meet-ai-performance-smoke/1.0" },
  });
  await response.arrayBuffer();
  const elapsedMs = performance.now() - startedAt;
  if (!response.ok) {
    throw new Error(`${target.name} returned HTTP ${response.status} for ${target.url}`);
  }
  return elapsedMs;
}

function percentile(samples, percentileValue) {
  const index = Math.ceil((percentileValue / 100) * samples.length) - 1;
  return samples[Math.max(0, Math.min(index, samples.length - 1))] ?? 0;
}

function formatMs(value) {
  return `${value.toFixed(1)}ms`;
}
