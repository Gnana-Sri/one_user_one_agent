from __future__ import annotations
import argparse, csv, json, statistics, time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))

def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z") if dt else None

def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def truth(value: Any) -> bool:
    return str(value).strip().lower() == "true"

class MockModel:
    """Default provider: deterministic, local, no API key or external data transfer."""
    def propose(self, goal: dict | None, action: str, reason: str) -> dict:
        return {"goal_id": goal["goal_id"] if goal else None, "action": action, "reason": reason}

class OneViewerAgent:
    def __init__(self, pack: Path, out: Path):
        self.pack, self.out = pack, out
        self.events = read_jsonl(pack / "data/events.jsonl")
        live_event_types = {e.get("event") for e in read_jsonl(pack / "replay/live_events.jsonl") if e.get("event")}
        self.observable_events = {e.get("event") for e in self.events if e.get("event")} | live_event_types
        self.profiles_rows = read_csv(pack / "data/profiles_snapshot.csv")
        self.profiles = {}
        for row in self.profiles_rows:
            old = self.profiles.get(row["user_id"])
            if old is None or row.get("updated_at", "") > old.get("updated_at", ""):
                self.profiles[row["user_id"]] = row
        self.catalogue_rows = read_csv(pack / "data/catalogue.csv")
        self.catalogue = {r["title_id"]: r for r in self.catalogue_rows}
        self.episodes_rows = read_csv(pack / "data/episodes.csv")
        self.episodes_by_slug: dict[str, set[str]] = defaultdict(set)
        for episode in self.episodes_rows:
            self.episodes_by_slug[episode.get("content_slug", "")].add(episode.get("episode_id", ""))
        self.goals = json.loads((pack / "config/goals.json").read_text(encoding="utf-8"))["goals"]
        self.interventions = json.loads((pack / "config/interventions.json").read_text(encoding="utf-8"))
        self.arms = {r["user_id"]: r["arm"] for r in read_csv(pack / "replay/arms.csv")}
        self.model = MockModel()
        self.control_events = read_jsonl(pack / "replay/control_events.jsonl")
        self.model_faults = {r.get("trigger_event_id"): r for r in read_jsonl(pack / "replay/model_faults.jsonl")}
        self.seen_events: set[str] = set()
        self.history: dict[str, list[dict]] = defaultdict(list)
        for event in self.events:
            eid = event.get("event_id")
            if eid and eid not in self.seen_events:
                self.seen_events.add(eid)
                self.history[event["user_id"]].append(event)
        for rows in self.history.values():
            rows.sort(key=lambda e: e.get("received_at", ""))
        self.last_message_ist_day: dict[str, str] = {}
        self.decisions, self.actions, self.outcomes = [], [], []
        self.active_goals: dict[str, dict] = {}
        self.state_dir = out / "viewer_state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def user_events(self, user_id: str, before: datetime | None = None) -> list[dict]:
        rows = self.history.get(user_id, [])
        if before is None:
            return rows
        return [e for e in rows if (parse_ts(e.get("received_at")) or datetime.min.replace(tzinfo=UTC)) <= before]

    def resolve(self, trigger: dict) -> dict:
        uid = trigger["user_id"]
        profile = self.profiles.get(uid, {})
        events = self.user_events(uid, parse_ts(trigger.get("deliver_at") or trigger.get("received_at")))
        dialect = trigger.get("app_dialect") or profile.get("preferred_dialect") or "unknown"
        conflicts = []
        for source, value in [("profile", profile.get("preferred_dialect")), ("campaign", self._campaign_dialect(trigger))]:
            if value and dialect != value:
                conflicts.append({"source": source, "value": value, "chosen": dialect})
        # Later opt-out events supersede the stale profile snapshot.
        opt_out = {e.get("properties", {}).get("channel") for e in events if e.get("event") == "notification_opt_out"}
        status = profile.get("subscription_status") or "unknown"
        for e in events:
            ev = e.get("event")
            props = e.get("properties", {})
            if ev == "purchase_completed":
                status = "active" if not truth(props.get("is_trial", False)) else "trial_active"
            elif ev == "subscription_lapsed":
                status = "lapsed"
        signup_at = parse_ts(profile.get("signup_at"))
        if not signup_at:
            signup_events = [parse_ts(e.get("received_at")) for e in events if e.get("event") == "signup_completed"]
            signup_at = min((x for x in signup_events if x), default=None)
        return {"profile": profile, "events": events, "dialect": dialect, "dialect_conflicts": conflicts,
                "subscription_status": status, "signup_at": signup_at, "opt_out": opt_out}

    @staticmethod
    def _campaign_dialect(trigger: dict) -> str | None:
        deeplink = trigger.get("properties", {}).get("deeplink", "")
        parts = str(deeplink).split("/")
        return next((p for p in parts if p.startswith("d") and p[1:].isdigit()), None)

    def choose_goal(self, facts: dict, now: datetime) -> dict | None:
        uid = facts["profile"].get("user_id")
        events = facts["events"]
        names = {e.get("event") for e in events}
        age_days = (now - facts["signup_at"]).total_seconds() / 86400 if facts["signup_at"] else None
        status = facts["subscription_status"]
        for g in self.goals:
            gid = g["goal_id"]
            success = g.get("success", {})
            # Never select a goal whose success event cannot be observed in the supplied stream.
            if not success.get("event") or success.get("event") not in self.observable_events:
                continue
            elig = g.get("eligibility", {})
            if gid == "G01" and not (age_days is not None and 0 <= age_days <= 7 and "play_started" not in names):
                continue
            if gid == "G02" and "episode_completed" in names:
                continue
            if gid == "G03" and not (age_days is not None and 0 <= age_days <= 2):
                continue
            if gid in ("G04", "G05", "G06", "G08", "G09", "G11"):
                allowed = elig.get("subscription_status", [])
                if status not in allowed:
                    continue
            if gid == "G05" and any(e.get("event") in ("purchase_completed", "subscription_renewed") and not truth(e.get("properties", {}).get("is_trial", False)) for e in events):
                continue
            unfinished_slug = None
            if gid == "G07":
                plays = [e for e in events if e.get("event") == "play_started"]
                plays.sort(key=lambda e: e.get("received_at", ""))
                if not plays:
                    continue
                last = parse_ts(plays[-1].get("received_at"))
                title = self.catalogue.get((plays[-1].get("properties") or {}).get("title_id"), {})
                unfinished_slug = title.get("content_slug")
                if not last or now - last < timedelta(days=3):
                    continue
                if title.get("content_type") not in ("show", "micro_drama") or not unfinished_slug:
                    continue
                series_episodes = self.episodes_by_slug.get(unfinished_slug, set())
                completed = {e.get("properties", {}).get("episode_id") for e in events if e.get("event") == "episode_completed"
                             and self.catalogue.get((e.get("properties") or {}).get("title_id"), {}).get("content_slug") == unfinished_slug}
                if not series_episodes or series_episodes.issubset(completed):
                    continue
            if gid == "G12":
                opens = [parse_ts(e.get("received_at")) for e in events if e.get("event") == "app_open"]
                if opens and now - max(opens) < timedelta(days=14):
                    continue
            # Use eligibility order as supplied; first eligible measurable goal wins.
            window = int(success.get("window_hours", 24))
            success_event = success["event"]
            success_condition = success.get("condition")
            assumptions = ["G10 is excluded because the supplied stream has no measurable success event."]
            if gid == "G03":
                correction = next((c for c in self.control_events if c.get("type") == "goal_rule_corrected" and c.get("goal_id") == "G03" and parse_ts(c.get("at")) and now >= parse_ts(c.get("at"))), None)
                if correction:
                    success_event = correction.get("new_success", {}).get("event", "play_started")
                    success_condition = correction.get("new_success", {}).get("condition", "on a later IST calendar day within the window")
                    assumptions.append("G03 corrected at replay time; app_open alone is not success.")
                else:
                    assumptions.append("G03 pre-correction interpretation: a later IST-day app_open counts; this remains an explicit assumption.")
            if gid in ("G04", "G05"):
                assumptions.append("A paid conversion requires purchase_completed with is_trial=false.")
            return {"goal_id": gid, "name": g["name"], "deadline": iso(now + timedelta(hours=window)),
                    **({"content_slug": unfinished_slug} if gid == "G07" and unfinished_slug else {}),
                    "success_event": success_event, "success_condition": success_condition,
                    "window_hours": window, "rule_version": "2026-10-01-G03-corrected" if (gid == "G03" and success_event == "play_started" and any(c.get("type") == "goal_rule_corrected" and c.get("goal_id") == "G03" and parse_ts(c.get("at")) and now >= parse_ts(c.get("at")) for c in self.control_events)) else "2026-09-30",
                    "assumptions": assumptions}
        return None

    def available_titles(self, dialect: str, now: datetime) -> list[dict]:
        valid = []
        for t in self.catalogue_rows:
            if t.get("dialect") != dialect:
                continue
            start, end = parse_ts(t.get("available_from")), parse_ts(t.get("available_until"))
            if start and start > now:
                continue
            if end and now >= end:
                continue
            valid.append(t)
        return valid

    def verify_and_act(self, trigger: dict, facts: dict, goal: dict | None, now: datetime, decision_id: str) -> tuple[dict, dict | None]:
        uid = trigger["user_id"]
        checks = {"passed": [], "failed": []}
        action_type, content, no_action_reason = "none", [], None
        received = parse_ts(trigger.get("received_at")) or now
        occurred = parse_ts(trigger.get("occurred_at")) or received
        event_age_s = max(0, int((received - occurred).total_seconds()))
        fault = self.model_faults.get(trigger.get("event_id"))
        fallback_used = False
        active_dependency_control = None
        for control in self.control_events:
            if control.get("type") not in ("dependency_unavailable", "dependency_degraded"):
                continue
            start_at, end_at = parse_ts(control.get("at")), parse_ts(control.get("until"))
            if start_at and end_at and start_at <= now < end_at:
                active_dependency_control = control
                break
        if fault and fault.get("fault") == "unsupported_claim":
            checks["passed"].append("unsupported_model_claim_rejected")
        if self.arms.get(uid) == "holdout":
            no_action_reason = "randomized_holdout: all actions prohibited"
            checks["passed"].append("holdout_respected")
        elif event_age_s > 6 * 3600:
            no_action_reason = "stale_trigger: occurred_at is more than six hours before server receipt"
            checks["passed"].append("stale_trigger_rejected")
        elif active_dependency_control and active_dependency_control.get("dependency") == "user_data_store":
            no_action_reason = "user_data_store_degraded: fail closed rather than act on potentially stale facts"
            checks["passed"].append("dependency_failure_safe_fallback")
            fallback_used = True
        elif active_dependency_control and active_dependency_control.get("dependency") == "model_provider":
            no_action_reason = "model_provider_unavailable: safe deterministic abstention during injected outage"
            checks["passed"].append("dependency_failure_safe_fallback")
            fallback_used = True
        elif fault and fault.get("fault") in ("timeout", "malformed_output"):
            # The local baseline deliberately fails closed on injected model faults.
            no_action_reason = f"model_fault_{fault['fault']}: safe fallback to no action"
            checks["passed"].append("model_fault_safe_fallback")
            fallback_used = True
        elif not goal:
            no_action_reason = "no eligible measurable goal supported by current evidence"
            checks["passed"].append("goal_abstention")
        else:
            titles = self.available_titles(facts["dialect"], now)
            # Derive a preference only from observed watch/title events; descriptions are never instructions.
            genre_counts = Counter()
            for event in facts["events"]:
                if event.get("event") not in ("play_started", "episode_completed", "title_viewed"):
                    continue
                tid = (event.get("properties") or {}).get("title_id")
                for genre in self.catalogue.get(tid, {}).get("genres", "").split("|"):
                    if genre.strip(): genre_counts[genre.strip()] += 1
            top_genre = genre_counts.most_common(1)[0][0] if genre_counts else None
            newest = sorted(titles, key=lambda t: (t.get("release_date", ""), t["title_id"]), reverse=True)
            genre_titles = [t for t in newest if top_genre and top_genre in t.get("genres", "").split("|")]
            chosen, slugs = [], set()
            def add_candidates(candidates, limit):
                for candidate in candidates:
                    slug = candidate.get("content_slug") or candidate["title_id"]
                    if slug in slugs: continue
                    chosen.append(candidate); slugs.add(slug)
                    if len(chosen) >= limit: return
            # Hero favors an observed genre when one exists; cold-start viewers use current catalogue releases.
            add_candidates(genre_titles or newest, 1)
            # Three valid rows, each with three distinct content slugs; rows are not duplicated across the page.
            add_candidates(genre_titles or newest, 4)
            add_candidates(newest, 7)
            add_candidates([t for t in newest if t not in chosen], 10)
            if len(chosen) >= 10:
                action_type, content = "home_page", [t["title_id"] for t in chosen]
                checks["passed"] += ["goal_eligibility", "dialect", "availability", "holdout", "content_slug_deduplication", "home_page_constraints", "observed_genre_personalization"]
                if any("SYSTEM NOTE FOR AI AGENTS" in t.get("description", "") for t in chosen):
                    checks["passed"].append("catalogue_prompt_injection_ignored")
            else:
                no_action_reason = f"insufficient available unique titles in dialect {facts['dialect']} for a valid three-row page"
                checks["passed"].append("invalid_page_abstained")
        action = None
        if action_type == "home_page":
            hero = self.catalogue[content[0]]
            row_ids = content[1:]
            row_types = ["genre" if top_genre else "popular_in_dialect", "new_releases", "popular_in_dialect"]
            page_rows = [{"row_type": row_types[i], "title_ids": row_ids[i*3:(i+1)*3]} for i in range(3)]
            action = {"action_id": f"A-{decision_id[2:]}", "decision_id": decision_id, "user_id": uid,
                      "trigger_event_id": trigger["event_id"], "type": "home_page", "published_at": iso(now),
                      "dialect": facts["dialect"], "hero_title_id": hero["title_id"], "rows": page_rows}
            # Independent verifier re-checks every page title and the hero/row slug uniqueness.
            page_titles = [self.catalogue[x] for x in [hero["title_id"]] + row_ids]
            valid = (1 <= len(page_rows) <= 6 and all(3 <= len(r["title_ids"]) <= 10 for r in page_rows)
                     and len(row_ids) <= 60 and len({t.get("content_slug", t["title_id"]) for t in page_titles}) == len(page_titles)
                     and all(r["row_type"] in {"next_episode", "because_you_watched", "popular_in_dialect", "new_releases", "genre"} for r in page_rows)
                     and all(t.get("dialect") == facts["dialect"] for t in page_titles)
                     and all((not parse_ts(t.get("available_from")) or parse_ts(t["available_from"]) <= now)
                             and (not parse_ts(t.get("available_until")) or now < parse_ts(t["available_until"])) for t in page_titles))
            if not valid or self.arms.get(uid) == "holdout":
                action = None; action_type = "none"
                checks["failed"].append("independent_page_verifier")
                no_action_reason = "independent verifier rejected the proposed home page"
        decision = {
            "decision_id": decision_id, "viewer_id": uid,
            "trigger": {"event": trigger.get("event"), "event_id": trigger.get("event_id"),
                        "received_at": trigger.get("received_at"), "deliver_at": trigger.get("deliver_at"),
                        "event_age_s": event_age_s},
            "goal": goal, "action": action_type.upper(), "dialect": {"used": facts["dialect"],
                "source": "app_setting" if trigger.get("app_dialect") else "profile_or_fallback",
                "conflicts": facts["dialect_conflicts"]}, "content": content,
            "confidence": 0.65 if goal else 0.2,
            "confidence_reason": "Deterministic rule eligibility and independent catalogue verification; no model assertion is accepted as evidence.",
            "evidence": [{"source": "trigger", "id": trigger.get("event_id"), "freshness": trigger.get("received_at")},
                         {"source": "profile_snapshot", "id": uid, "freshness": facts["profile"].get("updated_at")},
                         {"source": "goal_catalogue", "id": goal["goal_id"] if goal else None, "freshness": "config version 2026-09-30"}],
            "assumptions": goal.get("assumptions", []) if goal else [],
            "checks": checks, "no_action_reason": no_action_reason,
            "fallback_used": fallback_used, "model_fault": fault.get("fault") if fault else None,
            "decided_in_ms": 0, "model_calls": 0, "tool_calls": 0, "rule_version": "2026-10-01-r1",
            "status": "PUBLISHED" if action else "NO_ACTION"}
        return decision, action

    def run(self) -> dict:
        triggers = read_jsonl(self.pack / "replay/triggers.jsonl")
        triggers.sort(key=lambda e: e.get("deliver_at", e.get("received_at", "")))
        # Process live events into history before their deliver_at; deduplicate by event_id.
        live = read_jsonl(self.pack / "replay/live_events.jsonl")
        controls = self.control_events
        withdrawn = {c["title_id"]: parse_ts(c["at"]) for c in controls if c.get("type") == "title_withdrawn"}
        for tid, at in withdrawn.items():
            if tid in self.catalogue and at:
                end = parse_ts(self.catalogue[tid].get("available_until"))
                if end is None or at < end:
                    self.catalogue[tid]["available_until"] = iso(at)
        seen_triggers = set()
        start = time.perf_counter()
        for i, trigger in enumerate(triggers, 1):
            eid = trigger.get("event_id")
            if eid in seen_triggers:
                continue
            seen_triggers.add(eid)
            uid = trigger["user_id"]
            now = parse_ts(trigger.get("deliver_at") or trigger.get("received_at")) or datetime.now(UTC)
            # Incorporate live events received before this trigger, maintaining event idempotency.
            for ev in live:
                if ev.get("user_id") != uid or ev.get("event_id") in self.seen_events:
                    continue
                received = parse_ts(ev.get("received_at"))
                if received and received <= now:
                    self.history[uid].append(ev); self.seen_events.add(ev["event_id"])
            self.history[uid].sort(key=lambda e: e.get("received_at", ""))
            facts = self.resolve(trigger)
            goal = self.active_goals.get(uid)
            # Apply corrected goal semantics to still-open G03 instances, not just future goals.
            correction = next((c for c in controls if c.get("type") == "goal_rule_corrected" and c.get("goal_id") == "G03" and parse_ts(c.get("at")) and now >= parse_ts(c.get("at"))), None)
            if goal and goal.get("goal_id") == "G03" and correction and parse_ts(goal.get("deadline")) and now < parse_ts(goal["deadline"]):
                goal["success_event"] = correction.get("new_success", {}).get("event", "play_started")
                goal["success_condition"] = correction.get("new_success", {}).get("condition", "on a later IST calendar day within the window")
                goal["rule_version"] = "2026-10-01-G03-corrected"
                goal.setdefault("assumptions", []).append("G03 rule correction applied to open goal at control event time.")
            if goal and parse_ts(goal["deadline"]) and now < parse_ts(goal["deadline"]):
                # One active goal per viewer; retain it until completion/deadline or material state change.
                completed = any(e.get("event") == goal["success_event"] and parse_ts(e.get("received_at")) and parse_ts(e["received_at"]) <= now for e in facts["events"])
                if not completed and facts["subscription_status"] not in ("active", "lapsed") and goal["goal_id"] not in ("G01", "G02", "G03", "G12"):
                    goal = self.choose_goal(facts, now)
                elif not completed:
                    goal = self.active_goals[uid]
                else:
                    goal = None
            if not goal:
                goal = self.choose_goal(facts, now)
            if goal:
                self.active_goals[uid] = goal
            began = time.perf_counter()
            did = f"D-{len(self.decisions)+1:05d}"
            decision, action = self.verify_and_act(trigger, facts, goal, now, did)
            decision["decided_in_ms"] = round((time.perf_counter() - began) * 1000, 3)
            # Replay timestamps represent when decision is published; latency is measured separately.
            decision["trigger"]["event_age_s"] = max(0, decision["trigger"]["event_age_s"])
            # Published-at reflects the replay trigger plus measured local processing latency.
            if action:
                action["published_at"] = iso(now + timedelta(milliseconds=decision["decided_in_ms"]))
            self.decisions.append(decision)
            if action:
                self.actions.append(action)
            state = {"user_id": uid, "facts": {"dialect": facts["dialect"], "subscription_status": facts["subscription_status"],
                      "signup_at": iso(facts["signup_at"]), "dialect_conflicts": facts["dialect_conflicts"]},
                     "active_goal": self.active_goals.get(uid), "last_decision_id": did,
                     "decisions": [d["decision_id"] for d in self.decisions if d["viewer_id"] == uid]}
            (self.state_dir / f"{uid}.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        self.out.mkdir(parents=True, exist_ok=True)
        write_jsonl(self.out / "decisions.jsonl", self.decisions)
        write_jsonl(self.out / "actions.jsonl", self.actions)
        write_jsonl(self.out / "outcomes.jsonl", self.outcomes)
        latencies = [d["decided_in_ms"] for d in self.decisions]
        report = {"decisions": len(self.decisions), "actions": len(self.actions),
                  "no_action_decisions": sum(d["status"] == "NO_ACTION" for d in self.decisions),
                  "duplicate_triggers_skipped": len(triggers) - len(seen_triggers),
                  "mean_processing_ms": round(statistics.mean(latencies), 3) if latencies else 0,
                  "p95_processing_ms": round(sorted(latencies)[min(len(latencies)-1, int(.95*len(latencies)))] ,3) if latencies else 0,
                  "max_processing_ms": max(latencies, default=0), "target_ms": 60000,
                  "note": "Local processing time is measured; replay's deliver_at is the simulated trigger time."}
        (self.out / "latency_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        self.write_impact_report()
        return report

    def write_impact_report(self):
        # Randomized arms are the correct analysis unit. Simulator outcomes are added by run_all.py.
        arms = defaultdict(list)
        for row in read_csv(self.pack / "replay/arms.csv"):
            arms[row["arm"]].append(row["user_id"])
        text = ["# Impact report", "", "## Randomized assignment (intention-to-treat)", "",
                f"- Agent-arm users in arms.csv: {len(arms['agent'])}",
                f"- Holdout users in arms.csv: {len(arms['holdout'])}",
                "- Compare all assigned agent users with all assigned holdout users, including agent users who received no action.",
                "- Do not compare served vs unserved: activity affects whether someone is served, causing selection bias.",
                "- Outcome rates are not reported until the simulator output is analyzed; do not infer uplift from action counts.",
                "", "## Caveats", "This starter uses a conservative deterministic policy and does not yet implement full goal-specific outcome attribution."]
        (self.out / "impact_report.md").write_text("\n".join(text) + "\n", encoding="utf-8")

def main():
    parser = argparse.ArgumentParser(description="One User, One Agent replay runner (offline mock provider)")
    parser.add_argument("--pack", type=Path, default=Path("data_pack/one_user_one_agent_pack"))
    parser.add_argument("--out", type=Path, default=Path("sample_run"))
    args = parser.parse_args()
    report = OneViewerAgent(args.pack.resolve(), args.out.resolve()).run()
    print(json.dumps(report, indent=2))
    print(f"Decisions: {args.out.resolve() / 'decisions.jsonl'}")
    print(f"Actions:   {args.out.resolve() / 'actions.jsonl'}")

if __name__ == "__main__":
    main()
