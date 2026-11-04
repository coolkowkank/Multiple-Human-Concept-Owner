"""Render docs/progress/team.png: the current Project Team. Imported by render_progress.py.
Facts come from docs/developers.md and the roster chart on team-launcher; update TEAM_NOTES when they change."""
import os, math
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.patches import Circle, FancyBboxPatch, Polygon

INK = "#1a1a2e"; GRAY = "#5a6272"; ARROW = "#8a8fa3"; PURPLE = "#8b7ec8"

def render(here, updated):
    W, H = 1180, 1740
    fig = plt.figure(figsize=(W/100, H/100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
    img = lambda n: mpimg.imread(os.path.join(here, "avatars", n + ".png"))
    def text(x, y, s, size=12, color=GRAY, weight="normal", style="normal", ha="center"):
        ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, fontstyle=style, ha=ha, va="top")
    def node(cx, cy, r, name=None, icon=None, bg=PURPLE, fs=22):
        if name:
            ax.imshow(img(name), extent=(cx-r, cx+r, cy+r, cy-r), zorder=3)
        else:
            ax.add_patch(Circle((cx, cy), r, fc=bg, ec="none", zorder=3))
            ax.text(cx, cy+1, icon, fontsize=fs, color="white", fontweight="bold", ha="center", va="center", zorder=4)
        ax.set_xlim(0, W); ax.set_ylim(H, 0)
    BADGE = {"Gq": "#e8553d", "Ce": "#1d6fb8", "Rq": PURPLE}
    def badge(cx, cy, key, r=9):
        ax.add_patch(Circle((cx, cy), r, fc=BADGE[key], ec="none", zorder=3))
        ax.text(cx, cy+0.5, key, fontsize=7, color="white", fontweight="bold", ha="center", va="center", zorder=4)
    def tline(x, y, s_, size=10, key=None):
        t = ax.text(x, y, s_, fontsize=size, color=GRAY, ha="center", va="top")
        if key:
            fig.canvas.draw()
            bb = t.get_window_extent(fig.canvas.get_renderer()).transformed(ax.transData.inverted())
            badge(min(bb.x0, bb.x1) - 13, y + 7, key)
        return t
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
    text(W/2, 14, "Current Project Team", 22, INK, "bold")
    text(W/2, 46, "Latest update: " + updated, 12, GRAY)
    OWN=(590,118,46); COR=(590,335,46); RES=(190,1040,40); EVA=(450,1040,40); BLD=(700,1040,40); REV=(990,1040,46)
    node(OWN[0],OWN[1],OWN[2],"coolkowkank"); node(COR[0],COR[1],COR[2],"instinct-telkomsel")
    node(BLD[0],BLD[1],BLD[2],"coolkowkank-bot"); node(REV[0],REV[1],REV[2],"instinct-christina")
    node(RES[0],RES[1],RES[2],"researcher-role"); node(EVA[0],EVA[1],EVA[2],icon="✓",bg="#2a9d8f")
    RYN=(230,545,34); AST=(930,335,46)
    node(RYN[0],RYN[1],RYN[2],icon="R",bg="#4a6fa5",fs=20); node(AST[0],AST[1],AST[2],icon="S",bg="#b0702a",fs=20)
    def labels(c, role, handle, l1, l2=None, l3=None):
        x, y, r = c; text(x, y+r+10, role, 14, INK, "bold"); text(x, y+r+32, handle, 11, GRAY, style="italic")
        for i, ln in enumerate([l1, l2, l3]):
            if not ln: continue
            if isinstance(ln, tuple): tline(x, y+r+52+16*i, ln[0], 10, ln[1])
            else: tline(x, y+r+52+16*i, ln, 10)
    labels(OWN,"Project owner","@coolkowkank","Decision authority: merges, spend, access")
    labels(COR,"Telkomsel - Coordinator","@instinct-telkomsel","Plans, assigns work, tracks progress","Model: not project-configured")
    labels(BLD,"Alex - Builder","@coolkowkank-bot",("gpt-oss-120b (free plan)","Gq"),"via shared bot account")
    labels(REV,"Bill - Independent reviewer","@instinct-christina","Reviews the Builder's pinned commits","Model: not project-configured")
    labels(EVA,"Eva - Evidence verifier","Uses @coolkowkank","shared research token",("Gemma 4 31B (free), trialed","Rq"),"runtime integration pending")
    labels(RES,"Nora - Researcher","Uses @coolkowkank","shared research token",("Nemotron-3 Ultra 550B (free)","Rq"),"synthesis; citations reviewed")
    labels(RYN,"Ryan - Team Resources","active, coordination-run","Route checks + replacement proposals (free only)","Status-draft backup qualified (narrow); code, research: GAP","Model: not project-configured")
    labels(AST,"Sam - Coordinator Assistant","active, status drafts only",("Model: gemma-4-31b-it (free)","Rq"),"Coordinator reviews every draft","Publication stays coordination-run")
    # hierarchy: owner > coordinator > others (plain lines, no arrowheads)
    HL="#b4b8c6"
    arrow((OWN[0],OWN[1]+OWN[2]+78),(COR[0],COR[1]-COR[2]-6))
    arrow((COR[0],COR[1]-COR[2]-6),(OWN[0],OWN[1]+OWN[2]+78))
    text(OWN[0]+14,252,"direction + gates",10,"#8a8fa3",ha="left")
    busy=970
    ax.plot([COR[0],COR[0]],[COR[1]+COR[2]+60,busy],color=HL,lw=2,zorder=1)
    ax.plot([RES[0],REV[0]],[busy,busy],color=HL,lw=2,zorder=1)
    for c in (RES,EVA,BLD,REV): ax.plot([c[0],c[0]],[busy,c[1]-c[2]-4],color=HL,lw=2,zorder=1)
    arrow((COR[0]+COR[2]+8,COR[1]-8),(AST[0]-AST[2]-8,COR[1]-8))
    arrow((AST[0]-AST[2]-8,COR[1]+12),(COR[0]+COR[2]+8,COR[1]+12))
    text((COR[0]+AST[0])/2,COR[1]-34,"status drafts / review",10,"#8a8fa3")
    arrow((RYN[0]+RYN[2]+12,RYN[1]),(COR[0]-6,RYN[1]))
    arrow((COR[0]-6,RYN[1]),(RYN[0]+RYN[2]+12,RYN[1]))
    text((RYN[0]+COR[0])/2+14,RYN[1]-24,"route checks / proposals",10,"#8a8fa3")
    # Dedicated support belongs to Ryan, not a serial layer in the team trunk.
    SR=(120,780,32); SV=(370,780,32); REC=(760,1300,38)
    for c,mark in [(SR,"Rs"),(SV,"V"),(REC,"RE")]: node(c[0],c[1],c[2],icon=mark,bg="#626b7b",fs=18)
    labels(SR,"Ryan's Researcher","requested / pending staffing","Model not configured","Not a running model seat")
    labels(SV,"Ryan's Verifier","requested / pending staffing","Model not configured","One-shot evidence check complete")
    ax.plot([RYN[0],RYN[0]],[690,718],color=HL,lw=1.5)
    ax.plot([SR[0],SV[0]],[718,718],color=HL,lw=1.5)
    for c in (SR,SV): ax.plot([c[0],c[0]],[718,c[1]-c[2]],color=HL,lw=1.5)
    labels(REC,"Recovery Executor","WP4 / WP9 execution assigned","Model not configured","Offline support; not autonomous proof")
    ax.plot([590,590],[busy,1240],color=HL,lw=1.5,zorder=1);ax.plot([590,760],[1240,1240],color=HL,lw=1.5,zorder=1);ax.plot([760,760],[1240,1260],color=HL,lw=1.5,zorder=1)
    # workflow arrows (lateral, not hierarchy)
    arrow((RES[0]+50,RES[1]-12),(EVA[0]-46,EVA[1]-12),"sources + claims",0,-24)
    arrow((EVA[0]-46,EVA[1]+16),(RES[0]+50,RES[1]+16),"returns unsupported",0,2)
    arrow((BLD[0]+46,BLD[1]-12),(REV[0]-52,REV[1]-12),"review request",0,-24)
    arrow((REV[0]-52,REV[1]+16),(BLD[0]+46,BLD[1]+16),"verdicts",0,2)
    ax.annotate("", xy=(0,0), xytext=(0,0))
    ax.annotate("", xy=(0,0), xytext=(0,0))
    # compact provider line (details live in docs)
    y0=1500
    text(60,y0-8,"Provider pool:",12,INK,"bold",ha="left")
    badge(215,y0+2,"Gq",11); text(232,y0-6,"1) Groq: Builder",10,ha="left")
    badge(405,y0+2,"Ce",11); text(422,y0-6,"2) Cerebras: on hold",10,ha="left")
    badge(620,y0+2,"Rq",11); text(637,y0-6,"3) Requesty: free route, Nora and Eva trials",10,ha="left")
    text(60,y0+34,"On demand, not staffed: Architect, Independent QC, Records.  The Coordinator keeps responsibility for accepting reviewed work.",10,ha="left")
    text(40,1600,"Sources: docs/developers.md and the team roster chart on the team-launcher branch, plus the current Researcher assignment.",9,"#8a8fa3",ha="left")
    text(40,1618,"Lines show levels: owner; Coordinator with Sam beside; Ryan on a side branch; teams. Arrows show review loops: Alex and Bill on code, Nora and Eva on sources.",9,"#8a8fa3",ha="left")
    text(40,1636,"Builder commits go through @coolkowkank-bot. Researcher commits: role author, owner @coolkowkank as committer.",9,"#8a8fa3",ha="left")
    fig.savefig(os.path.join(here, "team.png")); plt.close(fig)
