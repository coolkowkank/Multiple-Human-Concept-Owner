"""Render docs/progress/coordinator-timeline.png: Coordinator work on a time axis (EET, 2026-11-04).
Every solid marker is a timestamp from git history (commit times) on the main or Research_lab branch; edit EVENTS to refresh.
Checks that found no change are not recorded in the repo, so they are not drawn."""
import os, sys
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
INK="#1a1a2e"; GRAY="#5a6272"; GREEN="#2e7d32"; BLUE="#1d5fb8"; ORANGE="#d97800"; RED="#b23b3b"; PURPLE="#6a4fb3"
here=os.path.dirname(os.path.abspath(__file__))
asof=sys.argv[1] if len(sys.argv)>1 else "15:40"
m=lambda s:int(s[:2])*60+int(s[3:])
T0,T1=m("14:30"),m("16:00")
W,H=1400,800; L,R=190,1370
X=lambda t:L+(m(t) if isinstance(t,str) else t)*0+( (m(t) if isinstance(t,str) else t)-T0)*(R-L)/(T1-T0)
fig=plt.figure(figsize=(W/100,H/100),dpi=100)
ax=fig.add_axes([0,0,1,1]); ax.set_xlim(0,W); ax.set_ylim(H,0); ax.axis("off")
ax.text(W/2,16,"Coordinator work timeline, 2026-11-04 (EET)",ha="center",va="top",fontsize=18,fontweight="bold",color=INK)
ax.text(W/2,46,f"As of {asof} EET. Solid markers are recorded events (git commit times). Hatched is planned, not yet happened.",ha="center",va="top",fontsize=10.5,color=GRAY)
lanes=[("Routine:\nchart updates",95,200,GREEN,"#f4faf4"),("Trigger:\nBuilder and review",205,325,BLUE,"#f3f7fd"),
       ("Trigger:\nResearch and Eva",330,620,PURPLE,"#f7f4fc"),("Planned",625,695,GRAY,"#f7f7f7")]
for name,y0,y1,c,fc in lanes:
    ax.add_patch(Rectangle((L-10,y0),R-L+20,y1-y0,fc=fc,ec=c,lw=1))
    ax.text(L-20,(y0+y1)/2,name,ha="right",va="center",fontsize=11,fontweight="bold",color=c)
# axis
AY=720
ax.plot([L,R],[AY,AY],color=INK,lw=1.2)
for t in range(T0,T1+1,10):
    x=X(t); big=(t%30==0)
    ax.plot([x,x],[AY,AY+(8 if big else 4)],color=INK,lw=1)
    if big: ax.text(x,AY+12,f"{t//60:02d}:{t%60:02d}",ha="center",va="top",fontsize=10,color=INK)
    if big: ax.plot([x,x],[95,695],color="#d8d8e0",lw=0.6,zorder=0)
ax.text((L+R)/2,AY+34,"Time of day, EET",ha="center",va="top",fontsize=10,color=GRAY)
# frozen baseline and now
for t,lab,c in [("14:40","baseline frozen 14:40",RED),(asof,"now "+asof,INK)]:
    ax.plot([X(t),X(t)],[88,695],color=c,lw=1.3,ls="--",zorder=1)
ax.text(X("14:40")+4,70,"baseline frozen 14:40",fontsize=9,color=RED,va="top")
ax.text(X(asof)+4,70,"now "+asof,fontsize=9,color=INK,va="top",fontweight="bold")
def pts(times,y,c,marker="o",s=42):
    ax.scatter([X(t) for t in times],[y]*len(times),s=s,color=c,marker=marker,zorder=4,edgecolor="white",lw=0.8)
def lab(t,y,dy,text,c,ha="left"):
    x=X(t); ax.plot([x,x],[y,y+dy],color=c,lw=0.7,zorder=2)
    ax.text(x+(3 if ha=="left" else -3),y+dy+(2 if dy>0 else -2),text,fontsize=8.6,color=INK,va="top" if dy>0 else "bottom",ha=ha)
# lane 1
upd=["14:40","14:45","14:50","15:01","15:05","15:06","15:17","15:21","15:23","15:25","15:27","15:29","15:32"]
y=150; pts(upd,y,GREEN)
for t,tx,dy in [("14:40","First Gantt and S-curve",-8),("14:50","Research plan evidence",-38),("15:06","WP7 credit reversed\n(changes-required)",-8),
                ("15:21","Aliases, access label,\nthree-level team chart",-38),("15:32","Groq pool, provider badges",-8)]:
    lab(t,y,dy,tx,GREEN)
ax.text(L,185,"13 chart updates published. A check that finds no change is not recorded in the repo, so it is not drawn.",fontsize=8.8,color=GRAY,va="top",fontstyle="italic")
# lane 2
y=245
ev2=[("14:49","Builder pushes fix 45cec13",-8),("15:02","Coordinator assigns next Builder task\n(reviewer-skip guard)",44),("15:04","Reviewer verdict:\nchanges required",-8),("15:06","Coordinator reverses WP7 credit",74)]
pts([e[0] for e in ev2],y,BLUE)
for t,tx,dy in ev2: lab(t,y,dy,tx,BLUE)
# lane 3
y=425
ev3=[("14:42","Researcher: literature scan",-8),("14:52","Plan v3 (RW1-RW6)",42),("15:10","RW5 prior-art notes",-8),("15:11","RW4 liveness design",42),
     ("15:24","Nora seat trial recorded",84),("15:26","Citation gate trial",126),("15:28","Eva role defined",-8)]
pts([e[0] for e in ev3],y,PURPLE)
for t,tx,dy in ev3: lab(t,y,dy,tx,PURPLE)
ev3b=[("15:34","Eva review 1:\n1 unverified, 1 caveat missing",-55),("15:35","Nora correction note",70),("15:37","Researcher corrections",112),("15:37","Eva review 2: C5 and C14 verified,\nfirst loop closed",154)]
for t,tx,dy in ev3b:
    pts([t],y,PURPLE,marker="D"); lab(t,y,dy,tx,PURPLE,ha="right" if t=="15:34" else "left")
ax.text(L,600,"Diamonds: the Eva and Nora review loop, 15:34 to 15:37. It is one closed loop, not a standing pass, and earns no milestone credit.",fontsize=8.8,color=GRAY,va="top",fontstyle="italic")
# planned
ax.add_patch(Rectangle((X("15:40"),645),X("15:46")-X("15:40"),22,fc="white",ec=GRAY,hatch="////",lw=1))
ax.text(X("15:40")-10,656,"Next scheduled check, due about 15:40-15:46 (exact time not fixed).\nChecks then repeat about every 30 minutes while work is active.",fontsize=8.8,color=INK,va="center",ha="right")
ax.text(L,672,"Trigger work has no schedule. It happens when a draft, review, test result, failure or blocker arrives.",fontsize=8.8,color=GRAY,va="top",fontstyle="italic")
fig.savefig(os.path.join(here,"coordinator-timeline.png"),dpi=100); plt.close(fig)
