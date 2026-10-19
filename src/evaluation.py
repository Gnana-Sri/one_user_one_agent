from __future__ import annotations
import argparse, csv, json, math, statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))

def parse_ts(v):
    if not v: return None
    try: return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError): return None

def read_jsonl(p):
    if not p.exists(): return []
    out=[]
    with p.open(encoding="utf-8") as f:
        for line in f:
            if line.strip(): out.append(json.loads(line))
    return out

def read_csv(p):
    with p.open(newline="", encoding="utf-8") as f: return list(csv.DictReader(f))

def write_jsonl(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r, sort_keys=True, ensure_ascii=False)+"\n")

def success_match(goal, e, start, deadline, catalogue):
    t=parse_ts(e.get("received_at")) or parse_ts(e.get("deliver_at")) or parse_ts(e.get("occurred_at"))
    if not t or not start <= t <= deadline or e.get("event") != goal.get("success_event"): return False
    gid=goal.get("goal_id"); props=e.get("properties", {}) or {}
    if gid in ("G04","G05"): return e.get("event")=="purchase_completed" and str(props.get("is_trial", "false")).lower() not in ("true","1")
    if gid=="G06": return e.get("event")=="purchase_completed" and str(props.get("is_trial", "false")).lower() not in ("true","1")
    if gid=="G07":
        wanted=goal.get("content_slug")
        title=catalogue.get(props.get("title_id"), {})
        return bool(wanted and title.get("content_slug")==wanted)
    if gid=="G08":
        title=catalogue.get(props.get("title_id"), {})
        release=title.get("release_date")
        if not release: return False
        try: rd=datetime.fromisoformat(release).replace(tzinfo=UTC).date()
        except ValueError: return False
        return (start.date()-timedelta(days=30)) <= rd <= start.date() and bool(title)
    if gid=="G09": return True
    if gid=="G03": return t.astimezone(IST).date() > start.astimezone(IST).date()
    return True

def wilson(successes, n, z=1.96):
    if not n: return (None, None)
    p=successes/n; den=1+z*z/n
    center=(p+z*z/(2*n))/den
    half=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/den
    return max(0,center-half), min(1,center+half)

def rate_line(name, n, s):
    if not n: return f"| {name} | 0 | — | — |"
    lo,hi=wilson(s,n)
    return f"| {name} | {n} | {s/n:.2%} | [{lo:.2%}, {hi:.2%}] |"

