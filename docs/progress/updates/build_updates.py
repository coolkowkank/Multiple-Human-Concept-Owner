import json,pathlib
d=pathlib.Path(__file__).parent
data=json.loads((d/"updates.json").read_text())
(d/"index.html").write_text((d/"template.html").read_text().replace("__DATA__",json.dumps(data,ensure_ascii=False)))
print("wrote updates/index.html,",len(data["items"]),"items")
