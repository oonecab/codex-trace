"use strict";
const $ = id => document.getElementById(id);
const state = {sessions: [], sid: null, data: null, category: "all", query: "", selected: null, detail: null, tab: "content", limit: 250, reading: false, busy: false, ticket: 0};
const defs = [["all","全部"],["thinking","思考"],["command","命令"],["file","文件"],["tools","工具"],["message","说明"],["errors","异常"]];
const fmt = new Intl.DateTimeFormat("zh-CN", {month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hour12:false});
const clockFmt = new Intl.DateTimeFormat("zh-CN", {hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false});
function node(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
function shortDate(ms) { return ms ? fmt.format(new Date(ms)) : "时间未知"; }
function clock(ms) { return ms ? clockFmt.format(new Date(ms)) : ""; }
function duration(ms) { if (ms == null || !Number.isFinite(ms)) return "—"; if (ms < 1000) return Math.round(ms)+"ms"; if (ms < 60000) return (ms/1000).toFixed(ms<10000?1:0)+"s"; if (ms < 3600000) return Math.floor(ms/60000)+"m "+Math.floor(ms%60000/1000)+"s"; return Math.floor(ms/3600000)+"h "+Math.floor(ms%3600000/60000)+"m"; }
function announce(text) { $("notice").textContent = text || ""; $("notice").hidden = !text; }
function toast(text) { $("toast").textContent=text; $("toast").hidden=false; setTimeout(()=>$("toast").hidden=true,2200); }
async function api(path) { const r=await fetch(path,{cache:"no-store"}); const data=await r.json(); if(!r.ok) throw new Error(data.error||"读取失败"); return data; }
function eventKey(e) { return e.turnId+"/"+e.id; }
function timelineEvents(respectVisibility=true) {const firstRequests=new Set();return state.data.events.filter(e=>{if(respectVisibility&&!$("show-empty-thoughts").checked&&e.category==="thinking"&&!e.hasReadableText)return false;if(e.category!=="request")return true;if(firstRequests.has(e.turnId))return true;firstRequests.add(e.turnId);return false;});}
function selectedSession() { return state.sessions.find(s=>s.id===state.sid); }
function renderSessions() {
  const query=$("session-search").value.toLocaleLowerCase(); const project=$("project-filter").value;
  const list=state.sessions.filter(s=>(!s.archived||$("show-archived").checked)&&(!project||s.cwd===project)&&(!query||(s.title+" "+s.cwd).toLocaleLowerCase().includes(query)));
  $("session-count").textContent=list.length;
  const fragment=document.createDocumentFragment();
  for (const s of list) {
    const button=node("button","session-item"+(s.id===state.sid?" selected":"")); button.type="button"; button.setAttribute("aria-pressed",s.id===state.sid); button.title=s.title+"\n"+s.cwd;
    button.append(node("span","session-name",s.title)); const meta=node("small"); meta.append(node("span","",s.project+(s.archived?" · 归档":"")),node("span","",shortDate(s.updatedAt))); button.append(meta); button.addEventListener("click",()=>selectSession(s.id)); fragment.append(button);
  }
  if(!list.length) fragment.append(node("div","placeholder","没有匹配的会话。可以清除搜索条件或勾选“含归档”。"));
  $("sessions").replaceChildren(fragment);
}
async function loadSessions() {
  const result=await api("/api/sessions"); state.sessions=result.sessions;
  const old=$("project-filter").value; const projects=new Map(state.sessions.map(s=>[s.cwd,s.project]));
  $("project-filter").replaceChildren(new Option("所有项目",""));
  [...projects].sort((a,b)=>a[1].localeCompare(b[1])).forEach(([value,label])=>{const opt=new Option(label,value);opt.title=value;$("project-filter").add(opt);});
  $("project-filter").value=old; renderSessions();
  if(result.warning) announce(result.warning);
}
function syncHash() { const hash=new URLSearchParams();if(state.sid)hash.set("session",state.sid); history.replaceState(null,"","#"+hash); }
async function selectSession(sid) {
  state.sid=sid;state.category="all";state.query="";state.selected=null;state.detail=null;state.limit=250;state.data=null;
  $("event-search").value="";closeDetail();$("session-view").hidden=true;$("welcome").hidden=false;$("welcome").querySelector("h1").textContent="正在整理执行记录…";
  document.querySelector(".app").classList.remove("nav-open");renderSessions();syncHash();document.querySelector(".workspace").scrollTop=0;
  await refresh(true);
}
async function refresh(force=false) {
  if(!state.sid||state.busy&&!force)return;
  const ticket=++state.ticket;state.busy=true;$("refresh").disabled=true;
  try {
    const data=await api("/api/sessions/"+encodeURIComponent(state.sid)+(force?"?refresh=1":""));if(ticket!==state.ticket)return;
    const same=state.data&&JSON.stringify([state.data.events,state.data.turns,state.data.session,state.data.analysis])===JSON.stringify([data.events,data.turns,data.session,data.analysis]);
    state.data=data;$("welcome").hidden=true;$("session-view").hidden=false;announce(data.warnings.join(" "));
    $("last-refreshed").textContent="更新于 "+clock(data.loadedAt);
    if(!same) renderData();
    if(state.selected) await loadSelectedDetail();
  } catch(e) { if(ticket===state.ticket){announce(e.message);if(!state.data)$("welcome").querySelector("h1").textContent="暂时无法读取这条会话";} }
  finally { if(ticket===state.ticket){state.busy=false;$("refresh").disabled=false;} }
}
function renderData() {
  const d=state.data,s=d.session;$("session-title").textContent=s.title;document.title=s.title+" · Codex Trace";
  $("project-name").textContent=s.project;$("session-model").textContent=s.model;$("session-date").textContent=shortDate(s.createdAt);$("session-origin").textContent=s.originator;$("session-cwd").textContent=s.cwd;
  const running=d.turns.some(t=>t.status==="inProgress");$("session-state").textContent=running?"● 执行中":s.archived?"已归档":"历史记录";
  $("empty-thought-count").textContent=d.stats.thinkingWithoutText||"";
  const sumDuration=d.turns.reduce((a,t)=>a+(t.durationMs??(t.completedAt&&t.startedAt?t.completedAt-t.startedAt:0)),0);
  const facts=[[d.turns.length,"轮对话"],[d.stats.toolCalls,"次工具调用"],[d.stats.files,"个修改文件"],[d.stats.errors,"项异常 / 非零退出"],[duration(sumDuration),"已结束轮次用时"]];
  $("summary-strip").replaceChildren(...facts.map(([value,label],i)=>{const block=node("div","summary-item"+(i===3&&value?" error":""));block.append(node("strong","",String(value)),node("span","",label));return block;}));
  renderFilters();renderTrack();renderTimeline();ProcessViews.render(d);if(state.detail)renderDetail();
}
function matches(e,cat=state.category) { return cat==="all" || cat==="errors"&&e.error || cat==="tools"&&["tool","web","agent","context","wait","image","other"].includes(e.category) || e.category===cat; }
function renderFilters() {
  $("category-filters").replaceChildren(...defs.map(([cat,label])=>{const b=node("button",cat===state.category?"active":"",label);b.type="button";b.dataset.cat=cat;b.setAttribute("aria-pressed",cat===state.category);b.append(node("b","",timelineEvents().filter(e=>matches(e,cat)).length));b.addEventListener("click",()=>{state.category=cat;state.limit=250;renderFilters();renderTimeline();});return b;}));
}
function renderTrack() {
  const events=timelineEvents(false);
  // Up to 800 aggregate bins keep very long sessions responsive; each bin links to its first event.
  const stride=Math.max(1,Math.ceil(events.length/800)); const marks=[];
  for(let i=0;i<events.length;i+=stride){const e=events[i];const b=node("button",(eventKey(e)===state.selected?"selected ":"")+(e.error?"error":""));b.style.background="var(--"+e.category+")";b.title=e.label+" · "+e.title+(stride>1?`（此段含至多 ${stride} 个事件）`:"");b.setAttribute("aria-label",b.title);b.addEventListener("click",()=>locate(e));marks.push(b);}
  $("activity-track").replaceChildren(...marks);
}
function locate(e) {
  if(e.category==="thinking"&&!e.hasReadableText)$("show-empty-thoughts").checked=true;
  state.category="all";state.query="";$("event-search").value="";state.limit=Math.max(250,state.data.events.indexOf(e)+5);renderFilters();renderTimeline();
  const target=[...document.querySelectorAll(".event")].find(el=>el.dataset.key===eventKey(e));if(target)target.scrollIntoView({block:"center"});selectEvent(e);
}
function renderTimeline() {
  const d=state.data;if(!d)return;const query=state.query.toLocaleLowerCase();const pool=timelineEvents().filter(e=>matches(e)&&(!query||(e.title+" "+e.preview+" "+e.label+" "+e.files.join(" ")).toLocaleLowerCase().includes(query)));
  const shown=pool.slice(0,state.limit);$("visible-count").textContent=`显示 ${shown.length} / ${pool.length} 个事件`;
  $("load-more-wrap").hidden=shown.length>=pool.length;$("load-more").textContent=`继续显示 ${Math.min(250,pool.length-shown.length)} 个事件`;
  const byTurn=new Map();for(const e of shown){if(!byTurn.has(e.turnId))byTurn.set(e.turnId,[]);byTurn.get(e.turnId).push(e);}
  const fragment=document.createDocumentFragment();
  for(let index=0;index<d.turns.length;index++){
    const t=d.turns[index],events=byTurn.get(t.id)||[];if(!events.length&&(pool.length||state.category!=="all"||query))continue;
    const turn=node("section","turn");turn.dataset.turn=t.id;
    const head=node("div","turn-header"),request=node("div","turn-request"),num=node("span","turn-number",String(index+1).padStart(2,"0"));
    const req=d.events.find(e=>e.turnId===t.id&&e.category==="request");const requestBtn=node("button");requestBtn.append(node("h2","",req?req.preview||req.title:"此轮没有保存用户请求"));if(req)requestBtn.addEventListener("click",()=>selectEvent(req));request.append(requestBtn);
    const meta=node("small");meta.append(node("span","",shortDate(t.startedAt)),node("span","",t.status==="inProgress"?"进行中":t.status==="completed"?"已结束":t.status==="interrupted"?"已中断":"状态未记录"));if(t.durationMs!=null)meta.append(node("span","",duration(t.durationMs)));request.append(meta);head.append(num,request);turn.append(head);
    const items=node("div","events");
    for(const e of events){
      const button=node("button","event"+(eventKey(e)===state.selected?" selected":"")+(e.error?" error":""));button.type="button";button.dataset.key=eventKey(e);button.dataset.category=e.category;button.dataset.phase=e.phase||"";button.style.setProperty("--event-color","var(--"+e.category+")");button.setAttribute("aria-pressed",eventKey(e)===state.selected);
      const top=node("div","event-top");top.append(node("span","event-kind",e.label));if(e.error)top.append(node("span","event-error",e.exitCode!=null?"退出 "+e.exitCode:"异常"));top.append(node("time","event-time",clock(e.timestamp)),node("span","event-duration",e.durationMs!=null?duration(e.durationMs):""));
      const prose=["message","thinking","request"].includes(e.category);
      button.append(top,node("div","event-title",prose?e.preview||e.title:e.title));
      if(!prose&&e.preview&&e.preview.replace(/\s+/g," ").trim()!==e.title.trim())button.append(node("p","event-preview",e.preview));
      button.addEventListener("click",()=>selectEvent(e));items.append(button);
    }
    turn.append(items);fragment.append(turn);
  }
  if(!pool.length)fragment.append(node("div","empty-state",d.events.length?"这个筛选条件下没有事件。试试其他类别或清除搜索词。":"这条会话还没有可读取的执行事件。"));
  $("timeline").replaceChildren(fragment);$("timeline").classList.toggle("reading-mode",state.reading);
}
async function selectEvent(e) {
  ProcessViews.select(eventKey(e));
  const key=eventKey(e);state.selected=key;state.detail=null;state.tab="content";$("detail").hidden=false;document.querySelector(".app").classList.add("inspecting");
  $("detail-label").textContent=e.label;$("detail-title").textContent=e.title;$("detail-meta").replaceChildren();$("detail-body").replaceChildren(node("div","placeholder","正在读取原始内容…"));$("detail-source").textContent="";
  document.querySelectorAll(".event").forEach(el=>{el.classList.toggle("selected",el.dataset.key===key);el.setAttribute("aria-pressed",el.dataset.key===key);});renderTrack();
  await loadSelectedDetail();
}
async function loadSelectedDetail() {
  const sid=state.sid,key=state.selected,e=state.data?.events.find(item=>eventKey(item)===key);if(!e)return;
  try {const data=await api(`/api/sessions/${encodeURIComponent(sid)}/items/${encodeURIComponent(e.id)}?turn=${encodeURIComponent(e.turnId)}`);if(state.sid!==sid||state.selected!==key)return;if(JSON.stringify(state.detail)===JSON.stringify(data))return;state.detail=data;$("detail-label").textContent=data.label;$("detail-title").textContent=data.title;renderDetail();}
  catch(err){if(state.sid===sid&&state.selected===key)$("detail-body").replaceChildren(node("div","placeholder",err.message));}
}
function renderDetail() {
  const d=state.detail;if(!d)return;
  const metadata=[clock(d.timestamp),d.durationMs!=null?"耗时 "+duration(d.durationMs):null,d.exitCode!=null?"退出码 "+d.exitCode:null,d.status==="inProgress"?"进行中":null].filter(Boolean);
  $("detail-meta").replaceChildren(...metadata.map(x=>node("span","",x)));
  document.querySelectorAll("[data-tab]").forEach(el=>el.setAttribute("aria-selected",el.dataset.tab===state.tab));
  const blocks=[];function add(title,text,prose=false){if(!text)return;const block=node("section","detail-block");block.append(node("h4","",title),node("pre",prose?"prose":"",text));blocks.push(block);}
  if(state.tab==="raw")add("原始条目",JSON.stringify(d.raw,null,2));
  else{
    const insight=ProcessViews.insight(d);if(insight)blocks.push(insight);
    if(d.body)add(d.category==="thinking"?"记录中的可读摘要":"内容",d.body,true);
    add(d.category==="file"?"文件变更":"输入 / 命令",d.input);
    add("返回结果",d.output);
    if(!d.body&&!d.input&&!d.output)add("记录说明",d.category==="thinking"?"这次思考没有可展示的公开摘要。可在时间线中看到它发生的位置和已记录的耗时。":"此事件没有保存可读的输入或返回结果。可以查看原始记录中的字段。",true);
    for(const id of d.agents||[]){const button=node("button","agent-link","打开子代理会话 ↗ "+id.slice(0,12));button.addEventListener("click",()=>selectSession(id));blocks.push(button);}
  }
  $("detail-body").replaceChildren(...blocks);$("detail-source").textContent=`来源 ${d.source} · 序号 ${d.ordinal}\n事件 ${d.id}`;
}
function closeDetail(){state.selected=null;state.detail=null;$("detail").hidden=true;document.querySelector(".app").classList.remove("inspecting");document.querySelectorAll(".event.selected").forEach(el=>{el.classList.remove("selected");el.setAttribute("aria-pressed","false");});ProcessViews.select(null);if(state.data)renderTrack();}
$("session-search").addEventListener("input",renderSessions);$("project-filter").addEventListener("change",renderSessions);$("show-archived").addEventListener("change",renderSessions);
$("event-search").addEventListener("input",e=>{state.query=e.target.value;state.limit=250;renderTimeline();});
$("show-empty-thoughts").addEventListener("change",()=>{state.limit=250;renderFilters();renderTimeline();});
$("refresh").addEventListener("click",async()=>{try{await loadSessions();await refresh(true);}catch(e){announce(e.message);}});
$("density").addEventListener("click",()=>{state.reading=!state.reading;$("density").setAttribute("aria-pressed",state.reading);$("density").textContent=state.reading?"紧凑视图":"连续阅读";$("timeline").classList.toggle("reading-mode",state.reading);});
$("latest").addEventListener("click",()=>{state.limit=state.data?.events.length||250;renderTimeline();requestAnimationFrame(()=>{const el=document.querySelector(".workspace");el.scrollTop=el.scrollHeight;});});
$("load-more").addEventListener("click",()=>{state.limit+=250;renderTimeline();});$("close-detail").addEventListener("click",closeDetail);
document.querySelectorAll("[data-tab]").forEach(el=>el.addEventListener("click",()=>{state.tab=el.dataset.tab;renderDetail();}));
$("copy-detail").addEventListener("click",async()=>{if(!state.detail)return;const d=state.detail;try{await navigator.clipboard.writeText(state.tab==="raw"?JSON.stringify(d.raw,null,2):[d.body,d.input,d.output].filter(Boolean).join("\n\n"));toast("已复制");}catch{toast("复制不可用，请选中文字复制");}});
$("nav-toggle").addEventListener("click",()=>document.querySelector(".app").classList.toggle("nav-open"));
document.addEventListener("keydown",e=>{if(e.key==="Escape"){closeDetail();document.querySelector(".app").classList.remove("nav-open");}if(e.key==="/"&&!/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)){e.preventDefault();$("session-search").focus();}});
let ticks=0;setInterval(async()=>{if(!$("live").checked||document.hidden)return;await refresh();if(++ticks%6===0){try{await loadSessions();}catch{/* the next user refresh can surface index errors */}}},5000);
ProcessViews.configure({openEvent:selectEvent,openSession:selectSession,closeDetail});
(async()=>{try{const info=await api("/api/info");$("source-path").textContent=info.home;$("source-path").title=info.home;await loadSessions();const sid=new URLSearchParams(location.hash.slice(1)).get("session");if(sid&&state.sessions.some(s=>s.id===sid))await selectSession(sid);else if(state.sessions.length)await selectSession(state.sessions.find(s=>!s.archived)?.id||state.sessions[0].id);else{$("welcome").querySelector("h1").textContent="还没有找到本地会话";announce("请确认启动时指定了正确的 Codex 数据目录。");}}catch(e){announce(e.message);}})();
