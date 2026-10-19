/* The hero stage. Three broken steps wait on the left, a white beam strikes a dark
   glass prism, and the light leaves as three rays, one per angle on the right:
   blue for the clean run, gold for the cost, violet for who should fix it.
   Canvas 2D, no library, DPR aware. It pauses off screen, in a hidden tab, and on
   request, and it draws one still frame under prefers-reduced-motion.
   The scene is decorative. The angles are real DOM text in the hero markup.
   The stage attributes steer the rays: data-focus="0|1|2" lights one angle,
   data-em="test|audit" lights the angles a route leads to.
   API: window.FRPrism.mode("test"|"audit") */
(function(){
"use strict";
var st=document.getElementById("hero"),cv=document.getElementById("pz");
function flat(){if(st)st.classList.add("flat")}
if(!st||!cv||!cv.getContext)return flat();
var c=cv.getContext("2d");if(!c)return flat();
var inL=document.getElementById("stIn"),outL=document.getElementById("stOut"),sky=document.getElementById("stSky"),pz=document.getElementById("stPause");
var chips=[].slice.call(inL.children),labs=[].slice.call(outL.children);
var MQ=matchMedia("(max-width:899px)"),RMQ=matchMedia("(prefers-reduced-motion:reduce)");

/* every line below comes from a real run or audit in this repo (docs/runs, docs/audits, data/prs.json) */
var POOL={
 test:["No such option: --years","entire: command not found","Migration guide link: 404","Python version never stated","No module named 'typer'","curl: command not found","Docs say 0.9.0, not 0.9.58","KeyError: 'NEATLOGS_API_KEY'"],
 audit:["Flags page: 453 days old","29 code changes since edit","72 features with no docs","Infer-configs: 709 days old","15 stale of 1,405 pages","AccuKnox: 87 stale pages","Hard-deletes: 631 days old","AccuKnox page: 1,100 days old"]
};
/* three rays, one strand each, top to bottom: the clean run (blue), the cost (gold), who fixes it
   (violet). The hues match the icons on the right and the Doc-test, Receipt and Doc-audit sections below. */
var GC=[[90,178,255],[255,186,60],[176,108,255]];
var WARM={test:[255,118,100],audit:[255,184,80]};
var gw=[1,1,1];

var W=0,H=0,dpr=1,mob=false,G=null,lanes=[],parts=[],pulses=[],raf=0,vis=true,paused=false,still=RMQ.matches;
var t0=0,last=0,now=0,spawnAt=0,ks=0,rs=0,mode="test",mk=0,surge=0;
var ptr={x:0,y:0,tx:0,ty:0};

function cl(v,a,b){return v<a?a:v>b?b:v}
function ease(k){k=cl(k,0,1);return 1-Math.pow(1-k,4)}
function lerp(a,b,k){return a+(b-a)*k}
function mix(p,q,k){return[Math.round(lerp(p[0],q[0],k)),Math.round(lerp(p[1],q[1],k)),Math.round(lerp(p[2],q[2],k))]}
function rgba(a,al){return"rgba("+a[0]+","+a[1]+","+a[2]+","+al+")"}
function quad(a,b,d,u){var v=1-u;return{x:v*v*a.x+2*v*u*b.x+u*u*d.x,y:v*v*a.y+2*v*u*b.y+u*u*d.y}}
function cub(a,b,d,e,u){var v=1-u,A=v*v*v,B=3*v*v*u,C=3*v*u*u,D=u*u*u;return{x:A*a.x+B*b.x+C*d.x+D*e.x,y:A*a.y+B*b.y+C*d.y+D*e.y}}
function rel(r,R){return{l:r.left-R.left,t:r.top-R.top,r:r.right-R.left,b:r.bottom-R.top}}

/* ---------- layout: measure the stage and place the prism, lanes and labels ---------- */
function layout(){
 mob=MQ.matches;
 var R=cv.getBoundingClientRect();W=R.width;H=R.height;if(W<2||H<2)return;
 var px=W*H,cap=mob?2:2.2e6;
 dpr=Math.min(window.devicePixelRatio||1,2);if(px*dpr*dpr>cap*2)dpr=Math.max(1,Math.sqrt(cap*2/px));
 cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);
 G={};
 if(mob){
  var hm=Math.min(H*.66,W*.52);G.h=hm;G.w=hm*1.1547;G.cx=W*.46;G.ay=(H-hm)*.5;
  G.fx=W-2;G.top=12;G.bot=H-12;G.half=9;G.so=6;
  G.gyT=[H*.26,H*.52,H*.78];G.gy=G.gyT.slice();
  G.y0=null;lanes=[];
  chips.concat(labs).forEach(function(li){li.classList.remove("off");li._a=null;["transform","opacity","left","top"].forEach(function(p){li.style.removeProperty(p)})});
  ["left","top","width"].forEach(function(p){outL.style.removeProperty(p)});
  geo(0,0);
 }else{
  var S=st.getBoundingClientRect(),h1=rel(st.querySelector("h1").getBoundingClientRect(),S),fm=rel(document.getElementById("f").getBoundingClientRect(),S),hn=rel(document.getElementById("hint").getBoundingClientRect(),S),ch=rel(document.getElementById("chips").getBoundingClientRect(),S);
  /* vertical rhythm: a clear gap under the helper line, then the prism, then a margin above
     the horizon curve. A short stage shrinks the prism instead of letting it climb. */
  var hz=document.querySelector(".hz"),hzT=hz?rel(hz.getBoundingClientRect(),S).t:H-62,tb=Math.max(hn.b,ch.b);
  var gap=cl(H*.075,62,80),top=tb+gap,bot=hzT-cl(H*.05,36,56),sh=Math.max(120,bot-top);
  /* a narrow desktop gets a smaller prism, so the column of angles keeps its room */
  var h=cl(sh,120,Math.min(360,W*(W<1200?.21:.26)));G.h=h;G.w=h*1.1547;G.cx=W/2;G.ay=top+(sh-h)*.45;G.top=top;G.bot=bot;
  geo(0,0);
  /* the angles: one column on the right, as wide as its titles need and never over the prism */
  var cw=cl(W*.27,290,400);
  G.fx=Math.min(Math.max(G.cx+G.w*.5+64,W*.7),W-cw-24);
  var lx=G.fx+12;
  outL.style.left=Math.round(lx)+"px";outL.style.width=Math.round(Math.min(cw,W-lx-22))+"px";
  /* start under the input. Beside the examples and the helper line when the column clears them,
     else under them */
  var y0=lx>Math.max(ch.r,hn.r)+24?fm.b+30:tb+30;
  /* room for the column at rest plus the tallest reveal, so an open angle never hits the horizon */
  outL.classList.remove("tight");
  function rest(){var v=outL.offsetHeight;labs.forEach(function(li){var m=li.querySelector(".gm");if(m)v-=m.offsetHeight});return v}
  var E=0;labs.forEach(function(li){var m=li.querySelector(".gmi");if(m)E=Math.max(E,m.scrollHeight)});
  var Hr=rest();
  if(y0+Hr+E>bot){outL.classList.add("tight");Hr=rest()}
  /* centered on the prism's exit, so the three rays fan out evenly */
  outL.style.top=Math.round(cl(G.Pout.y-Hr*.5,y0,Math.max(y0,bot-Hr-E)))+"px";
  G.half=11;G.so=7;G.gy=null;measure();
  G.cl=Math.min(h1.l,fm.l);G.ct=h1.t;G.cb=tb;
 }
 /* anchor the backdrop light to the scene: the halo on the prism, the bleed where the rays land */
 if(sky){var so=rel(cv.getBoundingClientRect(),st.getBoundingClientRect());
  [["--pcx",so.l+G.cx],["--pcy",so.t+G.ay+G.h*.62],["--pby",so.t+G.ay+G.h],["--pfx",so.l+(mob?W*.86:G.fx)]].forEach(function(v){sky.style.setProperty(v[0],Math.round(v[1])+"px")})}
 /* chip lanes: start in the left column, curve down into the beam */
 lanes=[];
 if(!mob){
  /* with a wide left column the lanes start beside the headline. Their threads fall in a
     gutter between the chips and the text, then merge into the beam farther along. */
  /* the calmer composition won: chips live in the band below the text, beside the beam.
     Set wideL to true to let them climb beside the headline on very wide screens. */
  /* lane centers stay one chip height plus a margin apart. A short band shows fewer chips. */
  var chH=chips[0].offsetHeight||31,minSp=chH+12;
  var wideL=false,yA=wideL?Math.max(G.ct+26,120):G.cb+cl((G.top-G.cb)*.7,36,52)+chH/2,yB=G.bot-chH/2,xs=[0,0,0],wi=0;
  var bc0=beamY(Math.max(16,W*.034)+150),gp0=bc0-28>yA&&bc0+28<yB?56:0;
  var n=Math.max(1,Math.min(3,chips.length,Math.floor((yB-yA-gp0)/minSp)+1));
  chips.forEach(function(li,j){li.classList.toggle("off",j>=n)});
  G.gut=wideL?G.cl-82:1e4;
  for(var j=0;j<n;j++){
   /* spread the lanes evenly, skipping a band around the beam so no chip sits on it */
   var sx=Math.max(16,W*.034)+[0,26,52][j],bc=beamY(sx+130);
   var sy=Math.max(yA,bc-30-chH/2-(n-1-j)*minSp);
   var wide=wideL&&sy<G.cb+6;
   var bx=lerp(Math.min(G.Pin.x-80,W*.41),Math.min(G.Pin.x-120,W*.29),n>1?j/(n-1):.5),by=beamY(bx);
   lanes.push({S:{x:sx,y:sy},C:{x:sx+(bx-sx)*.62,y:sy},B:{x:bx,y:by},ph:j/n+.07*Math.sin(j*2.3),w:0,q:-1,wide:wide,drop:wide?G.cl-34-14*(wi++):0});
  }
  chips.forEach(function(li,j){if(j<n)setChip(j,POOL[mode][j]);fit(j)});
 }
 if(still||paused||!raf)frame(now||performance.now());
}
function beamY(x){return lerp(G.y0,G.Pin.y,x/G.Pin.x)}
/* where each ray lands: the middle of its angle's icon. Read again when an angle opens or closes,
   and the ray eases to the new spot. */
var icons=labs.map(function(li){return li.querySelector(".gi")});
function measure(redraw){
 if(mob||!G||!W)return;
 var S=st.getBoundingClientRect();
 G.gyT=icons.map(function(e){var r=e.getBoundingClientRect();return r.top-S.top+r.height/2});
 var r0=icons[0].getBoundingClientRect();G.ix=r0.left-S.left+r0.width/2;
 if(!G.gy||still||paused)G.gy=G.gyT.slice();
 if(redraw&&(still||paused||!raf))frame(now||performance.now());
}
/* prism geometry under the current tilt */
function geo(th,dy){
 var h=G.h,w=G.w,cx=G.cx,ay=G.ay+dy,gy=ay+h*2/3,cs=Math.cos(th),sn=Math.sin(th);
 function rot(x,y){var X=x-cx,Y=y-gy;return{x:cx+X*cs-Y*sn,y:gy+X*sn+Y*cs}}
 G.A=rot(cx,ay);G.L=rot(cx-w/2,ay+h);G.R=rot(cx+w/2,ay+h);
 G.Pin={x:lerp(G.A.x,G.L.x,.56),y:lerp(G.A.y,G.L.y,.56)};
 G.Pout={x:lerp(G.A.x,G.R.x,.6),y:lerp(G.A.y,G.R.y,.6)};
 if(G.y0===undefined||G.y0===null||!G.fixY)G.y0=G.Pin.y+G.Pin.x*.085;
 G.fixY=true;
}
/* the chip under lane j: measure its width once per text */
function fit(j){var li=chips[j],L=lanes[j];if(!L)return;L.w=li.offsetWidth;
 var lim=Math.min(G.gut,L.B.x-60),dx=lim-L.w-L.S.x,D=Math.max(1,L.B.x-L.S.x);
 L.um=cl(dx/(1.24*D),.02,.26)}

/* ---------- chips: three steady failures, one pool per mode ---------- */
function setChip(j,s){var sp=chips[j].firstChild;if(sp.textContent!==s){sp.textContent=s;fit(j)}}
var swapT=-1e9;
function chipsFrame(t){
 if(mob)return;
 var fade=still?1:cl((t-swapT)/420,0,1),intro=still?1:ease((t-t0-500)/900);
 lanes.forEach(function(L,j){
  var li=chips[j],al=intro*(fade<1?(fade<.5?1-fade*2:fade*2-1):1);
  L.p=L.S;L.al=al;
  li.style.transform="translate3d("+(L.S.x+ptr.x*5).toFixed(1)+"px,"+(L.S.y-li.offsetHeight/2+ptr.y*4).toFixed(1)+"px,0)";
  li.style.opacity=al.toFixed(3);
 });
}
function swapChips(){
 /* fade out, change the pool at the midpoint, fade back in */
 swapT=now;var done=false;
 if(mob){inL.classList.add("swap")}
 setTimeout(function(){if(done)return;done=true;
  chips.forEach(function(li,j){setChip(j,POOL[mode][j%POOL[mode].length])});
  if(mob)inL.classList.remove("swap");
  if(still||paused)frame(now)},210);
}

/* ---------- drawing ---------- */
function drawFan(t,fanK){
 var P=G.Pout,fx=lerp(P.x,G.fx,fanK),so=G.so;
 c.save();c.globalCompositeOperation="lighter";c.lineCap="round";
 for(var q=0;q<3;q++){
  var wk=gw[q],yy=lerp(P.y,G.gy[q],fanK),col=GC[q],hw=2.2;
  var g=c.createLinearGradient(P.x,0,fx,0);
  g.addColorStop(0,rgba(col,0));g.addColorStop(.1,rgba(col,Math.min(1,.8*wk)));g.addColorStop(.85,rgba(col,Math.min(1,.9*wk)));g.addColorStop(1,rgba(col,Math.min(1,.5*wk)));
  /* a slim wedge, then a crisp center line */
  c.fillStyle=g;c.globalAlpha=.55;c.beginPath();c.moveTo(P.x,P.y-1);c.lineTo(fx,yy-hw*2);c.lineTo(fx,yy+hw*2);c.lineTo(P.x,P.y+1);c.closePath();c.fill();
  c.globalAlpha=1;c.strokeStyle=g;c.lineWidth=1.8;c.beginPath();c.moveTo(P.x,P.y);c.lineTo(fx,yy);c.stroke();
 }
 c.restore();
}
function drawBeam(t,k){
 var P=G.Pin,y0=G.y0,ex=lerp(0,P.x,k),ey=lerp(y0,P.y,k),fl=1;
 fl*=1+surge*.35;
 var tint=mix([238,242,255],[244,232,255],mk);
 c.save();c.globalCompositeOperation="lighter";c.lineCap="round";
 var g=c.createLinearGradient(0,0,P.x,0);g.addColorStop(0,rgba(tint,0));g.addColorStop(.5,rgba(tint,.55*fl));g.addColorStop(1,rgba(tint,Math.min(1,fl)));
 c.strokeStyle=g;
 [[2.6,.6],[1.2,1]].forEach(function(l){c.globalAlpha=l[1];c.lineWidth=l[0];c.beginPath();c.moveTo(0,y0);c.lineTo(ex,ey);c.stroke()});
 c.restore();
}
function tri(p,q,r){c.beginPath();c.moveTo(p.x,p.y);c.lineTo(q.x,q.y);c.lineTo(r.x,r.y);c.closePath()}
function edge(p,q,stops,w){var g=c.createLinearGradient(p.x,p.y,q.x,q.y);stops.forEach(function(s){g.addColorStop(s[0],s[1])});c.strokeStyle=g;c.lineWidth=w;c.beginPath();c.moveTo(p.x,p.y);c.lineTo(q.x,q.y);c.stroke()}
function drawPrism(t,k){
 if(k<=0)return;
 var A=G.A,L=G.L,R=G.R,h=G.h,w=G.w,dx=h*(.055+ptr.x*.03),dy=-h*(.04+ptr.y*.012);
 var A2={x:A.x+dx,y:A.y+dy},L2={x:L.x+dx,y:L.y+dy},R2={x:R.x+dx,y:R.y+dy};
 var inner=mix([70,140,255],[160,100,255],mk);
 c.save();c.globalAlpha=k;c.lineJoin="round";
 /* back face and the thin sides that give the glass its depth */
 tri(A2,L2,R2);c.fillStyle="rgba(8,9,18,.92)";c.fill();
 c.beginPath();c.moveTo(A.x,A.y);c.lineTo(A2.x,A2.y);c.lineTo(R2.x,R2.y);c.lineTo(R.x,R.y);c.closePath();
 var sg=c.createLinearGradient(A.x,A.y,R2.x,R2.y);sg.addColorStop(0,"rgba(40,46,70,.95)");sg.addColorStop(1,"rgba(6,7,14,.98)");c.fillStyle=sg;c.fill();
 /* front face: dark glass, lighter toward the lit left edge */
 tri(A,L,R);var fg=c.createLinearGradient(L.x,A.y,R.x,R.y);fg.addColorStop(0,"rgba(30,34,52,.94)");fg.addColorStop(.55,"rgba(13,15,26,.96)");fg.addColorStop(1,"rgba(5,6,12,.98)");c.fillStyle=fg;c.fill();
 /* a faint inner glow in the tool color */
 c.save();tri(A,L,R);c.clip();
 var ig=c.createRadialGradient(G.Pin.x+w*.12,G.Pin.y,0,G.Pin.x+w*.12,G.Pin.y,h*.75);ig.addColorStop(0,rgba(inner,.16+surge*.12));ig.addColorStop(1,rgba(inner,0));c.fillStyle=ig;c.fillRect(L.x-20,A.y-20,w+40,h+40);
 /* the light path inside the glass: white in, a faint spectrum toward the exit */
 c.globalCompositeOperation="lighter";
 var P1=G.Pin,P2=G.Pout,pg=c.createLinearGradient(P1.x,P1.y,P2.x,P2.y);pg.addColorStop(0,"rgba(255,255,255,.42)");pg.addColorStop(.55,"rgba(200,220,255,.12)");pg.addColorStop(1,"rgba(255,210,240,.2)");
 c.fillStyle=pg;c.beginPath();c.moveTo(P1.x,P1.y-1);c.lineTo(P2.x,P2.y-h*.022);c.lineTo(P2.x,P2.y+h*.022);c.lineTo(P1.x,P1.y+1);c.closePath();c.fill();
 /* internal reflections: the back edges seen through the glass */
 c.globalCompositeOperation="source-over";
 c.lineWidth=1;c.strokeStyle="rgba(190,205,255,.16)";tri(A2,L2,R2);c.stroke();
 c.strokeStyle="rgba(190,205,255,.1)";c.beginPath();c.moveTo(L.x,L.y);c.lineTo(L2.x,L2.y);c.stroke();
 /* a sheen down the lit face */
 var sh=c.createLinearGradient(A.x,A.y,L.x,L.y);sh.addColorStop(0,"rgba(255,255,255,.2)");sh.addColorStop(1,"rgba(255,255,255,0)");
 c.fillStyle=sh;c.beginPath();c.moveTo(A.x,A.y);c.lineTo(L.x,L.y);c.lineTo(L.x+w*.08,L.y-h*.015);c.lineTo(A.x+w*.012,A.y+h*.1);c.closePath();c.fill();
 c.restore();
 /* edges: crisp light on the lit edge, a rainbow rim along the base */
 var Wh="rgba(255,255,255,";
 edge(A,L,[[0,Wh+".95)"],[.56,Wh+".7)"],[1,Wh+".14)"]],1.4);
 edge(A,R,[[0,Wh+".5)"],[1,Wh+".2)"]],1.1);
 edge(A,A2,[[0,Wh+".45)"],[1,Wh+".05)"]],1);
 edge(A2,R2,[[0,Wh+".12)"],[1,Wh+".03)"]],1);
 var rim=[[0,"rgba(90,215,255,.15)"],[.22,"rgba(146,108,255,.7)"],[.45,"rgba(255,79,216,.85)"],[.7,"rgba(255,158,36,.95)"],[1,"rgba(255,222,60,.9)"]];
 edge(L,R,rim,2);
 c.restore();
}
function drawBlooms(t,beamK,fanK){
 var P=G.Pin,Q=G.Pout,h=G.h,tint=mix([235,240,255],[242,228,255],mk),b=1+surge*.6;
 c.save();c.globalCompositeOperation="lighter";
 if(beamK>.9){var bk=(beamK-.9)/.1;
  var r=h*.32,g=c.createRadialGradient(P.x,P.y,0,P.x,P.y,r);g.addColorStop(0,rgba(tint,.4*bk*b));g.addColorStop(.18,rgba(tint,.12*bk*b));g.addColorStop(1,rgba(tint,0));c.fillStyle=g;c.fillRect(P.x-r,P.y-r,2*r,2*r);

 }
  c.restore();
}
/* how bright each ray wants to be. An open angle wins, else the hovered route, else all three. */
function wT(q){var f=st.getAttribute("data-focus"),e=st.getAttribute("data-em");
 if(f!==null&&f!=="")return +f===q?1.3:.22;
 if(e==="test")return q<2?1.15:.25;
 if(e==="audit")return q===2?1.3:.25;
 return 1}
/* ---------- loop ---------- */
var intro=0;
function frame(t){
 if(!G||!W)return;
 now=t;
 var dt=Math.min(50,t-(last||t));last=t;
 var it=still?1e5:t-t0;
 var beamK=ease((it-80)/1000),prismK=ease((it-260)/800),fanK=ease((it-820)/1300);
 /* ease toward the pointer and toward the active tool */
 var f=still?1:1-Math.pow(1-.075,dt/16.7);
 if(!still){ptr.x+=(ptr.tx-ptr.x)*f;ptr.y+=(ptr.ty-ptr.y)*f}
 var tm=mode==="audit"?1:0;mk+=(tm-mk)*(still?1:1-Math.pow(1-.06,dt/16.7));
 surge=Math.max(0,surge-dt/900);
 var th=still?0:ptr.x*.045;
 geo(th,still?0:ptr.y*-4);
 /* ease each ray toward its brightness and its landing spot */
 var snap=still||paused;
 for(var q=0;q<3;q++){var wt=wT(q);gw[q]=snap?wt:gw[q]+(wt-gw[q])*f;if(G.gy&&G.gyT)G.gy[q]=snap?G.gyT[q]:G.gy[q]+(G.gyT[q]-G.gy[q])*Math.min(1,f*2.2)}
 c.setTransform(dpr,0,0,dpr,0,0);c.clearRect(0,0,W,H);
 chipsFrame(t);
 if(fanK>0)drawFan(t,fanK);
 drawBeam(t,beamK);
 drawPrism(t,prismK);
 drawBlooms(t,beamK,fanK);
 /* the angles arrive as their ray reaches them, then hold still so they stay easy to point at */
 if(!mob){var lk=still?1:fanK;labs.forEach(function(li,i){var a=cl((lk-.4-i*.1)/.25,0,1).toFixed(3);if(li._a!==a){li._a=a;li.style.opacity=a}})}
 if(sky&&!still)sky.style.transform="translate3d("+(ptr.x*-8).toFixed(1)+"px,"+(ptr.y*-6).toFixed(1)+"px,0)";
}
function loop(t){
 if(!vis||paused||still||document.hidden){raf=0;last=0;return}
 frame(t);raf=requestAnimationFrame(loop);
}
function start(){if(raf||!vis||paused||still||document.hidden)return;raf=requestAnimationFrame(loop)}
function stop(){if(raf)cancelAnimationFrame(raf);raf=0;last=0}

/* ---------- wiring ---------- */
function onPtr(e){if(mob||e.pointerType==="touch")return;var r=st.getBoundingClientRect();ptr.tx=cl((e.clientX-r.left)/r.width*2-1,-1,1);ptr.ty=cl((e.clientY-r.top)/r.height*2-1,-1,1)}
st.addEventListener("pointermove",onPtr,{passive:true});
st.addEventListener("pointerleave",function(){ptr.tx=0;ptr.ty=0});
var lay=0;function relayout(){if(lay)return;lay=requestAnimationFrame(function(){lay=0;layout()})}
if("ResizeObserver" in window){new ResizeObserver(relayout).observe(st);new ResizeObserver(function(){measure(true)}).observe(outL)}else addEventListener("resize",relayout);
/* a still or paused scene redraws once when an angle or a route lights up */
if("MutationObserver" in window)new MutationObserver(function(){if(still||paused||!raf)frame(performance.now())}).observe(st,{attributes:true,attributeFilter:["data-focus","data-em"]});
if("IntersectionObserver" in window)new IntersectionObserver(function(en){vis=en[0].isIntersecting;st.classList.toggle("idle",!vis);if(vis)start();else stop()},{threshold:0}).observe(st);
document.addEventListener("visibilitychange",function(){if(document.hidden)stop();else start()});
function setStill(v){still=v;st.classList.toggle("still",v);if(pz)pz.hidden=v;if(v){stop();frame(performance.now())}else{t0=performance.now()-4000;start()}}
if(RMQ.addEventListener)RMQ.addEventListener("change",function(e){setStill(e.matches)});
if(pz){pz.hidden=still;pz.addEventListener("click",function(){paused=!paused;pz.setAttribute("aria-pressed",paused?"true":"false");pz.setAttribute("aria-label",paused?"Play the animation":"Pause the animation");st.classList.toggle("paused",paused);if(paused)stop();else start()})}
window.FRPrism={mode:function(m){m=m==="audit"?"audit":"test";if(m===mode)return;mode=m;surge=1;swapChips();if(still||paused)setTimeout(function(){frame(performance.now())},230)}};
st.classList.add("live");st.classList.toggle("still",still);
t0=performance.now();
layout();
if(document.fonts&&document.fonts.ready)document.fonts.ready.then(relayout);
if(still)frame(performance.now());else start();
})();
