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
function go(){document.body.insertBefore(nav,document.body.firstChild)}
if(document.body)go();else document.addEventListener('DOMContentLoaded',go);
})();
