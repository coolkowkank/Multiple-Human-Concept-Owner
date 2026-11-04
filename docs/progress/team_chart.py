"""Render docs/progress/team.png: the current Project Team. Imported by render_progress.py.
Facts come from docs/developers.md and the roster chart on team-launcher; update TEAM_NOTES when they change."""
import os, math
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.patches import Circle, FancyBboxPatch, Polygon

INK = "#1a1a2e"; GRAY = "#5a6272"; ARROW = "#8a8fa3"; PURPLE = "#8b7ec8"

def render(here, updated):
    W, H = 1100, 1060
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
    OWN=(550,135,46); COR=(550,335,46); RES=(190,545,40); BLD=(520,545,40); REV=(880,545,46)
    node(OWN[0],OWN[1],OWN[2],"coolkowkank"); node(COR[0],COR[1],COR[2],"instinct-telkomsel")
    node(BLD[0],BLD[1],BLD[2],"coolkowkank-bot"); node(REV[0],REV[1],REV[2],"instinct-christina")
    node(RES[0],RES[1],RES[2],"researcher-role")
    def labels(c, role, handle, l1, l2=None, l3=None):
        x, y, r = c; text(x, y+r+10, role, 14, INK, "bold"); text(x, y+r+32, handle, 11, GRAY, style="italic")
        text(x, y+r+52, l1, 10)
        if l2: text(x, y+r+68, l2, 10)
        if l3: text(x, y+r+84, l3, 10)
    labels(OWN,"Project owner","@coolkowkank","Decision authority: merges, spend, access")
    labels(COR,"Telkomsel - Coordinator","@instinct-telkomsel","Plans, assigns work, tracks progress")
    labels(BLD,"Alex - Builder","@coolkowkank-bot","Groq gpt-oss-120b (free plan)","via shared bot account")
    labels(REV,"Bill - Independent reviewer","@instinct-christina","Reviews the Builder's pinned commits")
    labels(RES,"Nora - Researcher","Uses @coolkowkank","dedicated Researcher token","Nemotron-3 Ultra 550B (Requesty free)","verified-source synthesis; citations reviewed")
    # hierarchy: owner > coordinator > others (plain lines, no arrowheads)
    HL="#b4b8c6"
    ax.plot([OWN[0],COR[0]],[258,COR[1]-COR[2]-4],color=HL,lw=2,zorder=1)
    busy=470
    ax.plot([COR[0],COR[0]],[COR[1]+COR[2]+60,busy],color=HL,lw=2,zorder=1)
    ax.plot([RES[0],REV[0]],[busy,busy],color=HL,lw=2,zorder=1)
    for c in (RES,BLD,REV): ax.plot([c[0],c[0]],[busy,c[1]-c[2]-4],color=HL,lw=2,zorder=1)
    text(OWN[0]+14,262,"direction + gates",10,"#8a8fa3",ha="left")
    # workflow arrows (lateral, not hierarchy)
    arrow((BLD[0]+46,BLD[1]-12),(REV[0]-52,REV[1]-12),"review request",0,-24)
    arrow((REV[0]-52,REV[1]+16),(BLD[0]+46,BLD[1]+16),"verdicts",0,2)
    ax.annotate("", xy=(0,0), xytext=(0,0))
    ax.annotate("", xy=(0,0), xytext=(0,0))
    # model pool
    ax.add_patch(FancyBboxPatch((90,705),920,165,boxstyle="round,pad=4,rounding_size=10",fc="#fafafc",ec="#c9ccd4",lw=1.2,ls="--"))
    text(W/2,716,"Provider pool: standby, not team seats",13,INK,"bold")
    node(300,785,26,icon="Ce"); node(790,785,26,icon="Rq")
    text(300,816,"Cerebras (on hold)",12,INK,"bold"); text(300,835,"key and tool calls checked; credit ledger unverified",10)
    text(790,816,"Requesty (standby)",12,INK,"bold"); text(790,854,"needed manual recovery, skipped Reviewer; not autonomy",10)
    text(790,835,"zero-price model verified; one bounded run",10)
    ax.add_patch(FancyBboxPatch((90,895),920,76,boxstyle="round,pad=4,rounding_size=10",fc="white",ec="#c9ccd4",lw=1.2))
    text(W/2,905,"On demand: Architect, Independent QC, Records",12,INK,"bold")
    text(W/2,927,"Blueprint roles activated only when a task needs them. None is staffed today.",10)
    text(W/2,945,"Lines show the three levels: owner, Coordinator, others. Arrows show the Builder and reviewer feedback loop.",10)
    text(40,1000,"Sources: docs/developers.md and the team roster chart on the team-launcher branch, plus the current Researcher assignment.",9,"#8a8fa3",ha="left")
    text(40,1018,"Builder commits go through @coolkowkank-bot. Researcher commits: role author, owner @coolkowkank as committer.",9,"#8a8fa3",ha="left")
    fig.savefig(os.path.join(here, "team.png")); plt.close(fig)
