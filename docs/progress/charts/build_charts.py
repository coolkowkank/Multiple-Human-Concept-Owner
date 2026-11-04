"""Build docs/progress/charts/index.html (GitHub Pages Gantt + S-curve) from docs/progress/progress.json.
Run only when progress.json has a real content change."""
import json, pathlib
d = pathlib.Path(__file__).parent
data = json.loads((d.parent / "progress.json").read_text())
(d / "index.html").write_text((d / "template.html").read_text().replace("__DATA__", json.dumps(data, ensure_ascii=False)))
print("wrote charts/index.html, as_of", data["as_of"])
