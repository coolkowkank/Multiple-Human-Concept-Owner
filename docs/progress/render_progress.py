#!/usr/bin/env python3
"""Render docs/progress/gantt.svg and s-curve.svg from progress.json.
Update progress.json (status, credit_at, forecast_end) and rerun."""
import json, os
from datetime import datetime as D
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as md
import matplotlib.image as mpimg
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

here = os.path.dirname(os.path.abspath(__file__))
import sys; sys.path.insert(0, here)
d = json.load(open(os.path.join(here, "progress.json")))
P = d["packages"]; asof = D.fromisoformat(d["as_of"][:16])
t = lambda s: D.fromisoformat(s[:16])
CRED = {"verified": 1.0, "partial": 0.5}
COL = {"verified": "#2e7d32", "partial": "#f9a825", "in_progress": "#1565c0", "not_started": "#9e9e9e"}
LAB = {"verified": "Milestone done", "partial": "Partial (50%)", "in_progress": "In progress", "not_started": "Not started"}
plt.rcParams["svg.fonttype"] = "none"; plt.rcParams["font.family"] = "DejaVu Sans"
x0, x1 = D(2026,11,3,12), D(2026,11,5,15)

# Gantt: all rows share the same time axis
G = P + [dict(r, row_type="research") for r in d.get("research",{}).get("rows",[])] + [dict(r,row_type="job") for r in d.get("jobs",[])]
fig, ax = plt.subplots(figsize=(12, 13))
for i, p in enumerate(G):
    y = len(G) - 1 - i
    if p.get("row_type"):
        for e in p.get("markers",[]): ax.plot(md.date2num(t(e["at"])),y,marker="D",color="#5b4f9a",markersize=5)
        if not p.get("markers"): ax.text(md.date2num(x1)-.01,y,"No dated output",ha="right",fontsize=7,color="#666")
        continue
    s = t(p["start"])
    if p["status"] in ("verified", "partial"):
        e = t(p["end"]); ax.barh(y, max(md.date2num(e)-md.date2num(s), 0.012), left=md.date2num(s), color=COL[p["status"]], height=.55)
    elif p["status"] == "in_progress":
        ax.barh(y, md.date2num(asof)-md.date2num(s), left=md.date2num(s), color=COL["in_progress"], height=.55)
    if "forecast_end" in p:
        fs = asof if p["status"] != "not_started" else s
        fe = t(p["forecast_end"])
        if p["status"] in ("verified","partial"): fs = t(p["end"])
        ax.barh(y, md.date2num(fe)-md.date2num(fs), left=md.date2num(fs), height=.55, facecolor="none", edgecolor="#555", hatch="////", linewidth=.8, linestyle="--")
ax.axvline(md.date2num(asof), color="#c62828", lw=1.4); ax.text(md.date2num(asof), len(G)-.35, " now", color="#c62828", fontsize=8, va="bottom")
ppl = d.get("people", {})
icons = {k: mpimg.imread(os.path.join(here, v["icon"])) for k, v in ppl.items()}
ax.text(1.05, len(G)-.05, "Owner + contributors", transform=ax.get_yaxis_transform(), fontsize=8, ha="center", va="bottom", fontweight="bold")
for i, p in enumerate(G):
    y = len(G) - 1 - i
    for j, k in enumerate(p.get("pic", [])):
        ax.add_artist(AnnotationBbox(OffsetImage(icons[k], zoom=0.17), (1.02, y), xycoords=ax.get_yaxis_transform(), frameon=False, annotation_clip=False))
    for j, k in enumerate(p.get("contributors", [])):
        ax.add_artist(AnnotationBbox(OffsetImage(icons[k], zoom=0.1), (1.065 + j*0.03, y), xycoords=ax.get_yaxis_transform(), frameon=False, annotation_clip=False))
    if "baseline_end" in p:
        ax.plot([md.date2num(t(p["baseline_end"]))], [y], marker="D", color="#c62828", markersize=5, zorder=6)
