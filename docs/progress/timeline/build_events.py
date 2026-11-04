"""Rebuild docs/progress/timeline/events.json from git history. Run in a clone with all branches fetched.
Chart publications come from commits touching README.md or docs/progress on main (image repin commits skipped).
Triggered-work events are listed by hand below with their commit evidence. Times are commit times in EET.
Existing days are never rewritten by a later day's run: keep one entry per event id and only add."""
import json, os, subprocess
REPO="https://github.com/coolkowkank/Multiple-Human-Concept-Owner"
here=os.path.dirname(os.path.abspath(__file__)); out=os.path.join(here,"events.json")
env=dict(os.environ,TZ="Europe/Helsinki")
def log():
    r=subprocess.run(["git","log","origin/main","--date=format-local:%Y-%m-%d %H:%M","--format=%ad|%h|%s","--since=2026-11-04T14:30:00+02:00","--","README.md","docs/progress"],capture_output=True,text=True,env=env).stdout
    return [l.split("|",2) for l in r.strip().splitlines()][::-1]
old={}
if os.path.exists(out): old={e["id"]:e for e in json.load(open(out))["events"]}
ev=[]
for ts,sha,subj in log():
    if subj.startswith("README: repin") or "cache-bust" in subj or "restore dropped" in subj: continue
    d,t=ts.split(" ")
    ev.append(dict(id="pub-"+sha,day=d,time=t,kind="publication",title=subj[:110],status="Published on main. Recorded commit time.",
      evidence=[dict(label="Commit "+sha,url=f"{REPO}/commit/{sha}")]))
def trig(sha,t,title,status,branch=None,lane="Builder and review",extra=None):
    ev.append(dict(id="trg-"+sha,day="2026-11-04",time=t,kind="trigger",lane=lane,title=title,status=status,
      evidence=[dict(label="Commit "+sha,url=f"{REPO}/commit/{sha}")]+(extra or [])))
RV=REPO+"/blob/Research_lab/research/reviews/"
trig("45cec13","14:49","Builder pushes fix 45cec13","Tests reported passing by the Builder run (164 of 164). The independent review that followed returned changes-required, so this earns no Verified credit.")
trig("55e7c7e","15:02","Coordinator assigns next Builder task (reviewer-skip guard)","Task written. Later attempt failed and the guard is still unbuilt.")
trig("a75ce06","15:04","Reviewer verdict: changes required","Verdict recorded in this update commit. The verdict's own timestamp is not recorded, so this is the commit time.")
trig("fb34fc9","15:07","Coordinator reverses WP7 credit","Changes-required is not a pass, so the credit was removed. The Verified criterion was not changed.")
trig("9f6c594","15:38","Builder counter-fix attempt starts","The attempt later stopped at its request limit with no commit or push. The fix is not delivered and the live branch is unchanged.")
trig("321257b","15:51","Execution-tool hardening pinned","Support tooling, not the guard itself. Offline tests reported passing (224 test runs). Not a milestone.")
trig("91e928d","15:53","Reviewer-skip guard attempt starts","Running at snapshot time. Not accepted. Needs tests and an independent review before any credit.")
R="Research and Eva"
trig("b42f670","14:42","Researcher: literature scan","Published on Research_lab. Pending independent source review at the time.",lane=R)
trig("76351f3","14:52","Researcher: plan v3 (RW1-RW6)","Published on Research_lab.",lane=R)
trig("947a498","15:10","Researcher: RW5 prior-art notes","Published on Research_lab. Later reviewed by Eva review 1.",lane=R)
trig("ad93523","15:11","Researcher: RW4 liveness design","Published on Research_lab.",lane=R)
trig("6e5bd37","15:24","Coordinator records Nora seat-model trial","Trial record. 3 requests, zero reported cost. Some citations were wrong, so citation review is required. Earns no milestone credit.",lane=R)
trig("0c52bab","15:26","Coordinator records citation-gate trial","Source-only rerun passed 3 of 3. The citation gate is a workflow policy, not a mechanical gate.",lane=R)
trig("06479b3","15:28","Eva role defined","Role document on team-launcher. A manual review workflow only, with no roster wiring.",lane=R)
trig("3ecde66","15:34","Eva review 1","14 claims checked: 12 supported, 1 partial (resolved by the Coordinator), 1 unverified. Corrections required.",lane=R,extra=[dict(label="Review file",url=RV+"2026-11-04-eva-review-1.md")])
trig("36499b5","15:35","Nora correction note","Response to Eva review 1, written by the Nora seat model. Clearly attributed.",lane=R)
trig("61143ba","15:37","Researcher corrections","Unverified claim marked beside the claim, version caveat added beside the other.",lane=R)
trig("3aff4c6","15:37","Eva review 2","Both corrections verified. One extra phrase stays author-reported, not verified. First loop closed: process evidence only, not a standing pass.",lane=R,extra=[dict(label="Review file",url=RV+"2026-11-04-eva-review-2.md")])
for e in ev:
    if e["id"] in old: e=old[e["id"]]
ev=[old.get(e["id"],e) for e in ev]
for k,v in old.items():
    if k not in {e["id"] for e in ev}: ev.append(v)
ev.sort(key=lambda e:(e["day"],e["time"]))
json.dump(dict(timezone="Europe/Helsinki",note="Recorded events use commit times. Planned items are not events. A check that finds no change leaves no record.",events=ev),open(out,"w"),indent=1)
print(len(ev),"events")
