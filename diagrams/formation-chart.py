D='#2b2523'; G='#a39a93'; B='#6b5f59'; T='#3f7a73'; DG='#8f857d'
o=[]
a=o.append
a('''<svg xmlns="http://www.w3.org/2000/svg" width="1044" height="1241" viewBox="0 0 1044 1241" font-family="Noto Sans, DejaVu Sans, sans-serif">
<defs>''')
for n,c in [('d',D),('g',G),('b',B),('t',T),('x',DG)]:
    a(f'<marker id="m{n}" viewBox="0 0 12 10" refX="12" refY="5" markerWidth="12" markerHeight="10" markerUnits="userSpaceOnUse" orient="auto"><path d="M0,0 L12,5 L0,10 z" fill="{c}"/></marker>')
a('</defs><rect width="1044" height="1241" fill="#f4efec"/><rect x="13" y="13" width="1018" height="1215" rx="26" fill="#fff"/>')
def t(x,y,s,size=12.5,fill='#6a615c',w='400',anchor='start',extra=''):
    a(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{w}" text-anchor="{anchor}" {extra}>{s}</text>')
def line(d,c,w=2.2,mk=None,dash=None):
    m=f' marker-end="url(#m{mk})"' if mk else ''
    ds=f' stroke-dasharray="{dash}"' if dash else ''
    a(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{w}" stroke-linejoin="round"{m}{ds}/>')
def robot(cx,cy,r,col=D,dash=False,sw=2.6):
    ds=' stroke-dasharray="6 4"' if dash else ''
    a(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#fff" stroke="{col}" stroke-width="{sw}"{ds}/>')
    k=r/33
    a(f'<g stroke="{col}" stroke-width="{2.2*max(k,.6)}" fill="none"><rect x="{cx-12*k}" y="{cy-8*k}" width="{24*k}" height="{19*k}" rx="{5*k}"/><line x1="{cx}" y1="{cy-8*k}" x2="{cx}" y2="{cy-14*k}"/></g><circle cx="{cx}" cy="{cy-14*k}" r="{2*max(k,.7)}" fill="{col}"/><circle cx="{cx-5*k}" cy="{cy+1.5*k}" r="{2*max(k,.7)}" fill="{col}"/><circle cx="{cx+5*k}" cy="{cy+1.5*k}" r="{2*max(k,.7)}" fill="{col}"/>')
def human(cx,cy,r=33):
    a(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#fff" stroke="{D}" stroke-width="2.6"/>')
    k=r/33
    a(f'<g stroke="{D}" stroke-width="2.2" fill="none"><circle cx="{cx}" cy="{cy-8*k}" r="{8*k}"/><path d="M{cx-14*k} {cy+15*k} Q{cx-14*k} {cy+3*k} {cx} {cy+3*k} Q{cx+14*k} {cy+3*k} {cx+14*k} {cy+15*k}"/></g>')
t(522,56,'Concept-led agentic team formation',36,'#2b2523','400','middle','font-family="Noto Serif, DejaVu Serif, serif"')
t(522,95,'Four concept owners agree one written brief - concept_to_coordinator.md. A robot delivery team, including each owner\'s personal robot, executes it.',13.5,'#6a615c','400','middle')
a('<rect x="52" y="115" width="940" height="186" rx="22" fill="#faf6f3" stroke="#e6d9d2" stroke-width="2"/>')
t(72,141,'CONCEPT OWNERS',14,'#2b2523','700','start','letter-spacing="1.6"')
t(72,160,'Four humans agree the concept together, in writing; each human\'s personal robot captures their discussion into the brief.',12.5)
t(72,176,'Scope, spend and go-live decisions stay at this level.',12.5)
a('<rect x="52" y="313" width="940" height="607" rx="22" fill="#faf6f3" stroke="#e6d9d2" stroke-width="2"/>')
t(465,331,'DELIVERY TEAM (expandable)',12,'#2b2523','700','middle','letter-spacing="0.4"')
t(465,346,'Includes every personal robot.',11.5,anchor='middle'); t(465,360,'Coordinator manages all roles.',11.5,anchor='middle')
H=[(133,'Human 1'),(346,'Human 2'),(583,'Human 3'),(878,'Human 4')]
for x,n in H:
    human(x,232)
    if n=='Human 4':
        t(x-44,231,n,15,D,'700','end'); t(x-44,248,'concept owner',12.5,anchor='end')
    else:
        t(x+44,231,n,15,D,'700'); t(x+44,248,'concept owner',12.5)
    line(f'M{x} 265 L{x} 368',D,2.2,'d')
    robot(x,389,21,D,False,2.4)
# labels
def lab(x,n,side,ax):
    anc='start' if side=='r' else 'end'
    t(ax,383,'Personal robot',11,'#6a615c','400',anc); t(ax,396,'Instinct',11,'#6a615c','400',anc); t(ax,409,'owner: '+n,11,'#6a615c','400',anc)
lab(133,'Human 1','r',162); lab(346,'Human 2','r',374); lab(583,'Human 3','l',554); lab(878,'Human 4','l',850)
# writes
line('M133 410 L133 450 L408 450 L408 467',D,2.2,'d')
line('M346 410 L346 435 L475 435 L475 467',D,2.2,'d')
line('M583 410 L583 467',D,2.2,'d')
line('M878 410 L878 440 L683 440 L683 467',D,2.2,'d')
t(738,457,'writes',12,D,'400','middle')
# dashed clarifications
dash='7 5'
# robot1
line('M112 389 L98 389 L98 612 L521 612',DG,2.2,'x',dash)
# robot2 with gap at y444-456
line('M325 389 L308 389 L308 444',DG,2.2,None,dash)
line('M308 456 L308 612',DG,2.2,None,dash)
# robot3 with gap crossing y440
line('M604 389 L640 389 L640 418 L858 418 L858 434',DG,2.2,None,dash)
line('M858 446 L858 612',DG,2.2,None,dash)
# robot4
line('M899 389 L912 389 L912 612 L585 612',DG,2.2,'x',dash)
for p in [(308,612),(858,612)]: a(f'<circle cx="{p[0]}" cy="{p[1]}" r="3.6" fill="{DG}"/>')
a('<circle cx="98" cy="612" r="0"/>')
t(203,505,'each personal robot can also clarify',12,'#8a817a','400','middle'); t(203,521,'directly with the Coordinator',12,'#8a817a','400','middle'); t(203,537,'(questions, debugging) - never',12,'#8a817a','400','middle'); t(203,553,'overrides the brief',12,'#8a817a','400','middle')
# brief
a('<rect x="341" y="467" width="428" height="81" rx="16" fill="#fbf8f5" stroke="#b8a9a0" stroke-width="2.4"/>')
t(555,498,'concept_to_coordinator.md',16.5,'#2b2523','700','middle','font-family="DejaVu Sans Mono, monospace"')
t(555,518,'the one agreed brief - the Coordinator reads its orders here',12.5,anchor='middle'); t(555,535,'every concept change is recorded - full change history',12.5,anchor='middle')
line('M555 548 L555 586',D,2.6,'d'); t(545,572,'reads the agreed orders',12.5,'#4a423e','400','end')
# coordinator
robot(555,621,35,D,False,3)
line('M578 590 C 610 585 640 575 662 549',T,2.2,'t')
t(690,566,'real conflict with the',11.5,T); t(690,580,'concept: ask the owners for',11.5,T); t(690,594,'a recorded concept revision',11.5,T)
t(569,668,'Coordinator',15,D,'700'); t(569,684,'Instinct - owner: Human 1',12.5)
# human interaction
line('M105 232 L80 232 L80 811 L100 811',B,2.2,'b'); 
a(f'<text transform="translate(66,520) rotate(-90)" font-size="12.5" fill="#6a615c" text-anchor="middle">human interaction - to QC</text>')
line('M911 232 L957 232 L957 640 L585 640',B,2.2,'b')
a(f'<text transform="translate(971,430) rotate(-90)" font-size="12.5" fill="#6a615c" text-anchor="middle">human interaction - to the Coordinator</text>')
# QC verdict
line('M133 778 C 140 700 330 655 531 648',T,2.2,'t')
t(290,712,'QC verdict - a fail stands, no override',12.5,T)
# management
line('M555 656 L555 750',G,2.4); line('M155 750 L853 750',G,2.4)
t(541,733,'(one Coordinator, one work queue)',12.5,'#6a615c','400','end'); t(569,733,'assigns and manages all delivery roles',12.5)
for x in [155,313,493,673,853]: line(f'M{x} 750 L{x} 778',G,2.4,'g')
R=[(133,'Independent QC','Claude - owner: Human 3',['consequential calls','a fail stands'],'t'),(313,'Architect','Claude - owner: Human 2',['specs and acceptance criteria'],'t'),(493,'Builder','Instinct - owner: Human 4',['sole writer - one batch per turn'],''),(673,'Reviewer','Instinct - owner: Human 1',['written findings on every batch'],''),(853,'Records','Instinct - owner: Human 4',['secondary: mostly idle'],'')]
for x,n,ow,sub,c in R:
    robot(x,811,33,T if c else D,bool(c),2.6)
    t(x,863,n,15,D,'700','middle'); t(x,880,ow,11,'#6a615c','400','middle')
    for i,s in enumerate(sub): t(x,895+15*i,s,11,'#6a615c','400','middle')
a(f'<circle cx="962" cy="811" r="24" fill="none" stroke="#a39a93" stroke-width="2" stroke-dasharray="5 4"/><line x1="962" y1="801" x2="962" y2="821" stroke="#a39a93" stroke-width="2"/><line x1="952" y1="811" x2="972" y2="811" stroke="#a39a93" stroke-width="2"/>')
t(962,863,'Add robots',12.5,'#6a615c','700','middle'); t(962,880,'as needed',11,'#6a615c','400','middle')
# legend
a('<rect x="52" y="935" width="940" height="124" rx="18" fill="#faf6f3" stroke="#e6d9d2" stroke-width="2"/>')
t(72,960,'LEGEND',13,'#2b2523','700','start','letter-spacing="1.6"')
human(91,988,13); t(114,992,'Human - concept owner, equal say',12.5,'#2b2523')
robot(91,1022,13,D,False,2.2); t(114,1026,'Instinct robot - assistant, coordination, building, review, records',12.5,'#2b2523')
robot(612,984,13,T,True,2); t(634,988,'Claude robot - architecture and QC judgment seats',12.5,'#2b2523')
line('M600 1006 L648 1006',D,2.4,'d'); t(660,1010,'capture / orders / writes to the brief',12.5,'#2b2523')
line('M600 1026 L648 1026',DG,2.4,'x',dash); t(660,1030,'direct clarification - cannot override the brief',12.5,'#2b2523')
line('M600 1046 L648 1046',T,2.4,'t'); t(660,1050,'QC verdict / real concept conflict',12.5,'#2b2523')
t(522,1078,'Neutral placeholders - the concept owners assign names, owners and roles. The delivery team is expandable, not unlimited capacity.',12.5,'#6a615c','400','middle')

a('<rect x="52" y="1100" width="940" height="111" rx="16" fill="#faf6f3" stroke="#e6d9d2"/>')
t(72,1126,'ROLE CIRCLES ARE RESPONSIBILITIES, NOT DISTINCT INSTINCTS',13,D,'700')
t(72,1148,'One main delivery job per Instinct. Human 4: Builder + Records only while Records is mostly idle.',13,D)
t(72,1169,'If Records becomes busy, reassign it. Coordinator and Reviewer need separate delivery assignees.',13,D)
t(72,1190,'Keep own-human interaction and relay. Independent QC stays separate from Builder; a fail still stands.',13,D)

a('</svg>')
open('formation-chart.svg','w').write('\n'.join(o))