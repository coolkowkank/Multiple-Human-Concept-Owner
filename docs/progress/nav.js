(function(){
var s=document.currentScript,base=new URL('.',s.src).href;
var items=[['Home','../'],['Team','team/'],['Legacy Members','legacy-members/'],['Timeline','timeline/'],['Proposals','proposals/'],['Gantt and S-curve','charts/'],['README','https://github.com/coolkowkank/Multiple-Human-Concept-Owner#readme']];
var nav=document.createElement('nav');nav.className='sitenav';nav.setAttribute('aria-label','Site menu');
var inn=document.createElement('div');inn.className='in';
var t=document.createElement('b');t.textContent='Project Under Construction';inn.appendChild(t);
items.forEach(function(it){var a=document.createElement('a');a.textContent=it[0];a.href=/^https?:/.test(it[1])?it[1]:new URL(it[1],base).href;
 var p=a.pathname.replace(/\/index\.html$/,'/');if(!/^https?:/.test(it[1])||0){if(location.pathname.replace(/\/index\.html$/,'/')===p)a.setAttribute('aria-current','page')}
 inn.appendChild(a)});
nav.appendChild(inn);
function go(){document.body.insertBefore(nav,document.body.firstChild);
 var panel=document.createElement('aside');panel.className='updateclock';panel.setAttribute('aria-label','Update schedule');
 var title=document.createElement('b'),last=document.createElement('p'),detail=document.createElement('details'),summary=document.createElement('summary'),note=document.createElement('p');
 title.textContent='Update schedule: loading recorded check time';summary.textContent='Schedule and freshness details';detail.appendChild(summary);detail.appendChild(note);panel.appendChild(title);panel.appendChild(last);panel.appendChild(detail);nav.after(panel);
 fetch(new URL('update-status.json',base).href,{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error();return r.json()}).then(function(d){
  function dt(s){return new Date(s).toLocaleString('en-GB',{timeZone:'Europe/Helsinki',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hour12:false})+' EET'}
  last.textContent='Published content snapshot: '+dt(d.content_as_of)+'. '+(d.last_check_at?'Last completed check: '+dt(d.last_check_at)+'. '+d.check_result+'. ':'')+'Next recorded check: '+dt(d.next_check_at)+'.';
  note.textContent=d.cadence+'. Schedule recorded '+dt(d.schedule_recorded_at)+'. '+d.notice+' If no new evidence exists, the charts stay unchanged. No timer reset is treated as a successful update.';
  function tick(){var left=new Date(d.next_check_at)-Date.now();if(Date.now()>=new Date(d.schedule_expires_at)){title.textContent='Schedule needs renewal; no next check confirmed';return}
   if(left<=0){title.textContent='Scheduled check time passed; result / publication not confirmed';return}
   var secs=Math.floor(left/1000),min=Math.floor(secs/60);title.textContent='Next scheduled update check in '+min+'m '+String(secs%60).padStart(2,'0')+'s';}
  tick();setInterval(tick,1000);
 }).catch(function(){title.textContent='Next update check unavailable; publication not confirmed';last.textContent='The recorded schedule could not be loaded. Do not infer that the page is current.'});
}
if(document.body)go();else document.addEventListener('DOMContentLoaded',go);
})();
