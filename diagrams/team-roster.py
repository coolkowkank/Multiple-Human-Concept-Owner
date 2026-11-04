# Current team roster chart for coolkowkank/Multiple-Human-Concept-Owner.
# Style matches diagrams/formation-chart.py. Regenerate: python3 diagrams/team-roster.py > docs/team-roster.svg
D='#2b2523'; G='#a39a93'; T='#3f7a73'; DG='#8f857d'; MUT='#6a615c'
W,H=1044,985
o=[]; a=o.append
a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Noto Sans, DejaVu Sans, sans-serif">')
a(f'<rect width="{W}" height="{H}" fill="#f4efec"/><rect x="13" y="13" width="{W-26}" height="{H-26}" rx="26" fill="#fff"/>')
def t(x,y,s,size=12.5,fill=MUT,w='400',anchor='start',extra=''):
    a(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{w}" text-anchor="{anchor}" {extra}>{s}</text>')
def human(cx,cy,r=30,col=D):
    a(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#fff" stroke="{col}" stroke-width="2.6"/>')
    k=r/33
    a(f'<g stroke="{col}" stroke-width="2.2" fill="none"><circle cx="{cx}" cy="{cy-8*k}" r="{8*k}"/><path d="M{cx-14*k} {cy+15*k} Q{cx-14*k} {cy+3*k} {cx} {cy+3*k} Q{cx+14*k} {cy+3*k} {cx+14*k} {cy+15*k}"/></g>')
def robot(cx,cy,r=26,col=D,dash=False):
    ds=' stroke-dasharray="6 4"' if dash else ''
    a(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#fff" stroke="{col}" stroke-width="2.6"{ds}/>')
    k=r/33
    a(f'<g stroke="{col}" stroke-width="{2.2*max(k,.6)}" fill="none"><rect x="{cx-12*k}" y="{cy-8*k}" width="{24*k}" height="{19*k}" rx="{5*k}"/><line x1="{cx}" y1="{cy-8*k}" x2="{cx}" y2="{cy-14*k}"/></g><circle cx="{cx}" cy="{cy-14*k}" r="{2*max(k,.7)}" fill="{col}"/><circle cx="{cx-5*k}" cy="{cy+1.5*k}" r="{2*max(k,.7)}" fill="{col}"/><circle cx="{cx+5*k}" cy="{cy+1.5*k}" r="{2*max(k,.7)}" fill="{col}"/>')
def card(x,y,w,h,fill='#faf6f3',stroke='#e6d9d2'):
    a(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="20" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')

t(522,56,'Multiple Human Concept Owner - team roster',30,D,'400','middle','font-family="Noto Serif, DejaVu Serif, serif"')
t(522,86,'As tested 4 Nov 2026 - github.com/coolkowkank/Multiple-Human-Concept-Owner',12.5,MUT,'400','middle')

# Owner
card(52,110,940,108)
human(120,164)
t(170,150,'Project owner - @coolkowkank (human)',15,D,'700')
t(170,172,'Decision authority: GO/no-GO gates, merges to default branch, spend, provider choices, access changes.',12.5)
t(170,192,'Everything below operates inside owner-set boundaries.',11.5,DG)

# Active delivery team
card(52,238,940,372)
t(72,264,'ACTIVE DELIVERY TEAM - exercised in live runs today',13,D,'700',extra='letter-spacing="0.6"')
# Coordinator
robot(150,340)
t(200,322,'Coordinator - @instinct-telkomsel',14,D,'700')
t(200,342,'Personal-assistant seat. Assigns scoped tasks, keeps',12)
t(200,359,'reviews independent, implements the launcher, sole writer',12)
t(200,376,'on working branches (team-launcher, live/*).',12)
t(200,396,'Never decides merge/spend/access.',11.5,DG)
# Reviewer
robot(150,455)
t(200,437,'Independent reviewer (QC) - @instinct-christina',14,D,'700')
t(200,457,'Personal-assistant seat. Peer-verifies pinned commits;',12)
t(200,474,'verdicts become "verified" only on her reproduction.',12)
t(200,491,'VERIFIED the Groq fix loop today (documentation scope).',12)
t(200,511,'Independent: takes no task assignments from the Coordinator.',11.5,DG)
# Builder model - right column
robot(640,340,26,T)
t(690,322,'Builder - Groq openai/gpt-oss-120b',14,D,'700')
t(690,342,'Model seat (free tier). PROVEN today: edits,',12)
t(690,359,'commits and pushes via its own tool calls.',12)
t(690,379,'Every commit author-labelled with the model name;',12)
t(690,396,'transcripts are the evidence.',12)
t(690,416,'A model is not a GitHub account and never',11.5,DG)
t(690,433,'appears in the contributors graph.',11.5,DG)
# Shared identity - right column
a(f'<circle cx="640" cy="500" r="26" fill="#fff" stroke="{G}" stroke-width="2.6"/>')
t(640,506,'GH',13,G,'700','middle')
t(690,482,'Shared GitHub identity - @coolkowkank-bot',14,D,'700')
t(690,502,'Machine account, not a seat: links per-model',12)
t(690,519,'author names into one contributor entry and',12)
t(690,536,'authenticates model pushes (public_repo token;',12)
t(690,553,'models never see it).',12)
t(690,573,'Author, committer and pusher stay three',11.5,DG)
t(690,590,'separate facts.',11.5,DG)

# Configured seats
card(52,630,940,170)
t(72,656,'CONFIGURED SEATS - solid = occupied today, dashed = available',13,D,'700',extra='letter-spacing="0.6"')
seats=[('Coordinator',True),('Builder',True),('Independent QC',True),('Reviewer',False),('Records',False),('Architect',False)]
x=140
for name,on in seats:
    robot(x,722,22,D,not on)
    t(x,766,name,11.5,D if on else DG,'700' if on else '400','middle')
    x+=152
t(72,792,'Seat adapters: mock - queue - cli - http - interactive. Any platform that can run a CLI or answer an HTTP prompt can occupy a seat.',11.5,DG)

# History
card(52,820,940,120)
t(72,846,'HISTORY (closed)',13,D,'700',extra='letter-spacing="0.6"')
t(72,868,'Rehearsal participants Bill-QC and joe-agent (evaluation docs on main, 3 Nov 2026); Claude authored legacy evaluation docs (4 Nov 2026).',12)
t(72,888,'Rehearsal branches archived as tags after 4 Nov cleanup. Conditional model fallbacks (free tiers, unused): Cerebras, Requesty.',12)
t(72,908,'Grounded in commit history and accepted review work only - see developers.md.',11.5,DG)

open('docs/team-roster.svg','w').write('\n'.join(o)+'\n</svg>')
print('svg written')