def evaluate(pack: Path, out: Path):
    decisions=read_jsonl(out/"decisions.jsonl")
    sim_events=read_jsonl(out/"sim"/"outcome_events.jsonl")
    arms={r["user_id"]:r["arm"] for r in read_csv(pack/"replay/arms.csv")}
    catalogue={r["title_id"]:r for r in read_csv(pack/"data/catalogue.csv")}
    goals_by_user={}
    # A goal instance starts at deadline minus its configured window; keep the first instance per viewer.
    for d in decisions:
        g=d.get("goal")
        if not g or not g.get("success_event"): continue
        uid=d["viewer_id"]
        deadline=parse_ts(g.get("deadline"))
        hours=int(g.get("window_hours") or 24)
        if not deadline: continue
        start=deadline-timedelta(hours=hours)
        key=(uid, g.get("goal_id"), deadline.isoformat())
        if key in goals_by_user:
            existing=goals_by_user[key]
            # A control-event correction updates the same open goal instance in place.
            if g.get("rule_version") != existing.get("rule_version"):
                for field in ("success_event", "success_condition", "rule_version", "content_slug"):
                    existing[field]=g.get(field)
            continue
        goals_by_user[key]={"viewer_id":uid,"goal_id":g.get("goal_id"),"goal_name":g.get("name"),"content_slug":g.get("content_slug"),"started_at":start.isoformat().replace("+00:00","Z"),
                            "deadline":deadline.isoformat().replace("+00:00","Z"),"success_event":g.get("success_event"),"success_condition":g.get("success_condition"),
                            "rule_version":g.get("rule_version"),"arm":arms.get(uid,"unknown"),"judgment":"inconclusive","evidence_event_id":None,
                            "reason":"The observation horizon does not yet establish success or failure."}
    by_user=defaultdict(list)
    for e in sim_events: by_user[e.get("user_id")].append(e)
    judged=[]
    horizon_max=max((parse_ts(e.get("received_at")) for e in sim_events if parse_ts(e.get("received_at"))), default=None)
    for goal_key, row in goals_by_user.items():
        uid=row["viewer_id"]
        start=parse_ts(row["started_at"]); deadline=parse_ts(row["deadline"])
        if row["goal_id"]=="G10" or not row.get("success_event"):
            row["judgment"]="inconclusive"; row["reason"]="No measurable success signal is defined in the supplied event stream."
        else:
            matching=[e for e in by_user[uid] if success_match(row,e,start,deadline,catalogue)]
            if row["goal_id"]=="G09":
                days={((parse_ts(e.get("received_at")) or parse_ts(e.get("occurred_at"))).astimezone(IST).date()) for e in by_user[uid] if e.get("event")=="play_started" and parse_ts(e.get("received_at")) and start <= parse_ts(e["received_at"]) <= deadline}
                if len(days)>=3:
                    row["judgment"]="succeeded"; row["reason"]="play_started occurred on at least three distinct IST calendar days." 
                elif horizon_max and deadline <= horizon_max:
                    row["judgment"]="failed"; row["reason"]=f"Observed {len(days)} distinct play day(s), fewer than the required three."
            elif matching:
                row["judgment"]="succeeded"; row["evidence_event_id"]=matching[0].get("event_id"); row["reason"]="A matching success event was observed inside the goal window."
            else:
                horizon=horizon_max or start
                if horizon >= deadline:
                    row["judgment"]="failed"; row["reason"]="The full goal window was observed and no attributable success event occurred."
        judged.append(row)
    write_jsonl(out/"outcomes.jsonl", judged)
    # ITT replay outcomes: all randomized users, not served/unserved. Use the same 14-day simulator window.
    event_users=defaultdict(list)
    for e in sim_events: event_users[e.get("user_id")].append(e)
    def event_success(uid, predicate): return any(predicate(e) for e in event_users.get(uid, []))
    metrics={"episode_completed": lambda e:e.get("event")=="episode_completed", "paid_purchase":lambda e:e.get("event")=="purchase_completed" and str((e.get("properties") or {}).get("is_trial","false")).lower() not in ("true","1"), "any_play_started":lambda e:e.get("event")=="play_started"}
    groups={arm:[uid for uid,a in arms.items() if a==arm] for arm in ("agent","holdout")}
    summary={}
    for metric,pred in metrics.items():
        summary[metric]={}
        for arm,uids in groups.items():
            n=len(uids); s=sum(event_success(uid,pred) for uid in uids)
            lo,hi=wilson(s,n)
            summary[metric][arm]={"n":n,"successes":s,"rate":s/n if n else None,"ci95":[lo,hi]}
        a=summary[metric]["agent"]; h=summary[metric]["holdout"]
        summary[metric]["absolute_difference"]=(a["rate"]-h["rate"]) if a["rate"] is not None and h["rate"] is not None else None
    (out/"impact_metrics.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    # Recompute pilot ITT from supplied randomized assignment/outcomes; served is deliberately ignored.
    pilot_assign=read_csv(pack/"pilot/pilot_assignment.csv"); pilot_out=read_csv(pack/"pilot/pilot_outcomes.csv")
    outcomes={r["user_id"]:str(r.get("succeeded","false")).lower()=="true" for r in pilot_out}
    pilot_groups=defaultdict(list)
    for r in pilot_assign: pilot_groups[r.get("arm","").lower()].append(r["user_id"])
    pilot=[]
    for arm in ("treatment","agent","holdout","control"):
        uids=pilot_groups.get(arm,[])
        if uids:
            n=len(uids); s=sum(outcomes.get(uid,False) for uid in uids); lo,hi=wilson(s,n)
            pilot.append({"arm":arm,"n":n,"successes":s,"rate":s/n,"ci95":[lo,hi]})
    pilot_map={r["arm"]:r for r in pilot}
    treatment=pilot_map.get("treatment",pilot_map.get("agent")); holdout=pilot_map.get("holdout",pilot_map.get("control"))
    lines=["# Impact report","","## Replay: intention-to-treat (randomized arms)","","All users assigned to each arm are included, regardless of whether an action was served. Rates use unique users with at least one qualifying simulator event in the 14-day outcome horizon. Confidence intervals are 95% Wilson intervals for each arm's rate; the arm difference is descriptive and does not have a separate CI here.","","| Metric | Arm | Users | Users with event | Rate | 95% Wilson CI |","|---|---|---:|---:|---:|---|"]
    for metric, data in summary.items():
        for arm in ("agent","holdout"):
            x=data[arm]; lo,hi=x["ci95"]
            lines.append(f"| {metric} | {arm} | {x['n']} | {x['successes']} | {x['rate']:.2%} | [{lo:.2%}, {hi:.2%}] |")
        lines.append(f"| {metric} | absolute difference (agent - holdout) | — | — | {data['absolute_difference']:+.2%} | — |")
    lines += ["","## Earlier pilot: corrected randomized-arm analysis","","The supplied headline compares served users with everyone else and is selection-biased: service depends on engagement/eligibility. The correct estimate compares every randomized treatment user with every randomized holdout user, whether or not served.",""]
    if treatment and holdout:
        lines += ["| Arm | Users | Successes | Rate | 95% Wilson CI |","|---|---:|---:|---:|---|",f"| {treatment['arm']} | {treatment['n']} | {treatment['successes']} | {treatment['rate']:.2%} | [{treatment['ci95'][0]:.2%}, {treatment['ci95'][1]:.2%}] |",f"| {holdout['arm']} | {holdout['n']} | {holdout['successes']} | {holdout['rate']:.2%} | [{holdout['ci95'][0]:.2%}, {holdout['ci95'][1]:.2%}] |",f"| Difference | — | — | {(treatment['rate']-holdout['rate']):+.2%} | — |"]
    else:
        lines.append("Pilot randomized arm labels were not recognized; inspect pilot CSV schema before interpreting this section.")
    lines += ["","## Interpretation and limitations","","- The randomized-arm comparison is the correct intention-to-treat estimand; served-vs-unserved is not causal.","- Simulator events are synthetic and results should not be generalized to real viewers.","- The outcome judge uses the supplied event stream and goal windows; some goal conditions (notably G07/series continuation and incomplete observation windows) remain conservative and are called out in outcomes.jsonl.","- This is a deterministic baseline, not a claim that an LLM improved outcomes."]
    (out/"impact_report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    # Small reproducibility summary.
    judgments=defaultdict(int)
    for r in judged: judgments[r["judgment"]]+=1
    report={"goal_instances_judged":len(judged),"judgments":dict(judgments),"simulator_events":len(sim_events),"randomized_users":len(arms),"pilot_randomized_arms_found":bool(treatment and holdout),"impact_metrics":summary}
    (out/"evaluation_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    final=["# Final replay report","",f"- Decisions: {len(decisions)}",f"- Actions: {len(read_jsonl(out/'actions.jsonl'))}",f"- Simulator events: {len(sim_events)}",f"- Goal instances judged: {len(judged)}",f"- Judgments: {dict(judgments)}","","## Randomized-arm results","","See `impact_report.md` and `impact_metrics.json` for event rates and 95% Wilson intervals.","","## Reproducibility","","Run `python run_all.py` from the project root. This executes the decision replay, outcome simulator and evaluation stage.","","## Caveat","","This implementation is a stronger assessment baseline, not a production deployment. Review `KNOWN_LIMITATIONS.md` and the assignment brief before claiming full coverage."]
    (out/"final_report.md").write_text("\n".join(final)+"\n",encoding="utf-8")
    return report

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--pack",type=Path,default=Path("data_pack/one_user_one_agent_pack")); ap.add_argument("--out",type=Path,default=Path("sample_run")); a=ap.parse_args()
    print(json.dumps(evaluate(a.pack.resolve(),a.out.resolve()),indent=2))
if __name__=="__main__": main()
