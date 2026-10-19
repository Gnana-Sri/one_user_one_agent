# Architecture

## Decide → verify → act → measure

1. `src.agent.OneViewerAgent` loads the supplied synthetic pack and builds per-viewer event histories, deduplicating by `event_id` and ordering by server `received_at`.
2. Facts resolve the app dialect from the trigger (the setting the viewer will see), while profile/campaign disagreements remain visible in `dialect.conflicts`. Subscription updates from observed events override the day-stale profile.
3. Goal selection excludes G10 because it has no measurable success event. One active goal is retained per viewer; G03's corrected success signal is applied at the control event to open goals.
4. The deterministic local policy proposes a home page or abstains. The independent verifier checks holdout, trigger age, title dialect, availability and content-slug uniqueness; it fails closed on injected malformed-output and timeout cases.
5. Actions and decisions are written as JSONL; viewer snapshots are written under `sample_run/viewer_state/`. The model provider is mocked and no API key is required.
6. `run_all.py` runs the agent replay, the supplied outcome simulator, then `src.evaluation`. The evaluator writes goal judgments to `outcomes.jsonl`, aggregate event-rate metrics to `impact_metrics.json`, `impact_report.md`, and `final_report.md`.

## Ownership and memory
The active-goal dictionary and per-viewer state snapshot represent one owner per viewer in this single-process replay. Histories include provenance in the decision evidence. This is not a multi-worker transactional store.

## Latency and recovery
Processing time is measured locally. Action `published_at` is the replay trigger time plus measured processing duration. Old buffered triggers are rejected using `received_at - occurred_at`. Injected timeout/malformed model faults fail closed to no action. Model-provider and user-data-store control windows fail closed to no action; G03 correction and title withdrawal controls are applied. This is a deterministic simulation, not a realistic distributed outage/load test.

## Trust boundaries
Catalogue descriptions and event properties are treated as data, not instructions. The local mock provider is not a source of eligibility evidence. The verifier checks proposed content against the catalogue. No real viewer data is uploaded.

## Measurement
Outcome judgments use only observed events within each goal's start/deadline window. The replay impact report compares all randomized agent-arm users with all holdout users, including users who received no action. The historical pilot is re-analyzed by randomized assignment; served-vs-unserved is explicitly called out as selection-biased.
