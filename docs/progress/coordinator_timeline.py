"""Render docs/progress/coordinator-timeline.png: Coordinator work on a time axis (EET, 2026-11-04).
Solid markers are commit times from git history (main and Research_lab). Edit the lists below to refresh.
Checks that found no change are not recorded in the repo, so they are not drawn."""
import os, sys
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle
INK="#1a1a2e"; GRAY="#5a6272"; GREEN="#2e7d32"; BLUE="#1d5fb8"; PURPLE="#6a4fb3"; RED="#b23b3b"
here=os.path.dirname(os.path.abspath(__file__))
asof=sys.argv[1] if len(sys.argv)>1 else "15:45"
m=lambda s:int(s[:2])*60+int(s[3:])
T0,T1=m("14:30"),m("16:00")
W,H=800,905; L,R=120,775
X=lambda t:L+((m(t) if isinstance(t,str) else t)-T0)*(R-L)/(T1-T0)
fig=plt.figure(figsize=(W/100,H/100),dpi=100)
ax=fig.add_axes([0,0,1,1]); ax.set_xlim(0,W); ax.set_ylim(H,0); ax.axis("off")
def T(x,y,s,size=10,color=INK,ha="left",va="top",**k): ax.text(x,y,s,fontsize=size,color=color,ha=ha,va=va,**k)
T(W/2,12,"Coordinator work timeline, 2026-11-04 (EET)",17,INK,"center",fontweight="bold")
T(W/2,40,f"As of {asof} EET. Solid markers are recorded commit times. Hatched is planned, not yet happened.",10,GRAY,"center")
lanes=[("Chart\npublications",100,172,GREEN,"#f4faf4"),("Builder and\nreview",178,256,BLUE,"#f3f7fd"),("Research\nand Eva",264,392,PURPLE,"#f7f4fc"),("Planned",400,452,GRAY,"#f7f7f7")]
for name,y0,y1,c,fc in lanes:
    ax.add_patch(Rectangle((L-8,y0),R-L+16,y1-y0,fc=fc,ec=c,lw=1))
    T(L-14,(y0+y1)/2,name,10,c,"right","center",fontweight="bold")
AY=462
ax.plot([L,R],[AY,AY],color=INK,lw=1.2)
for t in range(T0,T1+1,10):
    big=t%30==0; x=X(t)
    ax.plot([x,x],[AY,AY+(7 if big else 4)],color=INK,lw=1)
    if big:
        T(x,AY+10,f"{t//60:02d}:{t%60:02d}",10,INK,"center"); ax.plot([x,x],[100,452],color="#d8d8e0",lw=0.6,zorder=0)
T((L+R)/2,AY+30,"Time of day, EET",9.5,GRAY,"center")
for t,c in [("14:40",RED),(asof,INK)]: ax.plot([X(t),X(t)],[92,452],color=c,lw=1.3,ls="--",zorder=1)
T(X("14:40")+3,78,"baseline frozen 14:40",9,RED)
T(X(asof)-3,78,"now "+asof,9,INK,"right",fontweight="bold")
def dot(t,y,c): ax.scatter([X(t)],[y],s=34,color=c,zorder=4,edgecolor="white",lw=0.8)
def num(t,y,n,c,diamond=False):
    ax.add_patch(Circle((X(t),y),9,fc=c,ec="white",lw=1,zorder=4)); T(X(t),y,str(n),8.5,"white","center","center",fontweight="bold",zorder=5)
upd=["14:40","14:45","14:50","15:01","15:05","15:06","15:17","15:21","15:23","15:25","15:27","15:29","15:32"]
for t in upd: dot(t,119,GREEN)
T(L,134,"13 chart publications, 14:40 to 15:32 (recorded commits only).\nThe repo does not show which, if any, came from a scheduled check.",8.6,GRAY,fontstyle="italic",wrap=False)
B=[("14:49",0,"Builder pushes fix 45cec13"),("15:02",1,"Coordinator assigns next Builder task (reviewer-skip guard)"),
   ("15:04",0,"Reviewer verdict: changes required"),("15:06",1,"Coordinator reverses WP7 credit (changes-required is not a pass)")]
C=[("14:42",0,"Researcher: literature scan"),("14:52",0,"Researcher: plan v3 (RW1-RW6)"),("15:10",0,"Researcher: RW5 prior-art notes"),("15:11",1,"Researcher: RW4 liveness design"),
   ("15:24",0,"Coordinator records Nora seat-model trial"),("15:26",1,"Coordinator records citation-gate trial"),("15:28",2,"Eva role defined (team-launcher branch)"),
   ("15:34",0,"Eva review 1: one claim unverified, one caveat missing"),("15:35",1,"Nora correction note"),("15:37",2,"Researcher corrections"),
   ("15:37",0,"Eva review 2: both verified, first loop closed")]
key=[];n=0
for t,r,txt in B: n+=1; num(t,200+r*28,n,BLUE); key.append((n,t,txt,BLUE))
for t,r,txt in C: n+=1; num(t,286+r*28,n,PURPLE); key.append((n,t,txt,PURPLE))
# planned: next scheduled check window starting at asof
ax.add_patch(Rectangle((X(asof),414),X(m(asof)+6)-X(asof),22,fc="white",ec=GRAY,hatch="////",lw=1,zorder=3))
T(X(asof)-8,425,"Next scheduled check: about every 30 minutes\nwhile work is active, exact time not fixed",9,INK,"right","center")
# key
KY=506
T(L-70,KY-4,"Key (numbers on the timeline)",11,INK,fontweight="bold")
for i,(k,t,txt,c) in enumerate(key):
    y=KY+22+i*21
    ax.add_patch(Circle((L-60,y+7),8,fc=c,ec="none")); T(L-60,y+7,str(k),8,"white","center","center",fontweight="bold")
    T(L-44,y,f"{t}  {txt}",9.6,INK)
T(L-70,KY+22+len(key)*21+10,"One closed Eva and Nora review loop is process evidence. It is not a standing pass and earns no milestone credit.",9,GRAY,fontstyle="italic")
T(L-70,KY+22+len(key)*21+30,"Trigger work (lanes 2 and 3) has no schedule: it happens when a draft, review, test result or blocker arrives.",9,GRAY,fontstyle="italic")
fig.savefig(os.path.join(here,"coordinator-timeline.png"),dpi=100); plt.close(fig)
