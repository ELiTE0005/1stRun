/* One floating island nav for every page. Usage:
   <div id="sitenav"></div><script src="<base>assets/site-nav.js" data-cur="test|audit|plan|home" defer></script>
   Over any element marked data-nav="dark" the bar turns dark, so it reads on a dark hero. */
(function(){
"use strict";
var me=document.currentScript||document.querySelector('script[src*="site-nav.js"]');
var BASE=me.src.replace(/assets\/site-nav\.js.*$/,""),CUR=me.getAttribute("data-cur")||"home",HOME=CUR==="home";
var host=document.getElementById("sitenav");
if(!host){host=document.createElement("div");host.id="sitenav";document.body.insertBefore(host,document.body.firstChild)}
var I={
 test:'<rect x="2.5" y="3.5" width="19" height="17" rx="3.5"/><path d="M6.8 9.2l3 2.6-3 2.6M12.3 15.6h4.9"/>',
 audit:'<path d="M12.5 3H7a2.5 2.5 0 0 0-2.5 2.5v13A2.5 2.5 0 0 0 7 21h4.2"/><path d="M12.5 3l5.5 5.5h-5.5z"/><circle cx="16" cy="15.8" r="3.1"/><path d="M18.3 18.1l2.7 2.7"/>',
 check:'<path d="M4 12.5l5 5L20 6.5"/>',ok:'<circle cx="12" cy="12" r="8.5"/><path d="M8 12.3l2.8 2.8L16.2 9"/>',
 play:'<path d="M7 4.5v15l12-7.5z"/>',q:'<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12h7"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',repo:'<path d="M6 3.5h11.5v14H7.5A1.5 1.5 0 0 0 6 19v-15.5zM6 19a1.5 1.5 0 0 0 1.5 1.5h10"/>',
 rcpt:'<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',watch:'<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10.5 9.5v5l4-2.5z"/>',
 cmp:'<path d="M4 6h16M4 12h16M4 18h16"/><path d="M9 4v16"/>',plan:'<path d="M4 19V9M10 19V5M16 19v-7M21 19H3"/>',
 agent:'<path d="M3.5 8.5l4 3.5-4 3.5M10.5 17.5h6"/><path class="sn-spark" d="M18.5 2.8l1 2.4 2.4 1-2.4 1-1 2.4-1-2.4-2.4-1 2.4-1z"/>',
proof:'<path d="M12 3.5l7 2.8v5.2c0 4.3-2.9 7.7-7 9-4.1-1.3-7-4.7-7-9V6.3z"/><path d="M8.8 12.2l2.3 2.3 4.2-4.4"/>',
 car:'<path d="M3 4.5l3 3 3-3"/>',burger:'<path d="M4 8h16M4 16h16"/>',x:'<path d="M6 6l12 12M18 6L6 18"/>'
};
function svg(n,vb,cls){return '<svg'+(cls?' class="'+cls+'"':"")+' viewBox="'+(vb||"0 0 24 24")+'" aria-hidden="true">'+I[n]+"</svg>"}
function tile(n){return '<span class="sn-tile t-'+n+'">'+svg(n)+"</span>"}
function it(href,icon,t,s,tag,id){return '<a class="sn-it" href="'+href+'"'+(id?' id="'+id+'"':"")+">"+svg(icon)+"<b>"+t+"</b>"+(tag?"<i"+(tag.ok?' class="ok"':"")+">"+(tag.t||"")+"</i>":"")+"<small>"+s+"</small></a>"}
var T=BASE+"doc-test/",A=BASE+"doc-audit/";
var GH='<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 .8a7.2 7.2 0 0 0-2.3 14c.4.1.5-.2.5-.4v-1.3c-2 .4-2.4-.9-2.4-.9-.3-.8-.8-1.1-.8-1.1-.7-.5 0-.5 0-.5.7.1 1.1.8 1.1.8.7 1.1 1.7.8 2.1.6.1-.5.3-.8.5-1-1.6-.2-3.3-.8-3.3-3.6 0-.8.3-1.4.7-1.9-.1-.2-.3-.9.1-1.9 0 0 .6-.2 2 .7a6.8 6.8 0 0 1 3.6 0c1.4-.9 2-.7 2-.7.4 1 .1 1.7.1 1.9.5.5.7 1.1.7 1.9 0 2.8-1.7 3.4-3.3 3.6.3.2.5.7.5 1.4v2.1c0 .2.1.5.5.4A7.2 7.2 0 0 0 8 .8z"/></svg>';
var LOGO='<svg viewBox="0 0 64 64" aria-hidden="true"><rect x="2" y="2" width="60" height="60" rx="15" fill="#0A66D6"/><path d="M21 22l13 10-13 10" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/><rect x="38" y="39" width="12" height="5.5" rx="2.75" fill="#fff"/></svg>';
function app(k,label){return '<button type="button" class="sn-app a-'+k+'" id="sn-b-'+k+'" aria-expanded="false" aria-controls="sn-m-'+k+'"'+(CUR===k?' aria-current="page"':"")+">"+tile(k)+"<b>"+label+"</b>"+svg("car","0 0 12 12","sn-car")+"</button>"}
/* the section links name what is on the home page, in page order. [label, target, icon, subtitle] */
var proof=[["Receipts","#receipt","rcpt","What each run cost and the proof it passed"],["Watch the demo","#watch","watch","The 2:54 film, plus four more"],["Compare","#compare","cmp","FirstRun next to Claude Code, Actions and Copilot"]];
var links=[["Cost caps","plan/","plan","What each plan may spend"],["For judges","judges/","ok","Each claim and its proof"]];
function href(l){return l[1].charAt(0)==="#"?(HOME?l[1]:BASE+l[1]):BASE+l[1]}
function curLink(l){return l[1]===CUR+"/"}
/* Agent Ready lives in the floating launcher and the mobile menu. It is a link to agent.md that opens a dialog instead, so it still works if the dialog code fails to load. */
var AG=BASE+"agent.md";
function agent(cls,inner){return '<a class="'+cls+' sn-ag" href="'+AG+'" role="button" aria-haspopup="dialog" aria-expanded="false">'+inner+"</a>"}
var AGMENU=agent("sn-it",svg("agent")+"<b>Agent Ready</b><small>One prompt for Claude Code, Cursor or Codex</small>");
host.innerHTML='<nav class="sn-nav" aria-label="Site"><div class="sn-bar">'+
 '<a class="sn-wm" href="'+BASE+'" aria-label="FirstRun home"'+(HOME?' aria-current="page"':"")+">"+LOGO+"<span>FirstRun</span></a>"+
 '<span class="sn-apps">'+app("test","Doc-test")+app("audit","Doc-audit")+app("proof","Proof")+"</span>"+
 '<span class="sn-sep" aria-hidden="true"></span><span class="sn-links">'+
 links.map(function(l){return '<a class="sn-lk" data-k="'+l[1]+'" href="'+href(l)+'"'+(curLink(l)?' aria-current="page"':"")+'>'+l[0]+"</a>"}).join("")+
 '</span><span class="sn-sp"></span><a class="sn-gh" href="https://github.com/HighnessAtharva/firstrun" aria-label="FirstRun on GitHub">'+GH+"</a>"+
 '<a class="sn-try" id="sn-try" href="'+BASE+'#hero">Try it</a>'+
 '<button type="button" class="sn-burger" id="sn-b-more" aria-label="Menu" aria-expanded="false" aria-controls="sn-m-more">'+svg("burger","0 0 24 24","sn-ib")+svg("x","0 0 24 24","sn-ix")+"</button></div>"+
 '<div class="sn-mm mm-test" id="sn-m-test" role="region" aria-label="Doc-test">'+
  '<div class="sn-hero">'+tile("test")+"<h3>Doc-test</h3><p>Runs a docs quickstart in a clean container, fixes the step that breaks, and proves the fix in a second clean run.</p>"+
  '<div class="sn-nums"><span><b id="sn-n-fix">&nbsp;</b>fixes proven</span><span><b id="sn-n-ok">&nbsp;</b>pages that work</span></div>'+
  '<a class="sn-go" href="'+T+'">Open Doc-test</a></div>'+
  '<div class="sn-list"><div class="sn-h">Results</div>'+
  it(T+"?f=fixed","check","Fix proven","Docs bugs with a fix that passed a clean rerun",{t:"",ok:1},"sn-c-fix")+
  it(T+"?f=works","ok","Docs that work","Every step passed as written",{t:""},"sn-c-ok")+
  it(T+"?f=open","q","Inconclusive","Runs that stopped before a fix was proven",{t:""},"sn-c-q")+
  '<div class="sn-h">Watch one</div>'+
  it(T+"#ex=dbt","play","Replay the dbt run","A docs bug, the fix, the clean rerun, the PR")+"</div></div>"+
 '<div class="sn-mm mm-audit" id="sn-m-audit" role="region" aria-label="Doc-audit">'+
  '<div class="sn-hero">'+tile("audit")+"<h3>Doc-audit</h3><p>Reads a whole repo's git history, code and docs. Lists stale pages and shipped features with no docs, and maps who works on which part of the code.</p>"+
  '<div class="sn-nums"><span><b id="sn-n-aud">&nbsp;</b>repos audited</span><span><b id="sn-n-stale">&nbsp;</b>stale pages found</span></div>'+
  '<a class="sn-go" href="'+A+'">Open Doc-audit</a></div>'+
  '<div class="sn-list"><div class="sn-h">Real audits</div><div id="sn-aud"></div>'+
  it(A+"#start","plus","Audit your repo","Paste a GitHub repo")+"</div></div>"+
 '<div class="sn-mm mm-proof" id="sn-m-proof" role="region" aria-label="Proof"><div class="sn-list">'+
  proof.map(function(l){return it(href(l),l[2],l[0],l[3],null,"sn-p-"+l[1].slice(1))}).join("")+"</div></div>"+
 '<div class="sn-mm mm-more" id="sn-m-more" role="region" aria-label="Menu"><div class="sn-list">'+
  '<div class="sn-h">The two tools</div>'+
  '<a class="sn-big b-test" href="'+T+'"'+(CUR==="test"?' aria-current="page"':"")+">"+tile("test")+"<b>Doc-test</b><small>Run a quickstart, fix it, prove it</small></a>"+
  '<a class="sn-big b-audit" href="'+A+'"'+(CUR==="audit"?' aria-current="page"':"")+">"+tile("audit")+"<b>Doc-audit</b><small>Find the docs your code outgrew</small></a>"+
  '<div class="sn-h">Proof</div>'+proof.map(function(l){return it(href(l),l[2],l[0],l[3])}).join("")+
  '<div class="sn-h">On this site</div>'+links.map(function(l){return it(href(l),l[2],l[0],l[3])}).join("")+AGMENU+
  it("https://github.com/HighnessAtharva/firstrun","repo","GitHub","The public repo")+"</div></div></nav>";

var $=function(i){return document.getElementById(i)},nav=host.firstChild,open=null,timer;
function set(k,on){
 var b=$("sn-b-"+k),m=$("sn-m-"+k);if(!b||!m)return;
 if(on&&open&&open!==k)set(open,false);
 b.setAttribute("aria-expanded",on?"true":"false");m.classList.toggle("on",on);open=on?k:(open===k?null:open);
 nav.classList.toggle("sn-open",!!open);
 if(on)load();
 if(on&&k==="proof")place(b,m);
}
function place(b,m){var n=nav.getBoundingClientRect(),r=b.getBoundingClientRect(),w=m.offsetWidth||340;
 var c=r.left+r.width/2-n.left;c=Math.max(w/2,Math.min(n.width-w/2,c));m.style.left=c+"px"}
["test","audit","proof","more"].forEach(function(k){
 var b=$("sn-b-"+k),m=$("sn-m-"+k);
 b.addEventListener("click",function(e){e.stopPropagation();set(k,b.getAttribute("aria-expanded")!=="true")});
 if(k!=="more"&&matchMedia("(hover:hover) and (pointer:fine)").matches){
  [b,m].forEach(function(x){
   x.addEventListener("mouseenter",function(){clearTimeout(timer);timer=setTimeout(function(){set(k,true)},open?0:120)});
   x.addEventListener("mouseleave",function(){clearTimeout(timer);timer=setTimeout(function(){if(open===k)set(k,false)},220)});
  });
 }
});
document.addEventListener("click",function(e){if(open&&!host.contains(e.target))set(open,false)});
document.addEventListener("keydown",function(e){if(e.key==="Escape"&&open){var k=open;set(k,false);$("sn-b-"+k).focus()}});
window.addEventListener("hashchange",function(){if(open)set(open,false)});
host.addEventListener("click",function(e){if(open&&e.target.closest(".sn-mm a"))set(open,false)});

/* Try it: put the cursor in this page's own input when it has one, else go to the home page box */
$("sn-try").addEventListener("click",function(e){
 var ids=["u","goU","repo"];
 for(var i=0;i<ids.length;i++){var x=$(ids[i]);if(x&&x.offsetParent){e.preventDefault();
  var rm=matchMedia("(prefers-reduced-motion:reduce)").matches;
  x.scrollIntoView({behavior:rm?"auto":"smooth",block:ids[i]==="u"?"center":"center"});
  setTimeout(function(){x.focus({preventScroll:true})},rm?0:420);if(open)set(open,false);return}}
});

/* Agent Ready: load the dialog code on first use, so no page loads it up front.
   If it fails to load, or the browser has no <dialog>, the link opens agent.md as a page. */
var agP=null;
function agLoad(){
 if(agP)return agP;
 agP=new Promise(function(ok,no){
  var n=2,l=document.createElement("link"),s=document.createElement("script");
  function one(){if(--n===0)window.FRAgent?ok(window.FRAgent):no()}
  l.rel="stylesheet";l.href=BASE+"assets/agent-modal.css";l.onload=one;l.onerror=no;
  s.src=BASE+"assets/agent-modal.js";s.async=true;s.onload=one;s.onerror=no;
  document.head.appendChild(l);document.head.appendChild(s);
 });
 agP.catch(function(){agP=null});
 return agP;
}
/* Floating Agent Ready launcher, bottom right, on every page that loads this script. It stays in view and hides only while the dialog is open. */
(function(){
 /* agent logos from @lobehub/icons 1.95.1 (MIT): Claude, Cursor, Codex. They are decoration, so the button label names the feature. */
 var lg=function(n,p){return '<span class="fr-agl-lg lg-'+n+'"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'+p+"</svg></span>"};
 var w=document.createElement("div");w.id="fr-agw";w.className="fr-agw";
 w.innerHTML='<div class="fr-agl-tip" id="fr-agl-tip" role="tooltip">agent.md tells Claude Code, Cursor or Codex how to run FirstRun for you. Click for the steps.</div>'+
  '<a class="fr-agl sn-ag" href="'+AG+'" role="button" aria-haspopup="dialog" aria-expanded="false" aria-describedby="fr-agl-tip" aria-label="Agent Ready: copy steps for your coding agent">'+
  '<span class="fr-agl-st">'+
  lg('claude','<path d="M4.709 15.955l4.72-2.647.08-.23-.08-.128H9.2l-.79-.048-2.698-.073-2.339-.097-2.266-.122-.571-.121L0 11.784l.055-.352.48-.321.686.06 1.52.103 2.278.158 1.652.097 2.449.255h.389l.055-.157-.134-.098-.103-.097-2.358-1.596-2.552-1.688-1.336-.972-.724-.491-.364-.462-.158-1.008.656-.722.881.06.225.061.893.686 1.908 1.476 2.491 1.833.365.304.145-.103.019-.073-.164-.274-1.355-2.446-1.446-2.49-.644-1.032-.17-.619a2.97 2.97 0 01-.104-.729L6.283.134 6.696 0l.996.134.42.364.62 1.414 1.002 2.229 1.555 3.03.456.898.243.832.091.255h.158V9.01l.128-1.706.237-2.095.23-2.695.08-.76.376-.91.747-.492.584.28.48.685-.067.444-.286 1.851-.559 2.903-.364 1.942h.212l.243-.242.985-1.306 1.652-2.064.73-.82.85-.904.547-.431h1.033l.76 1.129-.34 1.166-1.064 1.347-.881 1.142-1.264 1.7-.79 1.36.073.11.188-.02 2.856-.606 1.543-.28 1.841-.315.833.388.091.395-.328.807-1.969.486-2.309.462-3.439.813-.042.03.049.061 1.549.146.662.036h1.622l3.02.225.79.522.474.638-.079.485-1.215.62-1.64-.389-3.829-.91-1.312-.329h-.182v.11l1.093 1.068 2.006 1.81 2.509 2.33.127.578-.322.455-.34-.049-2.205-1.657-.851-.747-1.926-1.62h-.128v.17l.444.649 2.345 3.521.122 1.08-.17.353-.608.213-.668-.122-1.374-1.925-1.415-2.167-1.143-1.943-.14.08-.674 7.254-.316.37-.729.28-.607-.461-.322-.747.322-1.476.389-1.924.315-1.53.286-1.9.17-.632-.012-.042-.14.018-1.434 1.967-2.18 2.945-1.726 1.845-.414.164-.717-.37.067-.662.401-.589 2.388-3.036 1.44-1.882.93-1.086-.006-.158h-.055L4.132 18.56l-1.13.146-.487-.456.061-.746.231-.243 1.908-1.312-.006.006z" fill="#D97757" fill-rule="nonzero"></path>')+
  lg('cursor','<path fill="#14120B" d="M22.106 5.68L12.5.135a.998.998 0 00-.998 0L1.893 5.68a.84.84 0 00-.419.726v11.186c0 .3.16.577.42.727l9.607 5.547a.999.999 0 00.998 0l9.608-5.547a.84.84 0 00.42-.727V6.407a.84.84 0 00-.42-.726zm-.603 1.176L12.228 22.92c-.063.108-.228.064-.228-.061V12.34a.59.59 0 00-.295-.51l-9.11-5.26c-.107-.062-.063-.228.062-.228h18.55c.264 0 .428.286.296.514z"></path>')+
  lg('codex','<path d="M19.503 0H4.496A4.496 4.496 0 000 4.496v15.007A4.496 4.496 0 004.496 24h15.007A4.496 4.496 0 0024 19.503V4.496A4.496 4.496 0 0019.503 0z" fill="#14120B"></path><path d="M9.064 3.344a4.578 4.578 0 012.285-.312c1 .115 1.891.54 2.673 1.275.01.01.024.017.037.021a.09.09 0 00.043 0 4.55 4.55 0 013.046.275l.047.022.116.057a4.581 4.581 0 012.188 2.399c.209.51.313 1.041.315 1.595a4.24 4.24 0 01-.134 1.223.123.123 0 00.03.115c.594.607.988 1.33 1.183 2.17.289 1.425-.007 2.71-.887 3.854l-.136.166a4.548 4.548 0 01-2.201 1.388.123.123 0 00-.081.076c-.191.551-.383 1.023-.74 1.494-.9 1.187-2.222 1.846-3.711 1.838-1.187-.006-2.239-.44-3.157-1.302a.107.107 0 00-.105-.024c-.388.125-.78.143-1.204.138a4.441 4.441 0 01-1.945-.466 4.544 4.544 0 01-1.61-1.335c-.152-.202-.303-.392-.414-.617a5.81 5.81 0 01-.37-.961 4.582 4.582 0 01-.014-2.298.124.124 0 00.006-.056.085.085 0 00-.027-.048 4.467 4.467 0 01-1.034-1.651 3.896 3.896 0 01-.251-1.192 5.189 5.189 0 01.141-1.6c.337-1.112.982-1.985 1.933-2.618.212-.141.413-.251.601-.33.215-.089.43-.164.646-.227a.098.098 0 00.065-.066 4.51 4.51 0 01.829-1.615 4.535 4.535 0 011.837-1.388zm3.482 10.565a.637.637 0 000 1.272h3.636a.637.637 0 100-1.272h-3.636zM8.462 9.23a.637.637 0 00-1.106.631l1.272 2.224-1.266 2.136a.636.636 0 101.095.649l1.454-2.455a.636.636 0 00.005-.64L8.462 9.23z" fill="url(#fr-cdx)"></path><defs><linearGradient gradientUnits="userSpaceOnUse" id="fr-cdx" x1="12" x2="12" y1="3" y2="21"><stop stop-color="#B1A7FF"></stop><stop offset=".5" stop-color="#7A9DFF"></stop><stop offset="1" stop-color="#3941FF"></stop></linearGradient></defs>')+
  '</span><span class="fr-agl-t">Agent<span class="fr-agl-x"> Ready</span></span></a>';
 document.body.appendChild(w);
 document.documentElement.classList.add("has-agl");
 requestAnimationFrame(function(){w.classList.add("is-on")});
})();

var agBtns=document.querySelectorAll(".sn-ag");
function agState(on){Array.prototype.forEach.call(agBtns,function(b){b.setAttribute("aria-expanded",on?"true":"false")});
 var w=$("fr-agw");if(w)w.classList.toggle("is-open",!!on)}
Array.prototype.forEach.call(agBtns,function(b){
 b.addEventListener("pointerenter",function(){if(window.HTMLDialogElement)agLoad()});
 b.addEventListener("focus",function(){if(window.HTMLDialogElement)agLoad()});
 b.addEventListener("keydown",function(e){if(e.key===" "){e.preventDefault();b.click()}});
 b.addEventListener("click",function(e){
  if(!window.HTMLDialogElement||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||e.button)return;
  e.preventDefault();
  var back=b.closest(".sn-mm")?$("sn-b-more"):b,gone=false;
  if(open)set(open,false);
  agState(true);
  var t=setTimeout(function(){gone=true;location.href=AG},6000);
  agLoad().then(function(m){clearTimeout(t);if(gone)return;
   m.open({base:BASE,back:back,onclose:function(){agState(false)}});
  },function(){clearTimeout(t);if(!gone)location.href=AG});
 });
});

/* dark bar over a dark section: watch a thin strip at the top of the viewport */
if("IntersectionObserver" in window){
 var darks=document.querySelectorAll('[data-nav="dark"]'),on={};
 if(darks.length){
  var io=new IntersectionObserver(function(en){en.forEach(function(e){on[e.target.id||"x"]=e.isIntersecting});
   var any=false;for(var k in on)if(on[k])any=true;nav.classList.toggle("dark",any)},{rootMargin:"0px 0px -92% 0px"});
  Array.prototype.forEach.call(darks,function(d){io.observe(d)});
 }
 /* home page: mark the part of the page you are reading */
 if(HOME){
  var spy={steps:"sn-b-test",team:"sn-b-audit",audit:"sn-b-audit",receipt:"sn-b-proof",watch:"sn-b-proof",compare:"sn-b-proof"};
  var els=[];Object.keys(spy).forEach(function(id){var s=$(id);if(s)els.push(s)});
  var here=null;
  var so=new IntersectionObserver(function(en){en.forEach(function(e){
    var t=spy[e.target.id],el=$(t);if(!el)return;
    if(e.isIntersecting){if(here&&here!==el)here.classList.remove("is-here");el.classList.add("is-here");here=el}
    else if(here===el){el.classList.remove("is-here");here=null}
   })},{rootMargin:"-45% 0px -50% 0px"});
  els.forEach(function(s){so.observe(s)});
 }
}

/* live numbers, loaded once on first open or when idle */
var loaded=false;
function verdict(r){return r.status==="verified"&&r.fixes>0?"fixed":(r.status==="passed"||r.status==="verified")?"works":"open"}
function load(){
 if(loaded)return;loaded=true;
 fetch(BASE+"runs/index.json").then(function(r){return r.json()}).then(function(j){
  var by={};(j.runs||[]).filter(function(r){return!r.fixture}).forEach(function(r){var k=(r.url||r.target).replace(/[#?].*$/,"").replace(/\/$/,"");(by[k]=by[k]||[]).push(verdict(r))});
  var c={fixed:0,works:0,open:0};
  Object.keys(by).forEach(function(k){var v=by[k];c[v.indexOf("fixed")>=0?"fixed":v.indexOf("works")>=0?"works":"open"]++});
  $("sn-n-fix").textContent=c.fixed;$("sn-n-ok").textContent=c.works;
  $("sn-c-fix").querySelector("i").textContent=c.fixed;$("sn-c-ok").querySelector("i").textContent=c.works;$("sn-c-q").querySelector("i").textContent=c.open;
 }).catch(function(){});
 fetch(BASE+"audits/index.json").then(function(r){return r.json()}).then(function(j){
  var a=(j.audits||[]),st=0;a.forEach(function(x){st+=+x.stale||0});
  $("sn-n-aud").textContent=a.length;$("sn-n-stale").textContent=st;
  $("sn-aud").innerHTML=a.slice(0,4).map(function(x){var r=String(x.repo).replace(/[<>&"]/g,"");return it(A+"?id="+encodeURIComponent(x.id),"repo",r,(+x.pages||0)+" pages, "+(+x.uncovered||0)+" features with no docs",{t:(+x.stale||0)+" stale"})}).join("");
 }).catch(function(){});
}
if("requestIdleCallback" in window)requestIdleCallback(load,{timeout:2500});else setTimeout(load,1500);

/* Landing on /#receipt: the browser jumps before layout settles, so it can land too high. Jump again on load and 400 ms later.
   Only act when the hash names an element id. Hashes like #ex=dbt belong to the page scripts. */
function jump(){
 try{var h=decodeURIComponent(location.hash.slice(1));if(!h)return;var el=document.getElementById(h);
  if(el)el.scrollIntoView({block:"start",behavior:"instant"})}catch(e){}
}
function jumpAll(){jump();setTimeout(jump,400)}
if(document.readyState==="complete")jumpAll();else addEventListener("load",jumpAll);
})();
