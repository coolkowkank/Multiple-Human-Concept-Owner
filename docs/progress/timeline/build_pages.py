"""Build the self-contained GitHub Pages view: events.json is inlined into template.html -> index.html."""
import json, pathlib
d = pathlib.Path(__file__).parent
data = json.loads((d / "events.json").read_text())
plan = json.loads((d / "plan.json").read_text())
html = (d / "template.html").read_text().replace("__DATA__", json.dumps(data, ensure_ascii=False)).replace("__PLAN__", json.dumps(plan, ensure_ascii=False))
(d / "index.html").write_text(html)
print("wrote index.html,", len(data["events"]), "events, asOf", data["asOf"])
