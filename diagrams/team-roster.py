# Current-team chart for coolkowkank/Multiple-Human-Concept-Owner.
# Visual grammar: the owner's reference team-chart style (see diagrams/CHART-STYLE.md) -
# white background, circular GitHub avatars, bold role names + italic handles below each
# node, thin curved labeled hand-off arrows, legend box. The Builder seat is a model
# (icon node) labeled with the shared machine account it acts through (@coolkowkank-bot),
# with the model name kept on the node; never write "no GitHub account".
# Regenerate: python3 diagrams/team-roster.py  (writes docs/team-roster.png)
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch
import urllib.request
from PIL import Image
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AV = os.path.join(HERE, ".avatars")  # cached GitHub avatars (gitignored)
os.makedirs(AV, exist_ok=True)

INK = "#1a1a2e"; GRAY = "#5a6272"; ARROW = "#8a8fa3"; PURPLE = "#8b7ec8"

def avatar(login):
    p = os.path.join(AV, login + ".png")
    if not os.path.exists(p):
        urllib.request.urlretrieve(f"https://github.com/{login}.png?size=200", p)
    im = Image.open(p).convert("RGBA").resize((200, 200))
    # circular alpha mask - the chart style clips avatars to circles
    mask = Image.new("L", (200, 200), 0)
    from PIL import ImageDraw
    ImageDraw.Draw(mask).ellipse((0, 0, 200, 200), fill=255)
    im.putalpha(mask)
    return np.asarray(im)

W, H = 1434, 1010
fig = plt.figure(figsize=(W/100, H/100), dpi=100)
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
ax.add_patch(plt.Rectangle((0, 0), W, H, color="white"))

def text(x, y, s, size=15, color=GRAY, weight="normal", style="normal", ha="center"):
    ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, fontstyle=style, ha=ha, va="top")

def node(cx, cy, r, img=None, icon=None, icon_bg=PURPLE):
    if img is not None:
        ax.imshow(img, extent=(cx-r, cx+r, cy+r, cy-r), zorder=3)
        ax.add_patch(Circle((cx, cy), r, fill=False, ec="#5b8ac4", lw=2.5, zorder=4))
    else:
        ax.add_patch(Circle((cx, cy), r, fc=icon_bg, ec="none"))
        ax.text(cx, cy+12, icon, fontsize=34, color="white", fontweight="bold", ha="center", va="center")

def arrow(p1, p2, rad=0.0, style="-", color=ARROW, shrink=72):
    # Deterministic hand-drawn arc + triangle head. (FancyArrowPatch/annotate rendered
    # heads at the wrong end under this figure's inverted y-axis; verified by pixel
    # inspection. Head is ALWAYS at p2 here.)
    import math
    dx, dy = p2[0]-p1[0], p2[1]-p1[1]
    d = math.hypot(dx, dy) or 1
    nx, ny = -dy/d, dx/d
    mx, my = (p1[0]+p2[0])/2, (p1[1]+p2[1])/2
    cx, cy = mx + nx*rad*d, my + ny*rad*d
    n = 60
    pts = [((1-t)**2*p1[0] + 2*(1-t)*t*cx + t*t*p2[0],
            (1-t)**2*p1[1] + 2*(1-t)*t*cy + t*t*p2[1]) for t in (i/n for i in range(n+1))]
    # cumulative-length trim of `shrink` px at both ends
    seg = [math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1]) for i in range(n)]
    cum = [0.0]
    for L in seg: cum.append(cum[-1] + L)
    total = cum[-1]
    def at(dist):  # point at arc-length dist from p1
        for i in range(n):
            if cum[i+1] >= dist:
                f = 0 if seg[i] == 0 else (dist - cum[i]) / seg[i]
                return (pts[i][0] + f*(pts[i+1][0]-pts[i][0]), pts[i][1] + f*(pts[i+1][1]-pts[i][1]))
        return pts[-1]
    lo, hi = shrink, total - shrink
    sub = [at(lo + (hi-lo)*i/40) for i in range(41)]
    xs, ys = [p[0] for p in sub], [p[1] for p in sub]
    ax.plot(xs, ys, color=color, lw=1.6, ls=style, solid_capstyle="round", zorder=2)
    # head triangle at the p2 end, tangent along the last segment
    tx, ty = sub[-1][0]-sub[-3][0], sub[-1][1]-sub[-3][1]
    tl = math.hypot(tx, ty) or 1; tx, ty = tx/tl, ty/tl
    tipx, tipy = sub[-1]
    bx, by = tipx - 16*tx, tipy - 16*ty
    px, py = -ty*7, tx*7
    ax.add_patch(plt.Polygon([(tipx, tipy), (tipx - 16*tx + px, tipy - 16*ty + py),
                              (tipx - 16*tx - px, tipy - 16*ty - py)], closed=True,
                             fc=color, ec="none", zorder=2))

