# One User, One Agent — runnable assessment baseline

This project implements an offline, deterministic lifecycle-agent replay for the supplied synthetic OTT data pack. It is designed to run without an API key and to be inspectable in a technical discussion. It is a baseline rather than a production service; read `KNOWN_LIMITATIONS.md`.

## Requirements
- Python 3.10+ (uses standard library only)
- Windows PowerShell / VS Code terminal or any platform with Python

## Setup on Windows (PowerShell)
From the project root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m unittest discover -s tests -v
python run_all.py
```

No third-party dependency or API key is required. If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal and activate again.

## What `python run_all.py` does
1. Replays the triggers with `src.agent` and writes decisions/actions/state/latency.
2. Runs the supplied simulator over the actions.
3. Judges goal outcomes and writes randomized-arm evaluation reports.

## Main outputs
- `sample_run/decisions.jsonl` — one machine-readable decision per processed trigger, including evidence, conflicts, checks, no-action reasons and latency. The page policy uses observed genre history when available and publishes three valid rows with unique content slugs.
- `sample_run/actions.jsonl` — actions actually published (home-page actions only in this baseline).
- `sample_run/outcomes.jsonl` — judged goal instances: succeeded, failed or inconclusive, with reason and evidence event ID when available.
- `sample_run/latency_report.json` — local processing timing summary.
- `sample_run/impact_metrics.json` — randomized-arm event rates and confidence intervals.
- `sample_run/impact_report.md` — replay ITT and historical pilot randomized-arm analysis.
- `sample_run/final_report.md` — concise generated run summary.
- `sample_run/viewer_state/` — per-viewer snapshots.

## Run components individually
```powershell
python -m src.agent --pack data_pack/one_user_one_agent_pack --out sample_run
python data_pack/one_user_one_agent_pack/simulator/simulate_outcomes.py --pack data_pack/one_user_one_agent_pack --actions sample_run/actions.jsonl --out sample_run/sim
python -m src.evaluation --pack data_pack/one_user_one_agent_pack --out sample_run
```

## Important assumptions
- The current app dialect on the trigger takes precedence for the page; conflicts remain in the decision record.
- Goals whose success signal is absent from the supplied historical/live event types are excluded (G10 has no event; G11's `tv_app_open` is not observed either).
- The G03 success rule is corrected by the replay control event; open goals are updated when that control is reached.
- No push or WhatsApp sends are enabled in this baseline; those interventions require their consent, quiet-hour, shared frequency-cap and approved-template verifiers first.
- Impact comparisons use randomized assignment (intention-to-treat), never served vs unserved users.

## Data and privacy
All data is synthetic and supplied for this assessment. The implementation is local-only and does not upload data to an external model provider.
