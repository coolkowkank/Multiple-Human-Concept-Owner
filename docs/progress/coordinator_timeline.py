"""Export one completed calendar day's recorded timeline events, never a partial-day archive.
Example: python docs/progress/coordinator_timeline.py --day 2026-11-04 --as-of 2026-11-04T23:59 --output docs/progress/archive/2026-11-04-coordinator-timeline.png
Reads events.json and adds main's same-day chart/status publications through the cutoff.
"""
import argparse,json,pathlib,subprocess,datetime,textwrap,os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle,Rectangle
p=argparse.ArgumentParser();p.add_argument('--day',required=True);p.add_argument('--as-of',required=True);p.add_argument('--output',required=True);a=p.parse_args()
here=pathlib.Path(__file__).parent
if datetime.date.fromisoformat(a.day)>=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=2))).date():raise SystemExit('Archive requires a completed EET day')
data=json.loads((here/'timeline/events.json').read_text());ev=[e for e in data['events'] if e['day']==a.day and e['time']<=a.as_of[11:16]]
seen={e['id'] for e in ev};env=dict(os.environ,TZ='Europe/Helsinki')
log=subprocess.check_output(['git','log','origin/main','--date=format-local:%Y-%m-%d %H:%M','--format=%ad|%h|%s','--since='+a.day+'T00:00:00+02:00','--until='+a.day+'T23:59:59+02:00','--','README.md','docs/progress'],text=True,env=env)
for ln in log.splitlines():
 ts,sha,title=ln.split('|',2)
 if title.startswith('README: repin') or 'cache-bust' in title or 'restore dropped' in title or 'pub-'+sha in seen:continue
 ev.append(dict(id='pub-'+sha,day=a.day,time=ts[11:],kind='publication',title=title,status='Recorded main publication, not proof of a check unless its status record says so.',evidence=[dict(label='Commit '+sha,url='https://github.com/coolkowkank/Multiple-Human-Concept-Owner/commit/'+sha)]))
# Independent acceptance is a separate later event; preserve the earlier blocking/pending records.
if a.day=='2026-11-04':ev.append(dict(id='review-66a12f4-2103',day=a.day,time='21:03',kind='trigger',lane='Team and docs',title='Eva source-schema fix: independent offline acceptance',status='279 full /83 focused tests independently passed. Offline integration implemented/mock-tested; blocked on qualified assigned model/live verification. No completed Eva check or progress credit. Whole normalized claim-set fingerprint only, not semantic budget protection.',evidence=[]))
ev.sort(key=lambda e:(e['time'],e['id']));out=pathlib.Path(a.output);out.with_suffix('.json').write_text(json.dumps(dict(day=a.day,asOf=a.as_of,timezone='Europe/Helsinki',events=ev),indent=1)+'\n')
colors=['#415269','#2165a2','#7450a8','#2a8060'];lanes=['Chart publications','Builder and review','Research and Eva','Team and docs'];groups=[[],[],[],[]]
for i,e in enumerate(ev,1):
 e['number']=i;k=0 if e['kind']=='publication' else {'Builder and review':1,'Research and Eva':2,'Team and docs':3}.get(e.get('lane'),3);groups[k].append(e)
key=[]
for e in ev:
 lines=textwrap.wrap(f"{e['number']}. {e['time']}  {e['title']}",width=155);key.append(lines)
W=2400;L,R=250,2330;t0=0;t1=24*60
X=lambda s:L+((int(s[:2])*60+int(s[3:]))-t0)*(R-L)/(t1-t0)
heights=[]
for es in groups:
 rows=[]
 for e in es:
  x=X(e['time']);r=next((i for i,last in enumerate(rows) if x-last>=26),len(rows))
  if r==len(rows):rows.append(x)
  else:rows[r]=x
 heights.append(max(165,50+len(rows)*27))
chartend=135+sum(heights)+40;keystart=chartend+160
H=keystart+70+sum(len(x)*19+9 for x in key);fig=plt.figure(figsize=(W/100,H/100),dpi=100);ax=fig.add_axes([0,0,1,1]);ax.set_xlim(0,W);ax.set_ylim(H,0);ax.axis('off')
T=lambda x,y,s,**kw:ax.text(x,y,s,va='top',fontfamily='DejaVu Sans',**kw)
T(55,25,'Coordinator timeline - '+a.day,fontsize=23,fontweight='bold');T(55,68,f'Completed EET day, cutoff {a.as_of[11:]} | {len(ev)} recorded events | numbered markers are outputs/reviews, never durations',fontsize=12,color='#555')
L,R=250,2330;t0=0;t1=24*60;X=lambda s:L+((int(s[:2])*60+int(s[3:]))-t0)*(R-L)/(t1-t0)
for k,es in enumerate(groups):
 y=135+sum(heights[:k])+k*10;ax.add_patch(Rectangle((L,y),R-L,heights[k],facecolor='#f6f7f8',edgecolor='#ddd'));T(45,y+65,lanes[k],fontsize=13,fontweight='bold',color=colors[k]);rows=[]
 for e in es:
  x=X(e['time']);r=next((i for i,last in enumerate(rows) if x-last>=26),len(rows))
  if r==len(rows):rows.append(x)
  else:rows[r]=x
  yy=y+22+r*27;ax.add_patch(Circle((x,yy),11,facecolor=colors[k],edgecolor='white'));ax.text(x,yy,str(e['number']),ha='center',va='center',fontsize=7,color='white',fontweight='bold')
for h in range(0,25,2):
 x=L+(h*60-t0)*(R-L)/(t1-t0);ax.plot([x,x],[127,chartend],color='#ddd',linewidth=.5,zorder=0);T(x,chartend+5,('00:00' if h==24 else f'{h:02d}:00'),fontsize=11,ha='center')
T(55,chartend+55,'No evidence of continuous runtime or idle time is inferred. Checks without new work are not drawn as work.',fontsize=12,color='#555')
T(55,chartend+83,'Earlier pending/blocking entries are retained. Later review entries supersede them without rewriting their history.',fontsize=12,color='#555')
T(55,keystart,'Event key',fontsize=17,fontweight='bold');y=keystart+35
for lines in key:
 T(55,y,'\n'.join(lines),fontsize=10);y+=len(lines)*19+9
fig.savefig(out,dpi=100);plt.close(fig);print(len(ev),'events',W,H,out)
