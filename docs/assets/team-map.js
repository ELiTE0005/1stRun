/* FirstRun team map core, shared by the Doc-audit board and the home page.
   model() validates an audit's untrusted "team" block, avSrc() builds an avatar URL only from a
   validated GitHub id or login, and ribbons() draws the people-to-area ribbons as inline SVG.
   No libraries. Each page keeps its own hover, pin and copy logic. */
(function(g){
"use strict";
function isNum(x){return typeof x==="number"&&isFinite(x)}
function str(x,n){return typeof x==="string"?x.slice(0,n||200):""}
function initials(n){var t=String(n||"").split(/[\s._-]+/).filter(Boolean);return ((t.length>1?t[0][0]+t[1][0]:(t[0]||"?").slice(0,2))||"?").toUpperCase()}
function loginOk(p){return p&&typeof p.login==="string"&&/^[A-Za-z0-9-]{1,39}$/.test(p.login)}
/* person color slots by rank: the hue of --p0 to --p11 */
var HUE=[295,256,195,150,78,35,340,220,120,10,270,170];

/* avatars only from validated fields, never a URL from the JSON */
function avSrc(p){if(Number.isInteger(p.gh)&&p.gh>0&&p.gh<1e11)return "https://avatars.githubusercontent.com/u/"+p.gh+"?s=64&v=4";
  if(typeof p.login==="string"&&/^[A-Za-z0-9-]{1,39}$/.test(p.login))return "https://github.com/"+p.login+".png?size=64";return ""}

/* validate and index the team block; cells with a bad index are skipped */
function model(t){
  if(!t||typeof t!=="object"||t.disabled||!Array.isArray(t.people)||!Array.isArray(t.areas)||!t.people.length||!t.areas.length)return null;
  var P=t.people.slice(0,16).map(function(p,i){if(!p||typeof p.id!=="string"||!/^p\d{1,4}$/.test(p.id))return null;
    var nm=str(p.name,80).trim()||(loginOk(p)?p.login:"Contributor "+(i+1));if(/@/.test(nm))nm=loginOk(p)?p.login:"Contributor "+(i+1);
    var ini=str(p.ini,3).trim();if(!/^[\p{L}\p{N}]{1,3}$/u.test(ini))ini=initials(nm);
    return {id:p.id,i:i,slot:i<12?i:-1,name:nm,login:loginOk(p)?p.login:null,gh:Number.isInteger(p.gh)?p.gh:null,ini:ini.toUpperCase(),
      commits:isNum(p.commits)?Math.max(0,Math.round(p.commits)):0,share:isNum(p.share)?p.share:0,last:str(p.last,10),top:str(p.top,8),top_share:isNum(p.top_share)?p.top_share:null}});
  var Ar=t.areas.slice(0,12).map(function(a,i){if(!a||typeof a.id!=="string"||!/^a\d{1,4}$/.test(a.id))return null;
    return {id:a.id,i:i,label:str(a.label,60)||"area "+(i+1),path:str(a.path,160),repo:a.repo==="docs"?"docs":"code",share:isNum(a.share)?a.share:0,last:str(a.last,10),
      owners:Array.isArray(a.owners)?a.owners.slice(0,3):[],bus:Number.isInteger(a.bus)&&a.bus>0?a.bus:1,single:a.single===true,quiet:a.quiet===true}});
  var M={},rowSum={},colSum={},hasO=false;
  function add(pi,ai,w){var k=pi+"|"+ai;M[k]=(M[k]||0)+w;rowSum[pi]=(rowSum[pi]||0)+w;colSum[ai]=(colSum[ai]||0)+w;if(pi<0)hasO=true}
  (Array.isArray(t.cells)?t.cells:[]).forEach(function(c){if(!Array.isArray(c)||c.length<3)return;var pi=c[0],ai=c[1],w=c[2];
    if(!Number.isInteger(pi)||!Number.isInteger(ai)||!isNum(w)||w<=0)return;if(!(pi===-1||(pi>=0&&pi<P.length&&P[pi]&&pi<12)))return;if(ai<0||ai>=Ar.length||!Ar[ai])return;add(pi,ai,w)});
  var byId={};P.forEach(function(p){if(p)byId[p.id]=p});
  if(!Object.keys(M).length)Ar.forEach(function(a){if(!a)return;a.owners.forEach(function(o){if(!o||!isNum(o.s)||o.s<=0)return;
    if(o.p==="others")add(-1,a.i,o.s*Math.max(a.share,.01));else if(byId[o.p]&&byId[o.p].i<12)add(byId[o.p].i,a.i,o.s*Math.max(a.share,.01))})});
  var O=t.others&&typeof t.others==="object"&&isNum(t.others.people)&&t.others.people>0?{people:Math.round(t.others.people),commits:isNum(t.others.commits)?t.others.commits:0,share:isNum(t.others.share)?t.others.share:0}:null;
  var rowsP=P.filter(function(p){return p&&p.i<12&&rowSum[p.i]});
  if(hasO&&O)rowsP.push({id:"others",i:-1,slot:-1,name:"Everyone else",others:O});
  if(!rowsP.length)return null;
  var rIdx={};rowsP.forEach(function(p,r){rIdx[p.i]=r});
  var rowsA=Ar.filter(function(a){return a&&colSum[a.i]}).map(function(a){var s=0,n=0;rowsP.forEach(function(p){var w=M[p.i+"|"+a.i];if(w){s+=w*rIdx[p.i];n+=w}});a.bc=n?s/n:0;return a});
  rowsA.sort(function(x,y){return (x.bc-y.bc)||(y.share-x.share)});
  var aById={};Ar.forEach(function(a){if(a)aById[a.id]=a});
  rowsP.forEach(function(p){if(p.i<0)return;var top=aById[p.top];
    if(!top){var bw=0;rowsA.forEach(function(a){var w=M[p.i+"|"+a.i]||0;if(w>bw){bw=w;top=a}})}
    p.topA=top||null;if(p.top_share==null&&top)p.top_share=(M[p.i+"|"+top.i]||0)/rowSum[p.i]});
  P.forEach(function(p){if(p&&!p.topA)p.topA=aById[p.top]||null});
  return {P:P,byId:byId,A:rowsA,aById:aById,M:M,rowSum:rowSum,colSum:colSum,rowsP:rowsP,O:O,
    solo:rowsP.length===1&&rowsP[0].i>=0&&!O,total:Number.isInteger(t.total_people)?t.total_people:null}
}

/* draw the ribbons: left end = share of the person's work, right end = share of the area.
   o.W is the width, o.pitch the row pitch and o.bar the node height, both in px.
   Returns the svg element; the caller places it and wires hover. */
function ribbons(T,o){
  var W=o.W,R=o.pitch||52,B=o.bar||36,G=(R-B)/2,cid=o.clip||"tmc",nP=T.rowsP.length,nA=T.A.length,n=Math.max(nP,nA),H=n*R,oP=(n-nP)*R/2,oA=(n-nA)*R/2;
  var NS="http://www.w3.org/2000/svg";function s(t,a){var e=document.createElementNS(NS,t);for(var k in a)e.setAttribute(k,a[k]);return e}
  var svg=s("svg",{"class":"tm-svg","aria-hidden":"true",width:W,height:H,viewBox:"0 0 "+W+" "+H,focusable:"false"});
  var defs=s("defs",{}),gr=s("g",{}),gn=s("g",{});svg.appendChild(defs);svg.appendChild(gr);svg.appendChild(gn);
  var lc=T.rowsP.map(function(){return 0}),rc=T.A.map(function(){return 0}),x0=7,x1=W-7,m=W/2,k=0,segs=T.A.map(function(){return []});
  function fill(p){return p.slot>=0?"var(--p"+p.slot+")":"var(--po)"}
  T.rowsP.forEach(function(p,r){T.A.forEach(function(a,c){var w=T.M[p.i+"|"+a.i];if(!w)return;
    var tl=B*w/T.rowSum[p.i],tr=B*w/T.colSum[a.i],L0=oP+r*R+G+lc[r],L1=L0+tl,R0=oA+c*R+G+rc[c],R1=R0+tr;lc[r]+=tl;rc[c]+=tr;
    var f=function(v){return Math.round(v*100)/100};
    var d="M"+x0+","+f(L0)+"C"+f(m)+","+f(L0)+" "+f(m)+","+f(R0)+" "+x1+","+f(R0)+"L"+x1+","+f(R1)+"C"+f(m)+","+f(R1)+" "+f(m)+","+f(L1)+" "+x0+","+f(L1)+"Z";
    var pa=s("path",{d:d,"class":"rb","data-p":p.id,"data-a":a.id});pa.style.fill=fill(p);pa.style.setProperty("--i",k++);gr.appendChild(pa);
    var sg=s("rect",{x:W-5,y:f(R0),width:5,height:Math.max(.6,f(tr)),"class":"nd","data-p":p.id,"data-a":a.id});sg.style.fill=fill(p);segs[c].push(sg)})});
  T.rowsP.forEach(function(p,r){var b=s("rect",{x:0,y:oP+r*R+G,width:5,height:B,rx:2.5,"class":"nd","data-p":p.id});b.style.fill=fill(p);gn.appendChild(b)});
  T.A.forEach(function(a,c){var id=cid+c,cp=s("clipPath",{id:id});cp.appendChild(s("rect",{x:W-5,y:oA+c*R+G,width:5,height:B,rx:2.5}));defs.appendChild(cp);
    var g=s("g",{"clip-path":"url(#"+id+")"});if(a.quiet)g.setAttribute("opacity",".45");segs[c].forEach(function(x){g.appendChild(x)});gn.appendChild(g);
    if(a.quiet)gn.appendChild(s("rect",{x:W-6.5,y:oA+c*R+G-1.5,width:8,height:B+3,rx:4,fill:"none",stroke:"oklch(70% .01 255)","stroke-dasharray":"2 2"}))});
  svg._oP=oP;svg._oA=oA;
  return svg;
}

g.FRTeam={HUE:HUE,model:model,avSrc:avSrc,initials:initials,ribbons:ribbons};
})(window);
