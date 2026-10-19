# Submission checklist

## Implemented and locally verified in this revision
- [x] One command runs the replay, supplied simulator and evaluator: `python run_all.py`.
- [x] Offline mock/rule-based mode; no personal API key required.
- [x] Duplicate trigger/event handling and stale buffered-trigger abstention.
- [x] Current app dialect precedence with conflicting profile/campaign evidence retained.
- [x] Holdout viewers receive no actions.
- [x] Goal signals absent from the event stream are excluded (G10 and G11).
- [x] G03 correction updates open goal instances during replay.
- [x] Independent home-page checks for dialect, availability, content-slug uniqueness and valid row size.
- [x] Fail-closed behavior for injected timeout/malformed model faults and dependency outage windows.
- [x] Outcome judgments from simulator events and goal windows.
- [x] Replay intention-to-treat metrics comparing every randomized agent-arm user with every holdout user, with Wilson intervals.
- [x] Historical pilot recomputed by randomized arm rather than served/unserved status.
- [x] Eight automated unit tests pass in the current environment.
- [x] Sample replay outputs and generated reports included.

## Limitations to disclose in the submission/interview
- The policy is deterministic and uses a mock provider; it does not demonstrate live LLM orchestration.
- Only home-page actions are published. Messaging is deliberately not enabled; adding it requires implementing consent, quiet hours, combined push/WhatsApp caps, approved templates and copy validation before sending.
- G07 episode-level eligibility and some goal semantics remain conservative and should be reviewed against the brief.
- Dependency faults are simulated through safe abstention; this is not a distributed load or real storage/network outage test.
- The observed simulator result for this seed does not show positive lift: episode completion and play-start rates are lower in the agent arm, and paid-purchase rates are essentially equal. Report this honestly; do not claim the agent improved outcomes.
- The evaluator may use another simulator seed and an unseen replay day. Run tests and `python run_all.py` again in that environment.