# Title
text(W/2, 22, "Multiple-Human-Concept-Owner - current team (2026-11-04)", 27, INK, "bold")

# Legend (top-left)
lb = FancyBboxPatch((22, 62), 356, 78, boxstyle="round,pad=6,rounding_size=12",
                    fc="white", ec="#c9ccd4", lw=1.4)
ax.add_patch(lb)
text(44, 78, "Legend", 17, INK, "bold", ha="left")
ax.plot([44, 100], [118, 118], color=ARROW, lw=1.6, solid_capstyle="round")
ax.add_patch(FancyArrowPatch((100, 118), (120, 118), arrowstyle="-|>", mutation_scale=18, lw=1.6, color=ARROW))
text(140, 106, "labeled hand-off between roles", 13.5, GRAY, ha="left")

# Nodes: owner top-center; coordinator, builder, reviewer in one row (builder in the middle)
OWN, COR, REV, BLD = (717, 282, 74), (240, 715, 74), (1194, 715, 74), (717, 715, 66)
node(*OWN, img=avatar("coolkowkank"))
node(*COR, img=avatar("instinct-telkomsel"))
node(*REV, img=avatar("instinct-christina"))
node(*BLD, icon="AI")

# Owner labels
text(OWN[0], OWN[1]+OWN[2]+18, "Project owner", 21, INK, "bold")
text(OWN[0], OWN[1]+OWN[2]+50, "@coolkowkank", 16.5, GRAY, style="italic")
text(OWN[0], OWN[1]+OWN[2]+82, "Decision authority: merges, spend, access", 15)
# Coordinator labels
text(COR[0], COR[1]+COR[2]+18, "Coordinator", 21, INK, "bold")
text(COR[0], COR[1]+COR[2]+50, "@instinct-telkomsel", 16.5, GRAY, style="italic")
text(COR[0], COR[1]+COR[2]+82, "Assigns work, checks completed loop", 15)
# Reviewer labels
text(REV[0], REV[1]+REV[2]+18, "Independent reviewer", 21, INK, "bold")
text(REV[0], REV[1]+REV[2]+50, "@instinct-christina", 16.5, GRAY, style="italic")
text(REV[0], REV[1]+REV[2]+82, "Reviews the Builder's pinned commits", 15)
# Builder labels
text(BLD[0], BLD[1]+BLD[2]+18, "Builder", 21, INK, "bold")
text(BLD[0], BLD[1]+BLD[2]+50, "@coolkowkank-bot", 16.5, GRAY, style="italic")
text(BLD[0], BLD[1]+BLD[2]+82, "Model: Groq gpt-oss-120b (free plan)", 15)
text(BLD[0], BLD[1]+BLD[2]+110, "Edits, commits, pushes via its own tool calls", 15)

# Arrows
arrow((OWN[0]-60, OWN[1]+40), (COR[0]+30, COR[1]-60), rad=0.25, shrink=78)
text(160, 600, "direction + GO gates", 14.5, ARROW)
arrow((OWN[0]+60, OWN[1]+40), (REV[0]-30, REV[1]-60), rad=-0.25, shrink=78)
text(1290, 600, "direction + gates", 14.5, ARROW)
# Coordinator <-> Builder: assigns work (upper, into Builder), checks the completed loop (lower, into Coordinator)
arrow((COR[0], BLD[1]-24), (BLD[0], BLD[1]-24), shrink=90)
text(479, BLD[1]-62, "assigns scoped tasks", 14.5, ARROW)
arrow((BLD[0], BLD[1]+24), (COR[0], BLD[1]+24), shrink=90)
text(479, BLD[1]+34, "checks completed review loop", 14.5, ARROW)
# Review loop is directly between Builder and the independent reviewer
arrow((BLD[0], BLD[1]-24), (REV[0], BLD[1]-24), shrink=90)
text(955, BLD[1]-62, "review requests (pinned commit)", 14.5, ARROW)
arrow((REV[0], BLD[1]+24), (BLD[0], BLD[1]+24), shrink=90)
text(955, BLD[1]+34, "review verdicts", 14.5, ARROW)

# Footer: shared machine account is infrastructure, not a team member
text(40, H-64, "@coolkowkank-bot is the shared machine account the Builder acts through:", 13, GRAY, ha="left")
text(40, H-38, "it authenticates model pushes and is the committer identity on model commits.", 13, GRAY, ha="left")

out = os.path.join(ROOT, "docs", "team-roster.png")
fig.savefig(out, dpi=100)
print("wrote", out)
