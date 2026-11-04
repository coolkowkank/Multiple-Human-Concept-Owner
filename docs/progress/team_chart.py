"""Render docs/progress/team.png: the current Project Team. Imported by render_progress.py.
Facts come from docs/developers.md and the roster chart on team-launcher; update TEAM_NOTES when they change."""
import os, math
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.patches import Circle, FancyBboxPatch, Polygon

INK = "#1a1a2e"; GRAY = "#5a6272"; ARROW = "#8a8fa3"; PURPLE = "#8b7ec8"

def render(here, updated):
    W, H = 1100, 900
    fig = plt.figure(figsize=(W/100, H/100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
    img = lambda n: mpimg.imread(os.path.join(here, "avatars", n + ".png"))
    def text(x, y, s, size=12, color=GRAY, weight="normal", style="normal", ha="center"):
        ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, fontstyle=style, ha=ha, va="top")
    def node(cx, cy, r, name=None, icon=None, bg=PURPLE):
        if name:
            ax.imshow(img(name), extent=(cx-r, cx+r, cy+r, cy-r), zorder=3)
        else:
            ax.add_patch(Circle((cx, cy), r, fc=bg, ec="none", zorder=3))
            ax.text(cx, cy+2, icon, fontsize=22, color="white", fontweight="bold", ha="center", va="center", zorder=4)
        ax.set_xlim(0, W); ax.set_ylim(H, 0)
    def arrow(p1, p2, label=None, lx=0, ly=0, rad=0.0):
        dx, dy = p2[0]-p1[0], p2[1]-p1[1]; d = math.hypot(dx, dy)
        ux, uy = dx/d, dy/d
        a = (p1[0]+ux*0, p1[1]+uy*0); b = p2
        n = 40; cxp = (a[0]+b[0])/2 - uy*rad*d; cyp = (a[1]+b[1])/2 + ux*rad*d
        pts = [((1-t)**2*a[0]+2*(1-t)*t*cxp+t*t*b[0], (1-t)**2*a[1]+2*(1-t)*t*cyp+t*t*b[1]) for t in [i/n for i in range(n+1)]]
        ax.plot([p[0] for p in pts[:-2]], [p[1] for p in pts[:-2]], color=ARROW, lw=1.5, zorder=2)
        tx, ty = pts[-1][0]-pts[-3][0], pts[-1][1]-pts[-3][1]; tl = math.hypot(tx, ty); tx, ty = tx/tl, ty/tl
        tip = pts[-1]; px, py = -ty*6, tx*6
        ax.add_patch(Polygon([tip, (tip[0]-14*tx+px, tip[1]-14*ty+py), (tip[0]-14*tx-px, tip[1]-14*ty-py)], fc=ARROW, ec="none"))
        if label: text((a[0]+b[0])/2+lx, (a[1]+b[1])/2+ly, label, 10, "#8a8fa3")
    text(W/2, 14, "Project Team", 22, INK, "bold")
    text(W/2, 46, "Latest update: " + updated, 12, GRAY)
    OWN=(550,130,46); RES=(140,380,40); COR=(390,380,46); BLD=(630,380,40); REV=(920,380,46)
    node(OWN[0],OWN[1],OWN[2],"coolkowkank"); node(COR[0],COR[1],COR[2],"instinct-telkomsel")
    node(BLD[0],BLD[1],BLD[2],"coolkowkank-bot"); node(REV[0],REV[1],REV[2],"instinct-christina")
    node(RES[0],RES[1],RES[2],"researcher-role")
    def labels(c, role, handle, l1, l2=None):
        x, y, r = c; text(x, y+r+10, role, 14, INK, "bold"); text(x, y+r+32, handle, 11, GRAY, style="italic")
        text(x, y+r+52, l1, 10)
        if l2: text(x, y+r+68, l2, 10)
    labels(OWN,"Project owner","@coolkowkank","Decision authority: merges, spend, access")
    labels(COR,"Coordinator","@instinct-telkomsel","Plans, assigns work, runs the","launcher, tracks progress")
    labels(BLD,"Builder","@coolkowkank-bot","Model: Groq gpt-oss-120b (free plan)","Shared bot account, not a model identity")
    labels(REV,"Independent reviewer","@instinct-christina","Reviews the Builder's pinned commits")
    labels(RES,"Researcher","role, no GitHub account","Literature and public-system","R&D; proposes, no product edits")
    arrow((OWN[0]-60,OWN[1]+8),(COR[0]+8,COR[1]-58),"direction + gates",-70,-30,0.1)
    arrow((OWN[0]+60,OWN[1]+8),(REV[0]-8,REV[1]-58),"direction + gates",80,-30,-0.1)
    arrow((COR[0]+52,COR[1]-8),(BLD[0]-46,BLD[1]-8),"assigns tasks",0,-24)
    arrow((BLD[0]+46,BLD[1]-12),(REV[0]-52,REV[1]-12),"review request",0,-24)
    arrow((REV[0]-52,REV[1]+16),(BLD[0]+46,BLD[1]+16),"verdicts",0,2)
    arrow((RES[0]+46,RES[1]),(COR[0]-56,COR[1]),"insights",0,-22)
    ax.annotate("", xy=(0,0), xytext=(0,0))
    # model pool
    ax.add_patch(FancyBboxPatch((90,545),920,165,boxstyle="round,pad=4,rounding_size=10",fc="#fafafc",ec="#c9ccd4",lw=1.2,ls="--"))
    text(W/2,556,"Standby model pool: qualified providers, not team seats",13,INK,"bold")
    node(300,625,26,icon="Ce"); node(790,625,26,icon="Rq")
    text(300,656,"Cerebras (on hold)",12,INK,"bold"); text(300,675,"key and tool calls checked; credit ledger unverified",10)
    text(790,656,"Requesty (standby)",12,INK,"bold"); text(790,675,"zero-price model verified; one bounded run done",10)
    ax.add_patch(FancyBboxPatch((90,735),920,76,boxstyle="round,pad=4,rounding_size=10",fc="white",ec="#c9ccd4",lw=1.2))
    text(W/2,745,"On demand: Architect, Independent QC, Records",12,INK,"bold")
    text(W/2,767,"Blueprint roles activated only when a task needs them. None is staffed today.",10)
    text(W/2,785,"Builder and independent reviewer work in a direct loop; the Coordinator assigns work and checks the completed loop.",10)
    text(40,840,"Sources: docs/developers.md and the team roster chart on the team-launcher branch, plus the current Researcher assignment.",9,"#8a8fa3",ha="left")
    text(40,858,"@coolkowkank-bot authenticates model pushes and is the committer identity on model commits. Models never appear as separate GitHub accounts.",9,"#8a8fa3",ha="left")
    fig.savefig(os.path.join(here, "team.png")); plt.close(fig)
