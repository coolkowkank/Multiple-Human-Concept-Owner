#!/usr/bin/env python3
"""Render docs/progress/gantt.svg and s-curve.svg from progress.json.
Update progress.json (status, credit_at, forecast_end) and rerun."""
import json, os
from datetime import datetime as D
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as md
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

here = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(here, "progress.json")))
P = d["packages"]; asof = D.fromisoformat(d["as_of"][:16])
t = lambda s: D.fromisoformat(s[:16])
CRED = {"verified": 1.0, "partial": 0.5}
COL = {"verified": "#2e7d32", "partial": "#f9a825", "in_progress": "#1565c0", "not_started": "#9e9e9e"}
LAB = {"verified": "Milestone done", "partial": "Partial (50%)", "in_progress": "In progress", "not_started": "Not started"}
plt.rcParams["svg.fonttype"] = "none"; plt.rcParams["font.family"] = "DejaVu Sans"
x0, x1 = D(2026,11,3,12), D(2026,11,5,15)

# Gantt
fig, ax = plt.subplots(figsize=(11, 5.6))
for i, p in enumerate(P):
    y = len(P) - 1 - i; s = t(p["start"])
    if p["status"] in ("verified", "partial"):
        e = t(p["end"]); ax.barh(y, md.date2num(e)-md.date2num(s), left=md.date2num(s), color=COL[p["status"]], height=.55)
    elif p["status"] == "in_progress":
        ax.barh(y, md.date2num(asof)-md.date2num(s), left=md.date2num(s), color=COL["in_progress"], height=.55)
    if "forecast_end" in p:
        fs = asof if p["status"] != "not_started" else s
        fe = t(p["forecast_end"])
        if p["status"] in ("verified","partial"): fs = t(p["end"])
        ax.barh(y, md.date2num(fe)-md.date2num(fs), left=md.date2num(fs), height=.55, facecolor="none", edgecolor="#555", hatch="////", linewidth=.8, linestyle="--")
ax.axvline(md.date2num(asof), color="#c62828", lw=1.4); ax.text(md.date2num(asof), len(P)-.35, " now", color="#c62828", fontsize=8, va="bottom")
ax.set_yticks(range(len(P))); ax.set_yticklabels([f'{p["id"]}  {p["name"]}  ({p["weight"]}%)' for p in reversed(P)], fontsize=8)
ax.set_xlim(md.date2num(x0), md.date2num(x1)); ax.set_ylim(-.6, len(P)-.1)
ax.xaxis.set_major_locator(md.HourLocator(byhour=[0,6,12,18])); ax.xaxis.set_major_formatter(md.DateFormatter("%b %d\n%H:%M"))
ax.tick_params(axis="x", labelsize=7); ax.grid(axis="x", color="#ddd", lw=.6); ax.set_axisbelow(True)
for s_ in ("top","right"): ax.spines[s_].set_visible(False)
h = [Patch(color=COL[k], label=LAB[k]) for k in COL] + [Patch(facecolor="none", edgecolor="#555", hatch="////", label="Forecast (not a commitment)")]
ax.legend(handles=h, fontsize=7, loc="lower center", bbox_to_anchor=(.5, 1.0), ncol=5, frameon=False)
ax.set_title("Gantt chart (times in EET). Solid = observed in repo evidence. Hatched = forecast.", fontsize=9, loc="left", pad=22)
fig.tight_layout(); fig.savefig(os.path.join(here, "gantt.svg")); fig.savefig(os.path.join(here, "gantt.png"), dpi=130); plt.close(fig)

# S-curve
ev = sorted((t(p["credit_at"]), p["weight"]*CRED[p["status"]]) for p in P if p["status"] in CRED)
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
ax.plot(fx, fy, color="#555", lw=1.8, ls="--", label="Forecast baseline set "+asof.strftime("%b %d %H:%M")+" (a guess)")
ax.axvline(md.date2num(asof), color="#c62828", lw=1.2); ax.scatter([asof],[actual], color="#c62828", zorder=5)
ax.set_xlim(md.date2num(x0), md.date2num(x1)); ax.set_ylim(0, 105)
ax.xaxis.set_major_locator(md.HourLocator(byhour=[0,6,12,18])); ax.xaxis.set_major_formatter(md.DateFormatter("%b %d\n%H:%M"))
ax.tick_params(labelsize=7); ax.set_ylabel("Weighted % complete", fontsize=8); ax.grid(color="#ddd", lw=.6)
for s_ in ("top","right"): ax.spines[s_].set_visible(False)
ax.legend(fontsize=8, loc="upper left", frameon=False)
ax.set_title("Progress S-curve (EET). No plan existed before "+asof.strftime("%b %d")+", so there is no planned-vs-actual history.", fontsize=9, loc="left")
fig.tight_layout(); fig.savefig(os.path.join(here, "s-curve.svg")); fig.savefig(os.path.join(here, "s-curve.png"), dpi=130); plt.close(fig)
print("actual", actual)
