INK="#2b2625";GR="#6b605d";LG="#a39a96";TE="#3f7a73";BG="#faf7f5"
W,H=1240,1070
o=[]
a=o.append
a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif">')
def mk(id,c): return f'<marker id="{id}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5.5" markerHeight="5.5" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{c}"/></marker>'
a('<defs>'+mk('mi',INK)+mk('mt',TE)+mk('mg',LG)+mk('ml',GR)+'</defs>')
a(f'<rect width="{W}" height="{H}" fill="#f4efec"/><rect x="14" y="14" width="{W-28}" height="{H-28}" rx="26" fill="#fff"/>')
def t(x,y,s,size=13,fill=GR,anchor="start",weight="normal",extra=""):
    a(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}" {extra}>{s}</text>')
t(W/2,72,"Delivery flow: how the robots work below the Coordinator",34,INK,"middle",extra='font-family="Georgia, Noto Serif, serif"')
t(W/2,104,"Working exchanges between roles. These are collaboration lines, not reassignment: the Coordinator manages priorities and conflicts.",15,GR,"middle")
def robot(cx,cy,r,reasoner=False,big=False):
    col=TE if reasoner else INK
    dash=' stroke-dasharray="7 5"' if reasoner else ''
    a(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#fff" stroke="{col}" stroke-width="2.6"{dash}/>')
    s=r/40
    a(f'<rect x="{cx-17*s}" y="{cy-9*s}" width="{34*s}" height="{26*s}" rx="{7*s}" fill="none" stroke="{col}" stroke-width="2.4"/>')
    a(f'<circle cx="{cx-7*s}" cy="{cy+4*s}" r="{2.6*s}" fill="{col}"/><circle cx="{cx+7*s}" cy="{cy+4*s}" r="{2.6*s}" fill="{col}"/>')
    a(f'<line x1="{cx}" y1="{cy-9*s}" x2="{cx}" y2="{cy-17*s}" stroke="{col}" stroke-width="2.4"/><circle cx="{cx}" cy="{cy-18*s}" r="{2.4*s}" fill="{col}"/>')
# coordinator
CX,CY=560,200
# brief pill
a(f'<rect x="50" y="165" width="300" height="70" rx="14" fill="#fcf8f4" stroke="#b9a9a0" stroke-width="2"/>')
t(200,196,"concept_to_coordinator.md",15,INK,"middle","bold",extra='font-family="Courier New, monospace"')
t(200,216,"the agreed brief - orders come from here",12.5,GR,"middle")
a(f'<line x1="350" y1="{CY}" x2="{CX-44-2}" y2="{CY}" stroke="{INK}" stroke-width="2.4" marker-end="url(#mi)"/>')
robot(CX,CY,44,False)
t(CX+62,CY-2,"Coordinator",16,INK,"start","bold")
t(CX+62,CY+17,"Assistant - owner: Human 1",12.5)
t(CX+62,CY+35,"sets priorities, resolves conflicts",12.5)
# bus
xs=[120,390,660,930]; RY=430; R=40
BY=335
a(f'<line x1="{CX}" y1="{CY+44}" x2="{CX}" y2="{BY}" stroke="{LG}" stroke-width="2.2"/>')
a(f'<line x1="{xs[0]}" y1="{BY}" x2="{xs[-1]}" y2="{BY}" stroke="{LG}" stroke-width="2.2"/>')
for x in xs:
    a(f'<line x1="{x}" y1="{BY}" x2="{x}" y2="{RY-R-2}" stroke="{LG}" stroke-width="2.2" marker-end="url(#mg)"/>')
t(CX-14,BY-9,"Coordinator assigns work and manages priorities",12.5,GR,"end")
t(CX+14,BY-9,"Peers collaborate; they never reassign each other",12.5,GR,"start")
nodes=[("Architect","Reasoner - owner: Human 2","specs and acceptance criteria",True),
       ("Builder","Assistant - owner: Human 4","sole writer, one batch per turn",False),
       ("Reviewer","Assistant - owner: Human 1","written findings on every batch",False),
       ("Independent QC","Reasoner - owner: Human 3","consequential calls, a fail stands",True)]
for x,(n,m,d,c) in zip(xs,nodes):
    robot(x,RY,R,c)
    t(x+14,RY+R+26,n,16,INK,"start","bold")
    t(x+14,RY+R+45,m,12.5)
    t(x+14,RY+R+63,d,12.5)
# exchanges
def ex(x1,x2,top,bot,bi=True):
    s,e=x1+R+1,x2-R-1
    ms='marker-start="url(#mi)" ' if bi else ''
    a(f'<line x1="{s}" y1="{RY}" x2="{e}" y2="{RY}" stroke="{INK}" stroke-width="2.4" {ms}marker-end="url(#mi)"/>')
    m=(s+e)/2
    t(m,RY-10,top,12.5,INK,"middle")
    t(m,RY+22,bot,12.5,INK,"middle")
ex(xs[0],xs[1],"specs, constraints &#8594;","&#8592; design questions")
ex(xs[1],xs[2],"implementation &#8594;","&#8592; findings, fixes")
ex(xs[2],xs[3],"critical findings","milestone evidence",False)
# records
RYB=700; RX1,RX2=60,1180
a(f'<rect x="{RX1}" y="{RYB}" width="{RX2-RX1+0}" height="84" rx="14" fill="#fcf8f4" stroke="#b9a9a0" stroke-width="2"/>')
robot(RX1+60,RYB+42,28,False)
t(RX1+110,RYB+34,"Records",16,INK,"start","bold")
t(RX1+110,RYB+53,"Assistant - owner: Human 4",12.5)
t(RX1+110,RYB+71,"secondary: mostly idle",12.5)
t(RX1+330,RYB+34,"Architect, Builder, Reviewer and QC write decisions, results and handoffs here,",13,INK)
t(RX1+330,RYB+53,"so any human can reconstruct what happened. Concept changes are recorded too.",13,INK)
for x in xs:
    a(f'<line x1="{x}" y1="{RY+R+2}" x2="{x}" y2="{RYB-2}" stroke="{GR}" stroke-width="2" stroke-dasharray="6 5" marker-end="url(#ml)"/>')
t(xs[0]+14,RYB-20,"roles below the Coordinator write to Records",12.5,GR,"start")
VX=1196
a(f'<path d="M {xs[3]+R+2} {RY} L {VX} {RY} L {VX} 172 L {CX+33.9+1} 172" fill="none" stroke="{TE}" stroke-width="2.4" stroke-linejoin="round" marker-end="url(#mt)"/>')
t(VX-8,162,"QC verdict to the Coordinator - a fail stands, no override",12.5,TE,"end")
LY=820
a(f'<rect x="60" y="{LY}" width="1120" height="76" rx="14" fill="#faf7f5" stroke="#e6dedb" stroke-width="1.5"/>')
t(80,LY+24,"LEGEND",12,INK,"start","bold",'letter-spacing="2"')
robot(100,LY+54,14,False); t(124,LY+59,"Assistant robot",12.5,INK)
robot(262,LY+54,14,True); t(286,LY+59,"Reasoner robot (high-impact seats)",12.5,INK)
def leg(x,col,mk,dash,txt):
    d=f' stroke-dasharray="{dash}"' if dash else ''
    a(f'<line x1="{x}" y1="{LY+54}" x2="{x+40}" y2="{LY+54}" stroke="{col}" stroke-width="2.4"{d} marker-end="url(#{mk})"/>')
    t(x+50,LY+59,txt,12.5,INK)
leg(520,INK,'mi',None,"working exchange")
leg(690,LG,'mg',None,"assignment, priorities")
leg(880,GR,'ml',"6 5","written record")
leg(1030,TE,'mt',None,"QC verdict")
t(W/2,918,"Neutral placeholders - the concept owners assign actual names, owners and roles when adopting this blueprint.",12.5,GR,"middle")
a('<rect x="60" y="945" width="1120" height="95" rx="14" fill="#faf7f5" stroke="#e6dedb"/>')
t(80,970,"Role circles are responsibilities, not a count of assistants.",14,INK,"start","bold")
t(80,993,"One main delivery job each. Human 4: Builder + Records only while Records is mostly idle; reassign when busy.",14,INK)
t(80,1016,"Coordinator and Reviewer: separate delivery assignees. Own-human relay remains; independent QC stays separate from Builder.",14,INK)
a('</svg>')
open('delivery-flow.svg','w').write("\n".join(o))