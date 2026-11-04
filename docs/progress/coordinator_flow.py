"""Render docs/progress/coordinator-work.png: the Coordinator's two kinds of work. Run: python3 coordinator_flow.py"""
import os
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
INK="#1a1a2e"; GRAY="#5a6272"; GREEN="#2e7d32"; BLUE="#1d5fb8"; ORANGE="#e08a00"
here=os.path.dirname(os.path.abspath(__file__))
W,H=1180,760
fig=plt.figure(figsize=(W/100,H/100),dpi=100)
ax=fig.add_axes([0,0,1,1]); ax.set_xlim(0,W); ax.set_ylim(H,0); ax.axis("off")
def box(x,y,w,h,title,sub=None,ec=BLUE,fc="#f4f7fc"):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0,rounding_size=8",fc=fc,ec=ec,lw=1.6))
    ax.text(x+w/2,y+(h/2-(20 if sub and '\n' in sub else 9 if sub else 0)),title,ha="center",va="center",fontsize=11,fontweight="bold",color=INK)
    if sub: ax.text(x+w/2,y+h/2+(14 if '\n' in sub else 12),sub,ha="center",va="center",fontsize=8.4,color=GRAY,linespacing=1.3)
def arrow(x1,y1,x2,y2,c=GRAY,ls="-",rad=0):
    ax.add_patch(FancyArrowPatch((x1,y1),(x2,y2),arrowstyle="-|>",mutation_scale=14,color=c,lw=1.6,ls=ls,connectionstyle=f"arc3,rad={rad}"))
ax.text(W/2,22,"Coordinator work: two kinds",ha="center",va="top",fontsize=19,fontweight="bold",color=INK)
ax.text(W/2,52,"How the Coordinator (Telkomsel) works on this project, so you can follow it",ha="center",va="top",fontsize=11,color=GRAY)
# lane 1
ax.add_patch(FancyBboxPatch((20,90),W-40,230,boxstyle="round,pad=0,rounding_size=12",fc="#fbfdfb",ec=GREEN,lw=1.2))
ax.text(36,100,"1. Routine check and update",fontsize=13,fontweight="bold",color=GREEN,va="top")
ax.text(W-36,102,"Scheduled: every 30 minutes while work is active",fontsize=9.5,color=GREEN,va="top",ha="right",fontstyle="italic")
xs=[40,260,480,700]; bw=190
box(xs[0],150,bw,70,"Check progress","commits, tests,\nreviews",GREEN,"#f1f8f1")
box(xs[1],150,bw,70,"Look for stalled work","open items with\nno movement",GREEN,"#f1f8f1")
box(xs[2],150,bw,70,"Check team roles","who owns what,\nwho is blocked",GREEN,"#f1f8f1")
box(xs[3],150,bw,70,"Check chart accuracy","Gantt, S-curve,\nteam chart",GREEN,"#f1f8f1")
for i in range(3): arrow(xs[i]+bw+2,185,xs[i+1]-2,185,GREEN)
box(930,150,210,70,"Anything changed?","",GREEN,"#e6f2e6")
arrow(xs[3]+bw+2,185,928,185,GREEN)
ax.text(1035,240,"Yes: update charts, show time",ha="center",fontsize=9.5,color=INK,va="top")
ax.text(1035,258,"No: no change, no commit",ha="center",fontsize=9.5,color=GRAY,va="top")
ax.text(40,248,"Catches anything the triggers missed. The baseline (frozen 14:40) and the 'Verified' rule never change.",fontsize=9.5,color=GRAY,va="top")
# lane 2
ax.add_patch(FancyBboxPatch((20,360),W-40,300,boxstyle="round,pad=0,rounding_size=12",fc="#fcfaf4",ec=ORANGE,lw=1.2))
ax.text(36,370,"2. Trigger-based work",fontsize=13,fontweight="bold",color=ORANGE,va="top")
ax.text(W-36,372,"When something arrives. Does not wait for the next routine check.",fontsize=9.5,color=ORANGE,va="top",ha="right",fontstyle="italic")
box(40,420,200,110,"Something arrives","draft, review, test result,\nfailure or blocker",ORANGE,"#fff6e5")
box(300,420,190,110,"Route the next action","to the right role:\nBuilder, Researcher, Reviewer",ORANGE,"#fff6e5")
box(550,420,200,110,"Enforce corrections","fixes are read and\naddressed, then re-checked",ORANGE,"#fff6e5")
box(810,420,200,110,"Check acceptance","evidence passes?\nonly then count it",ORANGE,"#fff6e5")
for a,b in [(242,298),(492,548),(752,808)]: arrow(a,475,b,475,ORANGE)
ax.text(1075,445,"Accepted",ha="center",fontsize=10,fontweight="bold",color=GREEN,va="top")
ax.text(1075,462,"counts in progress",ha="center",fontsize=9,color=GRAY,va="top")
arrow(1012,455,1040,455,GREEN)
ax.text(1075,500,"Not accepted",ha="center",fontsize=10,fontweight="bold",color="#b23b3b",va="top")
ax.text(1075,517,"back to corrections",ha="center",fontsize=9,color=GRAY,va="top")
arrow(910,532,650,560,"#b23b3b",rad=-0.25); 
# example strip
ax.text(40,596,"Live example (Research_lab): Eva review 1 found one unverified claim and one missing caveat. The Researcher and Nora corrected them.\nEva review 2 (3aff4c6) verified both. One extra claim stays 'author-reported, not verified'.",fontsize=9.3,color=INK,va="top")
ax.text(40,632,"One review loop closed. This is not a standing pass or runtime automation, and it earns no milestone credit.",fontsize=9.3,color=GRAY,va="top",fontstyle="italic")
# link
arrow(250,322,200,418,GRAY,"--",0.0)
ax.text(270,336,"a routine check can find a missed arrival",fontsize=8.6,color=GRAY,va="top")
ax.text(W/2,675,"Today: the 30-minute check is scheduled. Trigger handling is Coordinator judgment on each arrival.\nThe repo has no automatic gate for it, and review rules are a manual workflow.",ha="center",fontsize=9.2,color=GRAY,va="top")
ax.text(W/2,728,"Criteria are never changed after seeing an outcome.",ha="center",fontsize=9.2,color=GRAY,va="top")
fig.savefig(os.path.join(here,"coordinator-work.png"),dpi=100); plt.close(fig)