ax.set_yticks(range(len(G))); ax.set_yticklabels([p["id"]+"  "+p["name"]+(" ("+str(p["weight"])+"%)" if "weight" in p else "") for p in reversed(G)], fontsize=8)
ax.set_xlim(md.date2num(x0), md.date2num(x1)); ax.set_ylim(-.6, len(G)-.1)
ax.xaxis.set_major_locator(md.HourLocator(byhour=[0,6,12,18])); ax.xaxis.set_major_formatter(md.DateFormatter("%b %d\n%H:%M"))
ax.tick_params(axis="x", labelsize=7); ax.grid(axis="x", color="#ddd", lw=.6); ax.set_axisbelow(True)
for s_ in ("top","right"): ax.spines[s_].set_visible(False)
h = [Patch(color=COL[k], label=LAB[k]) for k in COL] + [Patch(facecolor="none", edgecolor="#555", hatch="////", label="Forecast (not a commitment)"), Line2D([0],[0], marker="D", color="w", markerfacecolor="#c62828", markersize=6, label="Baseline end, frozen "+d["baseline"]["set_at"][11:16])]
ax.legend(handles=h, fontsize=7, loc="lower center", bbox_to_anchor=(.5, 1.0), ncol=3, frameon=False)
ax.set_title("Combined Gantt (EET): WP then RW then jobs. Purple diamonds = outputs/reviews, not durations.", fontsize=9, loc="left", pad=34)
fig.tight_layout(rect=(0, 0.15, 0.92, 1))
for n, (k, v) in enumerate(ppl.items()):
    yy = 0.12 - n*0.022
    fig.add_artist(AnnotationBbox(OffsetImage(icons[k], zoom=0.17), (0.035, yy), xycoords="figure fraction", frameon=False))
    fig.text(0.06, yy, v.get("alias","")+" ("+v["label"]+"): "+v["role"] if v.get("alias") else v["label"]+": "+v["role"], fontsize=8, va="center")
fig.text(0.02, 0.143, d.get("pic_note",""), fontsize=7, color="#555")
fig.savefig(os.path.join(here, "gantt.svg")); fig.savefig(os.path.join(here, "gantt.png"), dpi=130); plt.close(fig)

# S-curve
ev = sorted((t(e["at"]), e["credit"]) for p in P if p["status"] in CRED for e in p.get("credit_history", [{"at":p["credit_at"],"credit":p["weight"]*CRED[p["status"]]}]))
ax_, ay_ = [x0], [0]; c = 0
for tm, w in ev:
    ax_ += [tm, tm]; ay_ += [c, c+w]; c += w
ax_.append(asof); ay_.append(c)
actual = c
# forecast: remaining credit lands at forecast_end
fe = []; c2 = actual
rem = []
for p in P:
    cur = p["weight"]*CRED.get(p["status"], 0)
    if cur < p["weight"] and "forecast_end" in p:
        rem.append((t(p["forecast_end"]), p["weight"]-cur))
rem.sort(); fx = [asof]; fy = [actual]
for tm, w in rem:
    fx += [tm, tm]; fy += [c2, c2+w]; c2 += w
fig, ax = plt.subplots(figsize=(9, 4.6))
ax.plot(ax_, ay_, color=COL["verified"], lw=2.2, label=f"Actual weighted milestone progress, incl. partial credit: {actual:.1f}%")
B = d["baseline"]; bx = [t(B["set_at"])]; by = [B["start_pct"]]; cb = B["start_pct"]
for tm, w in sorted((t(a), b) for a, b in B["steps"]):
    bx += [tm, tm]; by += [cb, cb+w]; cb += w
ax.plot(bx, by, color="#c62828", lw=2.6, alpha=.35, label="Baseline forecast, frozen "+B["set_at"][11:16]+" (a guess, never edited)")
ax.plot(fx, fy, color="#333", lw=1.6, ls="--", label="Current forecast, updated "+asof.strftime("%H:%M"))
ax.axvline(md.date2num(asof), color="#c62828", lw=1.2); ax.scatter([asof],[actual], color="#c62828", zorder=5)
ax.set_xlim(md.date2num(x0), md.date2num(x1)); ax.set_ylim(0, 105)
ax.xaxis.set_major_locator(md.HourLocator(byhour=[0,6,12,18])); ax.xaxis.set_major_formatter(md.DateFormatter("%b %d\n%H:%M"))
ax.tick_params(labelsize=7); ax.set_ylabel("Weighted % complete", fontsize=8); ax.grid(color="#ddd", lw=.6)
for s_ in ("top","right"): ax.spines[s_].set_visible(False)
ax.legend(fontsize=8, loc="upper left", frameon=False)
ax.set_title("Progress S-curve (EET). No plan existed before "+asof.strftime("%b %d")+", so there is no planned-vs-actual history.", fontsize=9, loc="left")
fig.tight_layout(); fig.savefig(os.path.join(here, "s-curve.svg")); fig.savefig(os.path.join(here, "s-curve.png"), dpi=130); plt.close(fig)
import team_chart
team_chart.render(here, asof.strftime("%Y-%m-%d %H:%M EET"))
print("actual", actual)
