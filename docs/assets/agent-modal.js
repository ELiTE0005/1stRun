/* Agent Ready dialog. site-nav.js loads this file on first use and calls FRAgent.open({base, back, onclose}).
   The commands come from docs/agent.md. Change them there first, then here. */
(function(){
"use strict";
var SITE="https://1strun.rajbir.tech/",GH="https://github.com/ELiTE0005/1stRun";
var L1="Read "+SITE+"agent.md and follow it.";
var RCPT="FR-20261010-091740-help-accuknox-com";
var PRE={sh:"python3 --version\ngit --version",ps:"py -3.11 --version\ngit --version"};
var DOCKER={sh:"\ndocker info --format '{{.ServerVersion}}'",ps:"\nwsl -d Ubuntu-22.04 docker info --format '{{.ServerVersion}}'"};
var INSTALL={sh:"python3 -m venv .venv\n. .venv/bin/activate\npip install git+"+GH,ps:"py -3.11 -m venv .venv\n.venv\\Scripts\\Activate.ps1\npip install git+"+GH};
/* one task per segment: the prompt's second line and the commands that change with it */
var TASKS={
 test:{label:"Test a docs page",
  line:"Test the quickstart at https://docs.getdbt.com/guides/duckdb and tell me which step broke.",
  pre:"Python 3.11 or newer, git, and Docker for the clean container.",
  doctor:"1stRun doctor --for test --json",
  key:"Doc-test needs <code>CLAUDE_CODE_OAUTH_TOKEN</code> in <code>.env</code>. Your agent asks you to add it.",
  run:"1stRun run https://docs.getdbt.com/guides/duckdb --json > result.json",
  runNote:"Doc-test. Give the call 30 minutes, because one step may run for 5.",
  read:"Read <code>ok</code>, then <code>runs[0].status</code> and the report at <code>runs[0].files[\"report.md\"]</code>.",
  ask:"1stRun pr <run_id> --json",
  askNote:"For a verified fix it prints the diff, the PR body and the <code>gh</code> commands. It opens nothing."},
 audit:{label:"Audit a repo",
  line:"Audit github.com/fastapi/typer and tell me the top 3 docs tasks and who should own them.",
  pre:"Python 3.11 or newer and git. Doc-audit needs no Docker.",
  doctor:"1stRun doctor --for audit --json",
  key:"Doc-audit needs no key. Without <code>TYPESAFE_API_KEY</code> the agent adds <code>--no-jev</code>.",
  run:"1stRun audit fastapi/typer --no-publish --json > audit-result.json",
  runNote:"Doc-audit. fastapi/typer took 97 seconds. <code>--no-publish</code> keeps the audit on your disk.",
  read:"Read <code>ok</code>, then <code>top_tasks[]</code>: each task has <code>rank</code>, <code>title</code>, <code>effort</code> and a suggested <code>owner</code>.",
  ask:"1stRun audit-issue <audit_id> --json",
  askNote:"It drafts a GitHub issue for the docs team and prints the <code>gh</code> command. It opens nothing."},
 receipt:{label:"Check a receipt",
  line:"Check the cost and proof on receipt "+RCPT+" and tell me if it is verified.",
  pre:"Python 3.11 or newer and git. A receipt check needs no Docker.",
  doctor:"1stRun doctor --for audit --json",
  key:"A receipt check needs no key.",
  run:{sh:"mkdir -p site-receipt && curl -sSfo site-receipt/receipt.json "+SITE+"receipts/"+RCPT+".json\n1stRun receipt --check site-receipt/receipt.json --hash-only --json",
   ps:"New-Item -ItemType Directory -Force site-receipt | Out-Null\ncurl.exe -sSfo site-receipt/receipt.json "+SITE+"receipts/"+RCPT+".json\n1stRun receipt --check site-receipt/receipt.json --hash-only --json"},
  runNote:"It saves the receipt from the site and checks its hash. The file holds <code>price</code> and <code>proof</code>.",
  read:"Read <code>ok</code>, <code>valid</code> and <code>hash_ok</code>. Then read <code>price</code> and <code>proof.status</code> in the receipt.",
  ask:"",askNote:"A receipt check writes nothing and opens nothing."}
};
var ORDER=["test","audit","receipt"];
var IC={
 copy:'<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8.5" y="8.5" width="11" height="11" rx="2.5"/><path d="M15.5 8.5V6.5a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2"/></svg>',
 ok:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
 x:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
 mark:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 8.5l4 3.5-4 3.5M10.5 17.5h6"/><path class="sn-spark" d="M18.5 2.8l1 2.4 2.4 1-2.4 1-1 2.4-1-2.4-2.4-1 2.4-1z"/></svg>',
 pr:'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6.5" cy="6" r="2.2"/><circle cx="6.5" cy="18" r="2.2"/><circle cx="17.5" cy="18" r="2.2"/><path d="M6.5 8.2v7.6M17.5 15.8V10a3 3 0 0 0-3-3h-3.5M13 4.5L10.5 7l2.5 2.5"/></svg>',
 shield:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5l7 2.8v5.2c0 4.3-2.9 7.7-7 9-4.1-1.3-7-4.7-7-9V6.3z"/><path d="M8.8 12.2l2.3 2.3 4.2-4.4"/></svg>',
 key:'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="8" cy="14.5" r="4"/><path d="M11 11.5l8.5-8.5M16.5 6l2.5 2.5M14 8.5l2 2"/></svg>'
};
/* real output, run 2026-10-11 with an empty .env, trimmed. No path from the machine that ran it. */
var J_DOC='{\n  "ok": true,\n  "command": "doctor",\n  "exit_code": 0,\n  "error": null,\n  "can_run": {"doc_test": false, "doc_audit": true, "hosted_audit": true, "read_public_data": true},\n  "checks": [\n    {"name": "git", "status": "pass", "required_for": ["test", "audit"], ...},\n    {"name": "CLAUDE_CODE_OAUTH_TOKEN", "status": "fail", "required_for": ["test"],\n     "detail": "not set. Doc-test plans and repairs steps with Claude.",\n     "fix": "Ask the human to run `claude setup-token` and put CLAUDE_CODE_OAUTH_TOKEN in .env."},\n    ...\n  ]\n}';
var J_RC='{\n  "ok": true,\n  "command": "receipt",\n  "exit_code": 0,\n  "error": null,\n  "mode": "check",\n  "path": "site-receipt/receipt.json",\n  "valid": true,\n  "hash_ok": true,\n  "hash_only": true,\n  "problems": []\n}';

var BASE="",dlg=null,back=null,onclose=null,task="test",os=/Win/i.test(navigator.platform||navigator.userAgent)?"ps":"sh",raw=null,rawP=null,down=null;
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function hl(s){/* color the JSON keys, strings and literals of an escaped excerpt */
 return esc(s).replace(/(&quot;[^&\n]*?&quot;)(\s*:)?|\b(true|false|null|\d+)\b/g,function(m,str,colon,lit){
  if(str)return colon?'<span class="k">'+str+"</span>"+colon:'<span class="s">'+str+"</span>";
  return '<span class="v">'+lit+"</span>";
 });
}
function q(s){return dlg.querySelector(s)}
function cmd(id,text,label){return '<div class="ar-cmd"><pre id="'+id+'" tabindex="0" aria-label="'+esc(label)+'">'+esc(text)+'</pre><button type="button" class="ar-ic" data-copy="'+id+'" aria-label="Copy: '+esc(label)+'">'+IC.copy+"</button></div>"}
function step(n,title,note,cmdHtml){return '<li class="ar-step"><span class="ar-n" aria-hidden="true">'+n+"</span><b>"+title+"</b><p>"+note+"</p>"+(cmdHtml?"<div>"+cmdHtml+"</div>":"")+"</li>"}

function steps(){
 var t=TASKS[task],run=typeof t.run==="string"?t.run:t.run[os];
 var h=step(1,"Check the machine",t.pre,cmd("ar-c1",PRE[os]+(task==="test"?DOCKER[os]:""),"step 1, check the machine"))+
  step(2,"Install 1stRun in a virtual environment","About 3 minutes, because it pulls the Claude Agent SDK and Langfuse.",cmd("ar-c2",INSTALL[os],"step 2, install"))+
  step(3,"Run the preflight","It checks Python, git, Docker, each key and the network. It prints whether a key is set, never its value. "+t.key,cmd("ar-c3",t.doctor,"step 3, preflight"))+
  step(4,"Run the task with <code>--json</code>",t.runNote+" Stdout holds one JSON object.",cmd("ar-c4",run,"step 4, run the task"))+
  step(5,"Read the JSON",t.read,"")+
  step(6,"Ask you before any PR or issue","1stRun opens nothing, and your agent waits for your yes. "+t.askNote,t.ask?cmd("ar-c6",t.ask,"step 6, draft"):"");
 q(".ar-steps").innerHTML=h;
}
function paint(){
 var t=TASKS[task];
 dlg.setAttribute("data-task",task);
 q(".ar-ptext .l2").textContent=t.line;
 steps();
 Array.prototype.forEach.call(dlg.querySelectorAll(".ar-os button"),function(b){b.setAttribute("aria-pressed",b.getAttribute("data-os")===os?"true":"false")});
}

function build(){
 dlg=document.createElement("dialog");
 dlg.className="ar-dlg";dlg.id="ar-dlg";dlg.setAttribute("aria-labelledby","ar-t");dlg.setAttribute("aria-describedby","ar-d");
 var seg=ORDER.map(function(k,i){return '<input type="radio" name="ar-task" id="ar-k-'+k+'" value="'+k+'"'+(k===task?" checked":"")+'><label for="ar-k-'+k+'"><span class="ar-dot d-'+k+'" aria-hidden="true"></span>'+TASKS[k].label+"</label>"}).join("");
 dlg.innerHTML=
 '<div class="ar-head"><div class="ar-top"><span class="ar-mark" aria-hidden="true">'+IC.mark+'</span><div class="ar-title"><h2 id="ar-t">Agent Ready</h2>'+
 '<p class="ar-sub" id="ar-d">Give your coding agent one URL. It installs 1stRun, runs it and reports back.</p></div>'+
 '<button type="button" class="ar-x" aria-label="Close">'+IC.x+"</button></div>"+
 '<div class="ar-tabs" role="tablist" aria-label="Agent Ready">'+
 '<button type="button" role="tab" class="ar-tab" id="ar-tq" aria-selected="true" aria-controls="ar-pq">Quickstart</button>'+
 '<button type="button" role="tab" class="ar-tab" id="ar-tr" aria-selected="false" aria-controls="ar-pr" tabindex="-1">Full <span class="ar-mono">agent.md</span></button></div></div>'+
 '<div class="ar-body">'+
 '<div class="ar-panel" id="ar-pq" role="tabpanel" aria-labelledby="ar-tq">'+
  '<fieldset class="ar-seg"><legend class="ar-sr">Task for your agent</legend>'+seg+"</fieldset>"+
  '<div class="ar-prompt"><p class="ar-ptext" id="ar-prompt"><span class="l1">'+esc(L1)+'</span><span class="l2"></span></p>'+
  '<div class="ar-pfoot"><span class="ar-where">Paste it into Claude Code, Codex or the Cursor agent chat. Change the example to your own.</span>'+
  '<button type="button" class="ar-copy" id="ar-cp" autofocus>'+IC.copy+"<span>Copy prompt</span></button></div></div>"+
  '<div class="ar-h"><h3>Your agent runs these 6 steps</h3><div class="ar-os" role="group" aria-label="Shell">'+
  '<button type="button" data-os="sh">macOS, Linux</button><button type="button" data-os="ps">Windows</button></div></div>'+
  '<ol class="ar-steps"></ol>'+
  '<details class="ar-json"><summary>What the JSON looks like <small>2 real excerpts</small></summary><div class="ar-jin">'+
  '<div><p><code>1stRun doctor --for audit --json</code> with an empty <code>.env</code>, trimmed. Exit 0, because Doc-audit can run.</p><pre tabindex="0">'+hl(J_DOC)+"</pre></div>"+
  '<div><p><code>1stRun receipt --check site-receipt/receipt.json --hash-only --json</code> on receipt '+RCPT+".</p><pre tabindex=\"0\">"+hl(J_RC)+"</pre></div>"+
  "</div></details>"+
  '<ul class="ar-safe" aria-label="Safety">'+
  "<li>"+IC.pr+"Never opens a PR on its own</li><li>"+IC.shield+"Respects each repo's AI policy</li><li>"+IC.key+"Keys never printed</li></ul>"+
  '<p class="ar-links"><a href="'+BASE+'agent.md" target="_blank" rel="noopener">Open agent.md</a><a href="'+BASE+'llms.txt" target="_blank" rel="noopener">llms.txt</a>'+
  '<a href="'+GH+'/blob/main/AGENTS.md" target="_blank" rel="noopener">AGENTS.md</a><a href="'+GH+'/blob/main/skills/1strun/SKILL.md" target="_blank" rel="noopener">The Claude skill</a></p>'+
 "</div>"+
 '<div class="ar-panel" id="ar-pr" role="tabpanel" aria-labelledby="ar-tr" hidden>'+
  '<div class="ar-raw-bar"><span class="ar-meta"><b class="ar-mono">agent.md</b> <span id="ar-lines"></span></span>'+
  '<a href="'+BASE+'agent.md" target="_blank" rel="noopener">Open raw</a>'+
  '<button type="button" class="ar-copy" id="ar-cpall" disabled>'+IC.copy+"<span>Copy all</span></button></div>"+
  '<div id="ar-rawbox"><pre class="ar-raw wait" tabindex="0">Loading agent.md</pre></div>'+
 "</div></div>"+
 '<p class="ar-sr" aria-live="polite" id="ar-live"></p>';
 document.body.appendChild(dlg);
 paint();

 q(".ar-x").addEventListener("click",function(){dlg.close()});
 q(".ar-seg").addEventListener("change",function(e){if(e.target.name==="ar-task"){task=e.target.value;paint()}});
 q(".ar-os").addEventListener("click",function(e){var b=e.target.closest("button");if(b){os=b.getAttribute("data-os");paint();b.focus()}});
 q("#ar-cp").addEventListener("click",function(){copy(L1+"\n"+TASKS[task].line,q("#ar-cp"),"Prompt copied")});
 q("#ar-cpall").addEventListener("click",function(){if(raw)copy(raw,q("#ar-cpall"),"agent.md copied")});
 q(".ar-steps").addEventListener("click",function(e){var b=e.target.closest("[data-copy]");if(b)copy(q("#"+b.getAttribute("data-copy")).textContent,b,"Command copied")});
 /* tabs: click or the arrow keys */
 var tabs=[q("#ar-tq"),q("#ar-tr")];
 function pick(i,focus){
  tabs.forEach(function(t,j){var on=i===j;t.setAttribute("aria-selected",on?"true":"false");t.tabIndex=on?0:-1;q("#"+t.getAttribute("aria-controls")).hidden=!on});
  q(".ar-body").scrollTop=0;if(focus)tabs[i].focus();if(i===1)loadRaw();
 }
 tabs.forEach(function(t,i){t.addEventListener("click",function(){pick(i)})});
 q(".ar-tabs").addEventListener("keydown",function(e){
  var i=tabs.indexOf(document.activeElement);if(i<0)return;
  if(e.key==="ArrowRight"||e.key==="ArrowLeft"){e.preventDefault();pick(1-i,true)}
  else if(e.key==="Home"){e.preventDefault();pick(0,true)}else if(e.key==="End"){e.preventDefault();pick(1,true)}
 });
 /* a click on the backdrop closes it. A drag that starts inside the panel does not. */
 dlg.addEventListener("mousedown",function(e){down=e.target});
 dlg.addEventListener("click",function(e){if(e.target===dlg&&down===dlg)dlg.close();down=null});
 dlg.addEventListener("close",function(){
  document.documentElement.classList.remove("ar-lock","ar-gut");
  if(onclose)onclose();
  if(back&&back.isConnected)back.focus({preventScroll:true});
 });
}

function loadRaw(){
 if(raw||rawP)return;
 rawP=fetch(BASE+"agent.md",{cache:"no-cache"}).then(function(r){if(!r.ok)throw 0;return r.text()}).then(function(t){
  raw=t;var p=q("#ar-rawbox pre");p.textContent=t;p.classList.remove("wait");
  q("#ar-lines").textContent=t.split("\n").length+" lines";q("#ar-cpall").disabled=false;
 }).catch(function(){
  rawP=null;
  q("#ar-rawbox").innerHTML='<p class="ar-fail" role="status">agent.md did not load here. <a href="'+BASE+'agent.md" target="_blank" rel="noopener">Open agent.md</a> or give your agent '+esc(SITE)+"agent.md.</p>";
 });
}

function copy(text,btn,msg){
 var live=q("#ar-live");
 function ok(){
  if(btn._orig==null)btn._orig=btn.innerHTML;
  btn.classList.add("done");
  btn.innerHTML=IC.ok+(btn.querySelector("span")?"<span>Copied</span>":"");
  live.textContent="";setTimeout(function(){live.textContent=msg},30);
  clearTimeout(btn._t);btn._t=setTimeout(function(){btn.classList.remove("done");btn.innerHTML=btn._orig},1800);
 }
 function legacy(){
  var ta=document.createElement("textarea");ta.value=text;ta.setAttribute("readonly","");ta.style.cssText="position:fixed;top:0;left:0;opacity:0";
  dlg.appendChild(ta);ta.select();var done=false;try{done=document.execCommand("copy")}catch(e){}
  dlg.removeChild(ta);btn.focus();
  if(done)ok();else live.textContent="Copy failed. Select the text and press Ctrl+C.";
 }
 if(navigator.clipboard&&window.isSecureContext)navigator.clipboard.writeText(text).then(ok,legacy);else legacy();
}

window.FRAgent={open:function(o){
 BASE=o.base||"";back=o.back||null;onclose=o.onclose||null;
 if(!dlg)build();
 if(dlg.open)return;
 var de=document.documentElement;
 /* lock the page. Keep the scrollbar's space, so nothing behind the dialog moves. */
 if(innerWidth>de.clientWidth)de.classList.add("ar-gut");
 de.classList.add("ar-lock");
 dlg.showModal();
 var cp=q("#ar-cp");if(cp&&!q("#ar-pq").hidden)cp.focus({preventScroll:true});
}};
})();
