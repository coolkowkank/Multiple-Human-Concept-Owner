# Current-team chart for coolkowkank/Multiple-Human-Concept-Owner.
# Visual grammar: the owner's reference team-chart style (see diagrams/CHART-STYLE.md) -
# white background, circular GitHub avatars, bold role names + italic handles below each
# node, thin curved labeled hand-off arrows, legend box. Models are icon nodes, never
# GitHub accounts; shared machine accounts are infrastructure, not team members.
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

W, H = 1434, 1394
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
    ax.add_patch(FancyArrowPatch(p1, p2, connectionstyle=f"arc3,rad={rad}", arrowstyle="-|>",
                                 mutation_scale=22, lw=1.6, ls=style, color=color,
                                 shrinkA=shrink, shrinkB=shrink))

# Title
text(W/2, 22, "Multiple-Human-Concept-Owner - current team (2026-11-04)", 27, INK, "bold")

# Legend (top-left)
lb = FancyBboxPatch((22, 62), 356, 116, boxstyle="round,pad=6,rounding_size=12",
                    fc="white", ec="#c9ccd4", lw=1.4)
ax.add_patch(lb)
text(44, 78, "Legend", 17, INK, "bold", ha="left")
ax.plot([44, 100], [130, 130], color=ARROW, lw=1.6, solid_capstyle="round")
ax.add_patch(FancyArrowPatch((100, 130), (120, 130), arrowstyle="-|>", mutation_scale=18, lw=1.6, color=ARROW))
text(140, 118, "labeled hand-off between roles", 13.5, GRAY, ha="left")
ax.plot([44, 120], [162, 162], color=ARROW, lw=1.6, ls=(0, (4, 3)))
text(140, 150, "model work product", 13.5, GRAY, ha="left")

# Nodes: owner top-center, coordinator left, reviewer right, builder bottom-center
OWN, COR, REV, BLD = (717, 282, 74), (310, 715, 74), (1124, 715, 74), (717, 1130, 66)
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
text(COR[0], COR[1]+COR[2]+82, "Coordination + implementation oversight", 15)
# Reviewer labels
text(REV[0], REV[1]+REV[2]+18, "Independent reviewer", 21, INK, "bold")
text(REV[0], REV[1]+REV[2]+50, "@instinct-christina", 16.5, GRAY, style="italic")
text(REV[0], REV[1]+REV[2]+82, "Peer verification (F/P/R/N)", 15)
# Builder labels
text(BLD[0], BLD[1]+BLD[2]+18, "Builder", 21, INK, "bold")
text(BLD[0], BLD[1]+BLD[2]+50, "Groq gpt-oss-120b (free plan)", 16.5, GRAY, style="italic")
text(BLD[0], BLD[1]+BLD[2]+82, "Scoped tasks - edits, commits, pushes", 15)
text(BLD[0], BLD[1]+BLD[2]+110, "via its own tool calls - NOT a GitHub account", 15)

# Arrows
arrow((OWN[0]-60, OWN[1]+40), (COR[0]+30, COR[1]-60), rad=0.25, shrink=78)
text(330, 556, "direction + GO gates", 14.5, ARROW)
arrow((OWN[0]+60, OWN[1]+40), (REV[0]-30, REV[1]-60), rad=-0.25, shrink=78)
text(1090, 556, "direction + gates", 14.5, ARROW)
arrow((COR[0]+80, COR[1]-10), (REV[0]-80, REV[1]-10), rad=0.22, shrink=80)
text(717, 648, "review requests (pinned commit)", 14.5, ARROW)
arrow((REV[0]-80, REV[1]+30), (COR[0]+80, COR[1]+30), rad=0.22, shrink=80)
text(717, 810, "verdicts: verified / new findings", 14.5, ARROW)
arrow((COR[0]+40, COR[1]+66), (BLD[0]-60, BLD[1]-40), rad=0.2, style=(0, (4, 3)), shrink=76)
text(560, 905, "scoped tasks", 14.5, ARROW)
text(560, 932, "<-> reviewed output", 14.5, ARROW)

# Footer: shared machine account is infrastructure, not a team member
text(W-40, H-58, "Shared machine account @coolkowkank-bot authenticates model pushes and is", 13, GRAY, ha="right")
text(W-40, H-34, "the committer identity on model commits - infrastructure, not a team member.", 13, GRAY, ha="right")

out = os.path.join(ROOT, "docs", "team-roster.png")
fig.savefig(out, dpi=100)
print("wrote", out)
