"""Dated research outputs, not inferred task duration or additional credit."""
import json,pathlib,datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt,matplotlib.dates as md
h=pathlib.Path(__file__).parent;d=json.loads((h/'progress.json').read_text());R=d['research'];fig,ax=plt.subplots(figsize=(11,4.9))
for j,r in enumerate(R['rows']):
 y=5-j
 for m in r['markers']:
  t=datetime.datetime.fromisoformat(m['at']);ax.scatter(t,y,marker='D',s=48,color='#2e7d32',zorder=4);ax.annotate(t.strftime('%H:%M'),(md.date2num(t),y),xytext=(0,10),textcoords='offset points',ha='center',fontsize=7)
 if not r['markers']:ax.text(.985,y,'No dated output',transform=ax.get_yaxis_transform(),ha='right',color='#666',fontsize=8)
ax.set_yticks(range(6));ax.set_yticklabels([r['id']+' '+r['name'] for r in reversed(R['rows'])],fontsize=9);ax.set_ylim(-.5,5.7);ax.set_xlim(datetime.datetime(2026,11,4,14),datetime.datetime(2026,11,4,20));ax.xaxis.set_major_locator(md.HourLocator());ax.xaxis.set_major_formatter(md.DateFormatter('%H:%M'));ax.grid(axis='x',color='#ddd');ax.set_axisbelow(True)
ax.set_title('Research lane | RW1-RW6 | '+d['as_of'][:16].replace('T',' ')+' EET',loc='left',fontsize=12,pad=16)
fig.text(.02,.10,'Diamonds = dated publications/replays, not task duration, model runtime or completion. RW deadlines are not specified.',fontsize=9)
fig.text(.02,.055,'Researcher role owns the plan; output authorship varies. Proposed implementation is not adopted. No extra S-curve credit.',fontsize=9)
fig.tight_layout(rect=(0,.15,1,1));fig.savefig(h/'research-gantt.png',dpi=130);fig.savefig(h/'research-gantt.svg');plt.close(fig)
