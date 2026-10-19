# Final replay report

- Decisions: 2679
- Actions: 1098
- Simulator events: 31584
- Goal instances judged: 2283
- Judgments: {'failed': 1923, 'succeeded': 360}

## Randomized-arm results

See `impact_report.md` and `impact_metrics.json` for event rates and 95% Wilson intervals.

## Reproducibility

Run `python run_all.py` from the project root. This executes the decision replay, outcome simulator and evaluation stage.

## Caveat

This implementation is a stronger assessment baseline, not a production deployment. Review `KNOWN_LIMITATIONS.md` and the assignment brief before claiming full coverage.
