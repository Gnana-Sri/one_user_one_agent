# Known limitations

This repository is a deterministic, offline assessment implementation. It is not a production deployment and does not call a hosted LLM.

## Implemented in this revision
- Replay CLI, deduplication, server-receipt ordering, dialect conflict visibility, stale-trigger abstention, holdout exclusion, deterministic catalogue selection, page-level title/dialect/availability checks, and no-action reasons.
- Fail-closed handling for injected malformed-output and timeout triggers; unsupported model claims are not used as eligibility evidence.
- G03 correction is applied to open goals during replay and to new goals after the control event.
- Outcome judgment output and intention-to-treat event-rate comparisons with Wilson intervals, plus randomized-arm re-analysis of the historical pilot.
- Tests for baseline cases, timeout fallback and the presence of the corrected G03 rule.

## Remaining limitations to disclose
1. The model provider is a mock and the decision policy is rule-based. This meets the offline/no-key requirement but does not demonstrate live LLM orchestration.
2. Only home-page interventions are published. Push, WhatsApp and in-app messaging are deliberately not enabled, so consent/quiet-hour/frequency/template rules are avoided rather than implemented for sends. If messaging is added, all of those checks must be implemented before enabling it.
3. Goal eligibility is a conservative interpretation of the catalogue; G07 episode-level unfinished-series matching and some goal-specific eligibility rules warrant further validation.
4. The evaluation labels a first goal instance per viewer and uses available simulator event windows. Goals whose observation window extends beyond the simulator horizon are inconclusive; inspect `outcomes.jsonl`.
5. The replay is single-process; viewer-state snapshots are not transactionally safe for concurrent workers. Burst behavior is not a distributed-load test.
6. The confidence intervals are per-arm Wilson intervals. The difference is descriptive; a bootstrap or score-based interval for the difference could be added.
7. The `tv_app_open` success signal (G11) and G10 meaningful-engagement signal are not available in the supplied event stream; both goals are excluded rather than falsely judged.
8. Rerun `python run_all.py` to regenerate outputs for the supplied seed. The evaluators may use a different seed and unseen replay day.
