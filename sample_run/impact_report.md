# Impact report

## Replay: intention-to-treat (randomized arms)

All users assigned to each arm are included, regardless of whether an action was served. Rates use unique users with at least one qualifying simulator event in the 14-day outcome horizon. Confidence intervals are 95% Wilson intervals for each arm's rate; the arm difference is descriptive and does not have a separate CI here.

| Metric | Arm | Users | Users with event | Rate | 95% Wilson CI |
|---|---|---:|---:|---:|---|
| episode_completed | agent | 2513 | 484 | 19.26% | [17.77%, 20.85%] |
| episode_completed | holdout | 2487 | 502 | 20.18% | [18.65%, 21.81%] |
| episode_completed | absolute difference (agent - holdout) | — | — | -0.93% | — |
| paid_purchase | agent | 2513 | 36 | 1.43% | [1.04%, 1.98%] |
| paid_purchase | holdout | 2487 | 36 | 1.45% | [1.05%, 2.00%] |
| paid_purchase | absolute difference (agent - holdout) | — | — | -0.01% | — |
| any_play_started | agent | 2513 | 662 | 26.34% | [24.66%, 28.10%] |
| any_play_started | holdout | 2487 | 669 | 26.90% | [25.19%, 28.68%] |
| any_play_started | absolute difference (agent - holdout) | — | — | -0.56% | — |

## Earlier pilot: corrected randomized-arm analysis

The supplied headline compares served users with everyone else and is selection-biased: service depends on engagement/eligibility. The correct estimate compares every randomized treatment user with every randomized holdout user, whether or not served.

| Arm | Users | Successes | Rate | 95% Wilson CI |
|---|---:|---:|---:|---|
| treatment | 1912 | 349 | 18.25% | [16.59%, 20.05%] |
| holdout | 1979 | 387 | 19.56% | [17.87%, 21.36%] |
| Difference | — | — | -1.30% | — |

## Interpretation and limitations

- The randomized-arm comparison is the correct intention-to-treat estimand; served-vs-unserved is not causal.
- Simulator events are synthetic and results should not be generalized to real viewers.
- The outcome judge uses the supplied event stream and goal windows; some goal conditions (notably G07/series continuation and incomplete observation windows) remain conservative and are called out in outcomes.jsonl.
- This is a deterministic baseline, not a claim that an LLM improved outcomes.
