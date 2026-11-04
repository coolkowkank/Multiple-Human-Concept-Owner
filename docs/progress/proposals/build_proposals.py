import json,pathlib
d=pathlib.Path(__file__).parent
data=json.loads((d/"proposals.json").read_text())
(d/"index.html").write_text((d/"template.html").read_text().replace("__DATA__",json.dumps(data,ensure_ascii=False)))
print("wrote proposals/index.html,",len(data["items"]),"items")
