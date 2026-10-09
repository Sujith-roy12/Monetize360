# Research synthesis, source inspiration and limits

## Domain analysis informing the design

The official problem statement is the source of truth. The scenarios below are illustrative policies, not claims that any real business uses these precise thresholds or percentages.

| Domain | Relevant context | Composition and timing | Constraints / explanation |
|---|---|---|---|
| Hospitality | Nights, occupancy, arrival date, membership | Per-night base, demand premium, member discount, date surcharge; evaluate each quote | Quantity-aware floor, explicit percent basis, itemized booking amount |
| Tours | Party size, package category, guide selection | Per-person base, exclusive group tiers, package and guide adjustments | Avoid stacking mutually exclusive group discounts; disclose tier winner |
| Car rental | Rental days, vehicle category, pickup location, membership | Duration base, weekly/member competition, location fee | Minimum per-day amount, deterministic priority, fee after discount |
| Illustrative rate | Risk category, tenure | Base percentage rate plus basis-point changes | Rate units differ from money; min/max rate; no credit recommendation |
| Logistics example | Distance, weight, urgency | Distance base, weight surcharge, urgent fee | Delivery floor/cap; new attributes without source edits |

Common abstractions: typed transaction context, priced unit, base expression, conditional adjustments, conflicts, hard bounds and a versioned explanation. Important differences: quantity semantics, categorical/date inputs, exclusive offers, output units, and operational data freshness. Context is supplied by the caller; the prototype does not poll external inventory or market feeds.

This is an engineering synthesis of the supplied brief and reference repositories, not a comprehensive empirical industry study. For submission, validate business assumptions with domain stakeholders rather than presenting invented policies as measured practice.

## GitHub references

The following user-provided repositories informed architecture review:

- https://github.com/durkeshkumar/dynamic-pricing-business-rules-engine — product/administration/API separation inspired the catalog and policy-workspace split.
- https://github.com/shaikmali010/dynamic-pricing-engine — strategy abstraction inspired a shared execution contract; this implementation avoids adding a new hardcoded class per industry.
- https://github.com/aperezgdev/princing-rule-engine — configurable rule-set and explanation concepts informed composable conditions/actions. Here price and explanation come from the same evaluator.
- https://github.com/krishsaini777/dynamic-pricing-engine — separation of model ideas from business guardrails informed the decision to keep optional AI outside authoritative execution.

V2 is an independent Python/React implementation, not a merge of these repositories, and it does not claim to use every idea or reproduce their capabilities. No third-party repository source was copied into this project. Package dependencies retain their upstream licenses. Repository inspiration is not proof that this implementation is validated or production-safe.

## What is not implemented / not claimed

- No trained demand model, real sales dataset, learned price elasticity, optimizer, revenue-uplift evidence or GPU training pipeline.
- No guarantee that synthetic policy fixtures correspond to market-optimal prices.
- No full account system, tenant isolation, SSO, per-user approval identities or immutable external audit log. Tokens identify roles only.
- No authorization on demo read/pricing/history endpoints. Do not put private customer attributes into a shared public deployment.
- No rate limiting, request-body size cap at gateway, production load testing, migration framework, signed configurations, distributed cache or automatic rollback.
- Conflict validation catches duplicate IDs, invalid references/types, exclusive-group priority ties and runtime bound infeasibility. It does not mathematically prove all condition overlaps or business consistency.
- Expression/condition depth, attribute/rule/scenario counts are limited, but this is not a hardened untrusted-code service. Only trusted business editors should author configurations.
- Required new inputs can break callers even when product defaults remain valid. Validate API contracts and representative scenarios before publishing.
- Effective dates are rule-level. No scheduler for automatic version activation, retirement, or external context freshness checks.
- Multi-worker concurrent first-start seeding is not supported; use the provided single-worker launch for the prototype.
- SQLite is for local demo usage. PostgreSQL configuration is supplied but has not been run here.
- Browser build success does not establish runtime UI correctness. The included browser smoke test must be run after installing its dependencies.
- Optional provider integration depends on current model availability, account permissions, internet access, and billing. It was not live-tested.

## Verification record

Executed successfully in the build environment:

1. `python -m unittest discover -s tests -p test_engine.py -v`: 36 tests, including all 11 seeded scenarios.
2. `python -m compileall -q backend scripts tests`: Python compilation.
3. `npm run build` in frontend: Vite production bundle.

Not executed here: `pytest` API tests, real HTTP pipeline, Playwright UI smoke, PostgreSQL/Docker stack, live Gemini. Backend dependency downloads were denied by environment network policy. No workaround or invented success results were used. The README provides exact local verification commands.
