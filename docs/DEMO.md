# Four-minute judge demo

## Before presenting

Install dependencies and run `python scripts/verify_pipeline.py --browser` if Playwright is installed; otherwise run the default verifier and manually rehearse the UI. Start with `python scripts/run_local.py`. Connect publisher access. Keep `examples/logistics.strategy.json` open as a reusable example, and have the Car rental strategy selected in a second tab if useful. Do not claim the prepared logistics configuration is an unseen judge challenge.

## 0:00–0:35 — The problem

“Companies should not rebuild pricing software for every industry. Monetize360 lets businesses define their own inputs and policies, then runs all of them through one deterministic interpreter.”

Show Overview and actual four policies. State that numbers are illustrative policy scenarios, not real revenue.

## 0:35–1:20 — Price and explain

Pricing studio → Car rental → Calculate: ₹14,900.

Explain: 8 × ₹2,000 = ₹16,000; weekly SUV discount −₹1,600; airport charge +₹500. Show matching conditions and the skipped member rule. Toggle member on and recalculate: the competing discount does not stack because the weekly discount wins its exclusive group.

Switch to Hospitality and calculate ₹6,480; switch to Tours and calculate ₹28,000. “Same endpoint, same engine, different configuration.”

## 1:20–2:05 — Test safely

Simulation lab → Car rental, compare v1 against v1. Disable Weekly SUV discount and compare. The default scenario changes from ₹14,900 to ₹16,500. Explain that this is a policy counterfactual, **not a revenue prediction**. Show that the live policy was not modified.

## 2:05–3:15 — New-domain configuration

Strategy studio → Clone as new domain → YAML / JSON. Replace editor content with `examples/logistics.strategy.json` and Load into visual editor. Show its new distance, weight and urgency attributes. Validate & test → Save draft version → Approve version → Publish version.

Products → New product: ID `logistics_demo`, name `Express delivery`, strategy Logistics delivery, base rate `20`, defaults `{}` → Create product.

Pricing studio → Express delivery → Calculate: ₹1,550. The form was generated from the schema. No engine code changed.

For a truly unseen judge domain, define its attributes, quantity/base semantics, conditions, actions, units, constraints, and two expected outcomes. If it needs an unsupported operation (e.g. actuarial risk computation), say so; configuring any arbitrary algorithm is not claimed.

## 3:15–4:00 — Trust and control

Decision history → Replay. Show matching original price and trace. Strategy studio → demonstrate immutable versions and approval controls. Explain rollback reactivates an earlier published configuration and does not rewrite old decisions.

Close: “One pricing brain, multiple industries, configuration instead of redevelopment. Businesses own the policy; the platform makes execution explainable and reproducible.”

## Likely judge questions

- **Is this just rules?** It is a reusable policy language with typed input schemas, safe formulas, conflict semantics, versioning, simulations and exact explanations. Rules are intentional because the statement makes AI optional and demands business control.
- **Where is AI?** Optional natural-language configuration drafting with an actual provider adapter. Core pricing does not depend on an LLM. No ML training is claimed.
- **Where is the dataset?** The YAML files contain independently labelled regression cases, not training data. Real optimization would require demand/conversion observations across prices.
- **Can this handle every industry?** It supports new policies expressible in its current operators. It is not a universal actuarial, auction or dispatch algorithm.
- **Why not simply use a spreadsheet?** One versioned policy can serve API transactions and UI simulations with consistent validation, snapshots and replay.
- **Will this win first place?** No outcome is guaranteed. Demonstrate reproducibility and configuration-only onboarding, and be explicit about prototype limits.
