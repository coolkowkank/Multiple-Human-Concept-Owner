"""Render docs/team/registry.md (team-launcher) as a scrollable HTML table. Usage: build_legacy.py REGISTRY_MD SHA"""
import sys, re, html, pathlib
src, sha = sys.argv[1], sys.argv[2]
B = f"https://github.com/coolkowkank/Multiple-Human-Concept-Owner/blob/{sha}/docs/team/"
lines = [l for l in open(src).read().splitlines() if l.startswith("|")]
rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in lines]
head, body = rows[0], [r for r in rows[2:]]
def cell(c):
    out = html.escape(c)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f'<a href="{html.escape(B + m.group(2))}">{m.group(1)}</a>' if not m.group(2).startswith("http") else f'<a href="{m.group(2)}">{m.group(1)}</a>', html.unescape(out).replace("&", "&amp;").replace("<", "&lt;")) if "](" in c else out
    return out
th = "".join(f"<th>{html.escape(h)}</th>" for h in head)
tr = "".join("<tr>" + "".join(f"<td>{cell(c)}</td>" for c in r) + "</tr>" for r in body)
page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Legacy Members</title>
<style>body{{margin:0;background:#fbfaf8;color:#1f1c1b;font:16px/1.5 system-ui,sans-serif}}main{{max-width:1100px;margin:0 auto;padding:28px 16px 48px}}h1{{margin:0 0 6px;font-size:30px}}p{{color:#5d5855;margin:6px 0}}a{{color:#1d5fb8}}
summary{{cursor:pointer;font-weight:600;padding:10px 0;min-height:44px}}.box{{max-height:60vh;overflow:auto;border:1px solid #ddd9d3;border-radius:10px;margin-top:14px;background:#fff}}
table{{border-collapse:separate;border-spacing:0;min-width:980px;width:100%;font-size:14px}}th,td{{text-align:left;vertical-align:top;padding:9px 12px;border-bottom:1px solid #eee}}
th{{position:sticky;top:0;background:#f1efea;z-index:2;white-space:nowrap}}td:first-child,th:first-child{{position:sticky;left:0;background:#fbfaf8;z-index:1;font-weight:600}}th:first-child{{z-index:3;background:#f1efea}}</style><link rel="stylesheet" href="../nav.css"><script src="../nav.js"></script></head><body><main>
<h1>Legacy Members</h1><p>Everyone involved in the project: active members, defined but vacant roles, and historical contributors. Scroll the table sideways and down. The header and first column stay in view.</p>
<p>Source of truth: <a href="{B}registry.md">docs/team/registry.md</a> (team-launcher @ {sha[:7]}). <code>*</code> marks an instance with repo evidence of work. "unknown / unconfirmed" is not a claim of inactivity.</p>
<details open><summary>Legacy Members: {len(body)} entries (click to collapse or expand)</summary><div class="box" tabindex="0" aria-label="Legacy Members table, scrolls"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div></details>
</main></body></html>'''
pathlib.Path(__file__).with_name("index.html").write_text(page)
print("rows", len(body))
