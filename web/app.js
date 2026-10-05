'use strict';
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (n) => n == null ? '—' : Number(n).toLocaleString('es-ES');
const date = (s) => new Date(s).toLocaleString('es-ES', {day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit'});
const colors = {green:'#6ee1bd',yellow:'#ebcc76',orange:'#e99c6c',red:'#ef838d',gray:'#718399'};
const labels = {green:'Favorable',yellow:'Fricción localizada',orange:'Obstáculos',red:'Obstáculos graves',gray:'Sin evaluación'};
const dimensions = {contracts:'Contratos',context:'Contexto',verification:'Verificabilidad',observability:'Observabilidad',change_locality:'Localidad del cambio'};
const levels = {favorable:'Favorable',friction:'Fricción',obstacle:'Obstáculo',unknown:'Sin datos'};
const state = {config:null, project:null, selected:null, detail:null, expanded:new Set(), tab:'overview', view:'architecture', graph:{x:0,y:0,scale:1,width:900,height:600}, conversations:{}, busy:new Set(), search:'', positions:{}};
let profile;
try { profile=JSON.parse(localStorage.getItem('checker-profile')) || {}; } catch { profile={}; }
profile = {provider:'codex',model:'',endpoint:'http://127.0.0.1:11434', ...profile};
if(!profile.model)profile.model='gpt-6-luna';

async function api(path, body) {
  const options = body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Code-Checker-Token':state.config.token},body:JSON.stringify(body)};
  const response = await fetch('/api'+path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail==='string' ? data.detail : JSON.stringify(data.detail));
  return data;
}
function status(message, error=false, busy=false) { $('status').textContent=message; $('status').className='status'+(error?' error':'')+(busy?' busy':'')+(!message?' hidden':''); }
function toast(message) { $('toast').textContent=message; $('toast').classList.add('show'); clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('toast').classList.remove('show'),3500); }
function catchError(error) { status(error.message || String(error),true); }
function bind(id, event, fn) { $(id).addEventListener(event, e => Promise.resolve(fn(e)).catch(catchError)); }
async function poll(jobId, text) {
  status(text,false,true);
  for (;;) {
    const job=await api('/jobs/'+jobId);
    if(job.status==='completed') { status(''); return job.result; }
    if(job.status==='failed') throw new Error(job.message);
    await new Promise(resolve=>setTimeout(resolve,1200));
  }
}
function modelsOn(){return state.config?.models_enabled!==false;}
function nodeColor(node) { return node.assessment && !node.assessment.stale ? node.assessment.color : 'gray'; }
const diffLabels={added:'Añadido',modified:'Modificado',deleted:'Eliminado',unknown:'Sin analizar · datos anteriores',contains:'Contiene cambios',impact:'Impacto potencial',impact_path:'Ruta a impacto',context:'Contexto del consumidor'};
function inDiff(n){return !state.project?.comparison||state.diffVisible?.has(n.id);}
function diffBadge(n){return n.diff_status?`<span class="diff-badge diff-${n.diff_status}">${diffLabels[n.diff_status]}</span>`:'';}
function updateDiffFilter(){
  const c=state.project?.comparison;if(!c)return;
  state.diffVisible=new Set($('diff-impact').checked?c.impact_ids:c.changed_ids);
  state.scope='';state.level=null;state.page=0;state.search='';$('search').value='';
  renderScopes();renderStats();renderTree();renderGraph(true);
  $('diff-summary').textContent=`${c.pull_request?'PR #'+c.pull_request.number+' · '+c.pull_request.title+' · ':''}${c.mode==='working'?'Archivos actuales frente a':c.mode==='pr'?'PR desde ancestro común':'Comparación desde'} ${c.base} (${c.base_sha.slice(0,8)})${c.mode==='working'?'':` → ${c.head} (${c.head_sha.slice(0,8)})`} · ${c.files.length} archivos · ${c.direct_count} componentes añadidos/modificados/eliminados · ${c.impacted_count} consumidores potenciales. Vista estática: no ejecuta el modelo. ${c.note}`;
  $('diff-summary').classList.remove('hidden');$('diff-files').classList.remove('hidden');
  $('lazy-status').textContent='Diff estático · modelo pausado en esta vista';$('evaluate-map').disabled=true;
  $('export-btn').disabled=true;$('coverage-btn').disabled=true;$('run-btn').disabled=true;
  $('diff-file-list').innerHTML=c.files.length?c.files.map(f=>`<div><b>${esc(f.status)}</b> ${f.old_path?esc(f.old_path)+' → ':''}${esc(f.path)} <small>${f.mapped?'En mapa Python':'Sin componente Python indexado'}</small></div>`).join(''):'<p>No hay archivos cambiados en esta comparación.</p>';
  const first=state.project.nodes.find(n=>n.id===state.visibleModules?.[0]);
  state.tab='metrics';state.selected=null;state.detail=null;
  if(first)selectNode(first.id).catch(catchError);else $('inspector').innerHTML='<div class="inspector-placeholder"><h3>Sin componentes en este filtro</h3><p>Consulta el inventario de archivos o cambia la comparación.</p></div>';
}
async function loadGitRefs(){
  if(!state.project)return;
  const data=await api(`/projects/${state.project.id}/git-options`);
  state.gitRefs=data.refs;
  $('git-refs').innerHTML=['HEAD',...data.refs].map(r=>`<option value="${esc(r)}"></option>`).join('');
  toast(`Rama actual: ${data.branch}. Referencias disponibles cargadas.`);
}
function selectedPR(){return (state.pullRequests||[]).find(p=>String(p.number)===$('diff-pr').value);}
function describePR(){
  const p=selectedPR();
  $('diff-pr-info').textContent=p?`#${p.number} · ${p.head} → ${p.base} · ${p.merged?'Integrado':p.state==='closed'?'Cerrado':p.draft?'Borrador':'Abierto'}`:'Selecciona un PR o escribe su número. Se leerán sus commits sin modificar el repositorio.';
}
async function loadPullRequests(){
  if(!state.project)return;
  const pid=state.project.id,filter=$('diff-pr-state').value,serial=state.prRequest=(state.prRequest||0)+1;
  const previous=$('diff-pr').value;
  $('diff-pr-load').disabled=true;$('diff-pr').disabled=true;
  $('diff-pr-info').textContent='Consultando los PR de GitHub…';
  try{
    const data=await api(`/projects/${pid}/pull-requests?state=${filter}`);
    if(serial!==state.prRequest||state.project.id!==pid)return;
    state.pullRequests=data.pull_requests;
    $('diff-pr').innerHTML='<option value="">Selecciona un PR…</option>'+data.pull_requests.map(p=>`<option value="${p.number}">#${p.number} · ${esc(p.title)} · ${esc(p.head)} → ${esc(p.base)}${p.merged?' · integrado':p.state==='closed'?' · cerrado':p.draft?' · borrador':''}</option>`).join('');
    if(data.pull_requests.some(p=>String(p.number)===previous))$('diff-pr').value=previous;
    $('diff-pr-number').value='';
    describePR();
    if(!data.pull_requests.length)$('diff-pr-info').textContent='No hay PR en este estado. Cambia el filtro o indica un número.';
    $('diff-pr-repo').textContent=`${data.repository} · ${data.pull_requests.length} PR${data.truncated?' más recientes (límite 500); usa el número para uno anterior':''}`;
  }catch(error){
    if(serial===state.prRequest){state.pullRequests=[];$('diff-pr').innerHTML='<option value="">Lista no disponible</option>';$('diff-pr-info').textContent=error.message;}
  }finally{if(serial===state.prRequest){$('diff-pr-load').disabled=false;$('diff-pr').disabled=false;}}
}
async function applyDiff(){
  if(!state.project){$('diff-only').checked=false;toast('Abre primero un proyecto.');return;}
  const mode=$('diff-mode').value;
  const prNumber=mode==='pr'?Number($('diff-pr-number').value||$('diff-pr').value):null;
  if(mode==='pr'&&(!Number.isInteger(prNumber)||prNumber<1)){
    if(!state.project.comparison)$('diff-only').checked=false;
    toast('Selecciona un PR del desplegable o escribe su número.');return;
  }
  const serial=state.diffRequest=(state.diffRequest||0)+1,pid=state.project.id;
  $('diff-only').checked=true;$('diff-refresh').disabled=true;
  try{
    const {job_id}=await api(`/projects/${pid}/diff`,{base:mode==='pr'?'HEAD':$('diff-base').value.trim(),head:mode==='pr'?'HEAD':$('diff-head').value.trim(),mode:mode==='branches'?'pr':mode,pr_number:prNumber});
    const result=await poll(job_id,'Calculando el diff y sus consumidores por Git · solo lectura…');
    if(serial!==state.diffRequest||!$('diff-only').checked||state.project.id!==pid)return;
    if(!state.project.comparison)state.fullProject=state.project;
    state.project=result.project;state.diffJobId=job_id;
    $('origin-note').textContent='Comparación Git de solo lectura · sin checkout, fetch ni cambios en el repositorio. Los eliminados se consultan en la revisión anterior.';
    updateDiffFilter();
  }catch(error){
    if(serial===state.diffRequest&&!state.project.comparison)$('diff-only').checked=false;
    throw error;
  }finally{if(serial===state.diffRequest)$('diff-refresh').disabled=false;}
}
function leaveDiff(){
  state.diffRequest=(state.diffRequest||0)+1;$('diff-refresh').disabled=false;
  $('diff-summary').classList.add('hidden');$('diff-files').classList.add('hidden');
  $('evaluate-map').disabled=state.config?.models_enabled===false;$('export-btn').disabled=false;$('coverage-btn').disabled=false;$('run-btn').disabled=false;
  if(state.fullProject){state.project=state.fullProject;state.fullProject=null;state.diffJobId=null;state.diffVisible=null;state.level=null;state.scope='';state.page=0;state.selected=null;state.detail=null;renderScopes();renderStats();renderTree();renderGraph(true);$('inspector').innerHTML='<div class="inspector-placeholder"><h3>Proyecto completo</h3><p>Selecciona un componente.</p></div>';$('origin-note').textContent='Índice del proyecto actual · lectura estática. Pulsa ↻ para actualizarlo.';}
  scheduleLazy();
}
function badge(node) { const color=nodeColor(node); return `<span class="pill ${color}"><i class="dot ${color}"></i>${node.assessment?.stale?'Desactualizada':labels[color]}</span>`; }
function showView(name) { state.view=name; document.querySelectorAll('.view').forEach(el=>el.classList.toggle('active',el.id===name)); document.querySelectorAll('[data-view]').forEach(el=>el.classList.toggle('active',el.dataset.view===name)); if(name==='evidence')renderEvidence(); if(name==='history')renderHistory(); }

async function openProjectDialog() {
  const projects=await api('/projects');
  $('recent-projects').innerHTML=projects.length?'<div class="eyebrow">RECIENTES</div>'+projects.slice(0,6).map(p=>`<button type="button" class="recent" data-project="${p.id}">${esc(p.name)}<small>${esc(p.root)}</small></button>`).join(''):'';
  $('open-dialog').showModal();
}
async function scan(path,sshHost='') {
  $('open-dialog').close();
  const {job_id}=await api('/scan',{path,ssh_host:sshHost});
  const result=await poll(job_id,'Analizando el proyecto Python…');
  await loadProject(result.project_id, state.project?.id===result.project_id);
  toast('Análisis completado. Los archivos del proyecto no se han ejecutado.');
}
async function loadProject(id, keepSelection=false) {
  if(state.project?.comparison){$('diff-only').checked=false;leaveDiff();}
  const old=state.selected;
  const previousProject=state.project?.id;
  state.project=await api('/projects/'+id);
  if(previousProject!==id){
    state.prRequest=(state.prRequest||0)+1;state.pullRequests=[];state.gitRefs=[];
    $('diff-pr').innerHTML='<option value="">Selecciona un PR…</option>';$('diff-pr-number').value='';$('diff-pr-repo').textContent='';$('git-refs').innerHTML='';
    if($('diff-mode').value==='pr')loadPullRequests();
  }
  if(previousProject!==id){state.scope='';state.level=null;state.page=0;state.lazyFailures=new Set();}
  $('connect-host').value=state.project.origin?.kind==='ssh'?state.project.origin.host:'';
  $('connect-path').value=state.project.root;
  renderScopes();
  const origin=state.project.origin;
  $('origin-note').classList.toggle('hidden',!origin);
  $('origin-note').textContent=origin?.kind==='ssh'?`Lectura directa SSH · ${origin.host}:${origin.remote_path} · ${origin.revision?.slice(0,8)}${origin.dirty?' + cambios sin commit':''}. Fuentes bajo demanda; sin copia local del repositorio. El refresco comprueba el servidor remoto.`:origin?`Instantánea SSH · ${origin.host}:${origin.remote_path} · ${origin.revision?.slice(0,8)}${origin.dirty?' + cambios sin commit':''} · ${date(origin.captured_at)}. La actualización automática comprueba esta copia local, no el servidor remoto.`:'';
  localStorage.setItem('checker-project',id);
  $('welcome').classList.add('hidden');
  $('project-name').textContent=state.project.name;
  $('tree-root').textContent=state.project.name.toUpperCase();
  $('export-btn').disabled=false;
  $('scan-time').textContent='Analizado '+date(state.project.created_at);
  renderStats(); renderTree(); renderGraph(!keepSelection); renderEvidence(); renderHistory();
  if(!keepSelection)showView(state.view);
  const first=state.project.origin?.kind==='ssh'?state.project.nodes.find(n=>n.id===state.visibleModules?.[0]):state.project.nodes.find(n=>n.kind==='module'&&!n.is_test&&n.name.endsWith('service')) || state.project.nodes.find(n=>n.kind==='module'&&!n.is_test);
  await selectNode(keepSelection && state.project.nodes.some(n=>n.id===old)?old:first?.id);
  if(state.project.warnings.length)status('Análisis parcial: '+state.project.warnings.slice(0,2).join(' · '));
  if(state.project.needs_rescan)status('Hay cambios en disco. El análisis se actualizará automáticamente; también puedes pulsar ↻.');
}
function renderStats() {
  if(!state.project)return;
  const p=state.project;
  const modules=p.nodes.filter(n=>n.kind==='module');
  $('stat-modules').textContent=fmt(modules.length);
  $('file-count').textContent=modules.length;
  $('stat-edges').textContent=fmt(p.edges.filter(e=>e.internal).length);
  $('stat-assessed').textContent=fmt(p.nodes.filter(n=>n.assessment&&!n.assessment.stale).length);
  $('stat-runs').textContent=fmt(p.runs.length);
}
function renderTree() {
  if(!state.project)return;
  const q=state.search.toLowerCase();
  let html='';
  for(const module of state.project.nodes.filter(n=>n.kind==='module')) {
    if(!inDiff(module))continue;
    if(state.scope&&!module.path.startsWith(state.scope+'/'))continue;
    const children=state.project.nodes.filter(n=>n.module_id===module.id&&n.kind!=='module');
    if(q&&!module.qualified_name.toLowerCase().includes(q)&&!children.some(n=>n.qualified_name.toLowerCase().includes(q)))continue;
    const open=state.expanded.has(module.id)||!!q;
    html+=`<button class="tree-item ${state.selected===module.id?'selected':''}" data-node="${esc(module.id)}" title="${esc(module.path)}"><span class="tree-toggle" data-toggle="${esc(module.id)}">${open?'▾':'▸'}</span><span class="tree-kind">py</span><span class="name">${esc(module.name)}</span><i class="dot ${nodeColor(module)}"></i></button>`;
    if(open)html+=children.filter(n=>inDiff(n)&&(!q||n.qualified_name.toLowerCase().includes(q))).map(n=>`<button class="tree-item child ${state.selected===n.id?'selected':''}" data-node="${esc(n.id)}" title="${esc(n.qualified_name)}"><span class="tree-kind">${n.kind==='class'?'C':'ƒ'}</span><span class="name">${esc(n.name)}</span><i class="dot ${nodeColor(n)}"></i></button>`).join('');
  }
  $('tree').innerHTML=html||'<p class="inset muted">Ningún componente coincide.</p>';
}

function renderScopes(){
  const counts=new Map();
  for(const n of state.project.nodes.filter(n=>n.kind==='module')){
    if(!inDiff(n))continue;
    const parts=n.path.split('/');parts.pop();
    for(let i=1;i<=parts.length;i++){const key=parts.slice(0,i).join('/');counts.set(key,(counts.get(key)||0)+1);}
  }
  $('package-scope').innerHTML='<option value="">Todo el proyecto</option>'+[...counts].sort((a,b)=>a[0].localeCompare(b[0])).map(([path,count])=>`<option value="${esc(path)}">${esc(path)} · ${count}</option>`).join('');
  $('package-scope').value=state.scope||'';
}

function prepareConnections(edges, width, height=106) {
  state.graphEdges=GraphRouting.routeEdges(state.positions,edges,width,height);
  return '<g id="graph-edges"></g>';
}
function renderConnections() {
  const group=$('graph-edges');if(!group)return;
  const selected=state.positions[state.selected]?state.selected:state.project.nodes.find(n=>n.id===state.selected)?.module_id;
  const focused=!!state.positions[selected], mode=$('connection-mode').value;
  const containerSelected=state.graphContainer?.id===state.selected;
  const edges=state.graphEdges||[];
  const outgoing=edges.filter(e=>e.source===selected),incoming=edges.filter(e=>e.target===selected);
  const visible=mode==='none'?[]:mode==='all'||containerSelected?edges:focused?edges.filter(e=>e.source===selected||e.target===selected):[];
  const names=new Map(state.project.nodes.map(n=>[n.id,n.qualified_name||n.name]));
  group.innerHTML=visible.map(e=>{
    const direction=e.source===selected?'outgoing':e.target===selected?'incoming':'';
    const title=`${names.get(e.source)||e.source} → ${names.get(e.target)||e.target}${e.kind==='call'?' · llamada estática · L'+e.lines.join(', L'):e.context?' · '+e.context:''}${e.diff_removed?' · relación de la revisión anterior':''}`;
    return `<path class="graph-edge ${direction}" d="${e.path}" ${e.context&&e.context!=='runtime'?'stroke-dasharray="5 4"':''}><title>${esc(title)}</title></path>`;
  }).join('');
  // Keep card elements intact: replacing them on click would interrupt double-click navigation.
  document.querySelectorAll('#graph .graph-node').forEach(n=>{
    n.classList.toggle('selected',n.dataset.node===selected);
    n.setAttribute('aria-pressed',String(n.dataset.node===selected));
  });
  document.querySelectorAll('#graph .script-frame').forEach(n=>{n.classList.toggle('selected',containerSelected);n.setAttribute('aria-pressed',String(containerSelected));});
  document.querySelector('.map-toolbar strong').textContent=state.graphKind==='calls'?'Llamadas dentro del script':'Mapa de dependencias';
  document.querySelector('.map-toolbar>div>span').textContent=state.graphKind==='calls'?'Nombres locales resueltos por AST · no implica ejecución':'Imports estáticos · selecciona un componente';
  document.querySelector('.edge-key.outgoing').textContent=state.graphKind==='calls'?'→ Llama a':'→ Depende de';
  document.querySelector('.edge-key.incoming').textContent=state.graphKind==='calls'?'← Llamada por':'← Usado por';
  $('connection-status').textContent=(mode==='none'?'Flechas ocultas':mode==='all'||containerSelected?`${edges.length} conexiones entre las cajas visibles`:focused?
    `${outgoing.length} salientes · ${incoming.length} entrantes · entre las cajas visibles`:'Selecciona una caja para ver sus conexiones');
  if(state.graphKind==='calls')$('connection-status').textContent+=` · ${state.offPageCalls||0} conexiones con cajas fuera de esta página`;
}

function renderGraph(fit=false,forceModules=false) {
  if(!state.project)return;
  state.graphKind='imports';state.graphContainer=null;state.offPageCalls=0;
  if(state.project.origin?.kind==='ssh'||state.project.comparison){renderLevel(fit);return;}
  $('level-up').disabled=true;$('page-prev').disabled=true;$('page-next').disabled=true;$('page-label').textContent='';
  const modules=state.project.nodes.filter(n=>n.kind==='module'&&($('show-tests').checked||!n.is_test));
  const q=state.search.toLowerCase();
  const matchingModules=new Set(state.project.nodes.filter(n=>n.qualified_name.toLowerCase().includes(q)).map(n=>n.module_id));
  let visible=modules.filter(n=>(!state.scope||n.path.startsWith(state.scope+'/'))&&(!q||matchingModules.has(n.id)));
  state.visibleModules=visible.map(n=>n.id);
  $('scope-count').textContent=`${visible.length} módulos en este ámbito`;
  if(visible.length>30&&!q&&!forceModules){renderPackageGraph(visible,fit);return;}
  // Keep DOM responsive on large projects; search narrows the map without truncating analysis.
  const omitted=Math.max(0,visible.length-120);
  visible=visible.slice(0,120);
  const ids=new Set(visible.map(n=>n.id));
  let edges=state.project.edges.filter(e=>ids.has(e.source)&&(ids.has(e.target)||(!e.internal&&$('show-external').checked)));
  const external=new Map();
  if($('show-external').checked)for(const e of edges.filter(e=>!e.internal))external.set(e.target,{id:e.target,name:e.target.replace('external:',''),external:true,metrics:{}});
  const all=visible.concat([...external.values()].slice(0,30));
  const allowed=new Set(all.map(n=>n.id));edges=edges.filter(e=>allowed.has(e.target));
  const rank={};all.forEach(n=>rank[n.id]=0);
  // Bounded layering, retaining readable layout for cyclic graphs.
  const cyclic=new Set(state.project.cycles.flat());
  for(let pass=0;pass<Math.min(5,all.length);pass++)for(const e of edges)if(!cyclic.has(e.target)&&e.context==='runtime')rank[e.target]=Math.min(5,Math.max(rank[e.target],rank[e.source]+1));
  const layers=new Map();for(const n of all){const r=n.external?6:rank[n.id];if(!layers.has(r))layers.set(r,[]);layers.get(r).push(n);}
  const positions={};let row=0;const columns=Math.max(2,Math.min(4,Math.ceil(Math.sqrt(all.length/2))));
  for(const [,layer]of [...layers.entries()].sort((a,b)=>a[0]-b[0])) {
    layer.sort((a,b)=>a.name.localeCompare(b.name));
    layer.forEach((n,i)=>positions[n.id]={x:40+(i%columns)*278,y:40+(row+Math.floor(i/columns))*166});
    row+=Math.ceil(layer.length/columns);
  }
  state.positions=positions;
  const selectedModule=state.project.nodes.find(n=>n.id===state.selected)?.module_id;
  let html=prepareConnections(edges,218);
  html+=all.map(n=>{
    const p=positions[n.id],color=nodeColor(n),label=n.external?'Dependencia externa':n.assessment?.stale?'Evaluación desactualizada':n.assessment?labels[color]:'Pendiente de evaluación';
    const title=n.name.length>25?n.name.slice(0,23)+'…':n.name;
    const frameStyle=color==='gray'?'':`style="stroke:${colors[color]}"`;
    return `<g class="graph-node ${n.external?'external':''} ${selectedModule===n.id?'selected':''}" transform="translate(${p.x},${p.y})" data-node="${esc(n.id)}" role="button" tabindex="0" aria-label="${esc(n.name)}"><title>${esc(n.name)}</title><rect width="218" height="106" rx="7" ${frameStyle}/><circle cx="17" cy="18" r="3" fill="${colors[color]}"/><text x="28" y="21" class="n-kind">${n.external?'EXTERNA':n.is_test?'TEST MODULE':'PYTHON MODULE'}</text><text x="14" y="44" class="n-title">${esc(title)}</text><text x="14" y="60" class="n-path">${esc((n.path||'Import no resuelto dentro del proyecto').slice(-36))}</text><text x="14" y="79" class="n-metric">${n.external?'':`${n.metrics.functions} funciones  ·  ${n.metrics.fan_out} dependencias`}</text><text x="14" y="96" class="n-assess" fill="${colors[color]}">${esc(label)}</text></g>`;
  }).join('');
  $('viewport').innerHTML=html;
  renderConnections();
  $('graph-empty').classList.toggle('hidden',all.length>0);
  state.graph.width=columns*278+20;state.graph.height=Math.max(180,row*166+20);
  if(fit)fitGraph();else transformGraph();
  if(omitted)$('footer-note').textContent=`Mapa: 120 módulos visibles; ${omitted} más. Usa la búsqueda para acotar. Análisis completo conservado.`;
  else $('footer-note').textContent='Análisis estático local · sin ejecutar el código del proyecto';
}
function renderPackageGraph(modules,fit){
  const groups=new Map(),membership=new Map();
  for(const n of modules){
    const path=state.scope?n.path.slice(state.scope.length+1):n.path;
    const folder=path.includes('/')?path.split('/')[0]:null;
    const scope=folder?[state.scope,folder].filter(Boolean).join('/'):null;
    const id=scope?'package:'+scope:n.id;
    if(!groups.has(id))groups.set(id,{id,scope,name:folder||n.name,nodes:[]});
    groups.get(id).nodes.push(n);membership.set(n.id,id);
  }
  // Flat directories remain browsable as modules; they cannot be grouped further.
  if(![...groups.values()].some(g=>g.scope)){
    renderGraph(fit,true);return;
  }
  const all=[...groups.values()].sort((a,b)=>a.name.localeCompare(b.name)),positions={},columns=Math.min(4,Math.max(2,Math.ceil(Math.sqrt(all.length))));
  all.forEach((g,i)=>positions[g.id]={x:40+(i%columns)*278,y:40+Math.floor(i/columns)*166});
  state.positions=positions;
  const edges=new Set();
  for(const edge of state.project.edges){const a=membership.get(edge.source),b=membership.get(edge.target);if(a&&b&&a!==b)edges.add(JSON.stringify([a,b]));}
  let html=prepareConnections([...edges].map(key=>{const [source,target]=JSON.parse(key);return {source,target};}),218);
  html+=all.map(g=>{const p=positions[g.id],done=g.nodes.filter(n=>n.assessment&&!n.assessment.stale).length;return `<g class="graph-node" transform="translate(${p.x},${p.y})" data-node="${esc(g.id)}" role="button" tabindex="0" aria-label="${esc(g.scope?'Abrir paquete '+g.scope:g.name)}"><rect width="218" height="106" rx="7"/><text x="14" y="21" class="n-kind">${g.scope?'PAQUETE · ABRIR →':'PYTHON MODULE'}</text><text x="14" y="46" class="n-title">${esc(g.name.length>24?g.name.slice(0,22)+'…':g.name)}</text><text x="14" y="69" class="n-metric">${g.nodes.length} módulos · ${done} evaluados</text><text x="14" y="92" class="n-path">Colores disponibles al abrir</text></g>`;}).join('');
  $('viewport').innerHTML=html;$('graph-empty').classList.add('hidden');
  renderConnections();
  state.graph.width=columns*278+20;state.graph.height=Math.ceil(all.length/columns)*166+20;
  if(fit)fitGraph();else transformGraph();
  $('footer-note').textContent='Vista de paquetes. Abre uno para inspeccionar los colores individuales; no se promedian evaluaciones.';
}

function renderLevel(fit=false){
  const p=state.project,q=state.search.toLowerCase();
  const level=p.nodes.find(n=>n.id===state.level);
  const script=!q&&level&&level.kind!=='package'?p.nodes.find(n=>n.id===level.module_id):null;
  state.graphKind=script?'calls':'imports';state.graphContainer=script;
  const children=p.nodes.filter(n=>inDiff(n)&&(q?n.qualified_name.toLowerCase().includes(q):n.parent===(state.level||null))&&(p.comparison||$('show-tests').checked||!n.is_test));
  children.sort((a,b)=>(a.kind==='package'?0:1)-(b.kind==='package'?0:1)||a.name.localeCompare(b.name));
  const pages=Math.max(1,Math.ceil(children.length/12));state.page=Math.min(state.page||0,pages-1);
  const visible=children.slice(state.page*12,(state.page+1)*12);
  state.visibleModules=visible.map(n=>n.id);
  $('page-label').textContent=`Nivel ${state.level?.replace('package:','')||'raíz'} · ${state.page+1}/${pages}`;
  $('page-prev').disabled=state.page===0;$('page-next').disabled=state.page>=pages-1;$('level-up').disabled=!state.level;
  $('scope-count').textContent=`${visible.length} cajas visibles de ${children.length} · doble clic para abrir`;
  const columns=Math.max(2,Math.min(3,Math.ceil(Math.sqrt(visible.length)))),positions={};
  visible.forEach((n,i)=>positions[n.id]={x:40+(i%columns)*290,y:(script?120:40)+Math.floor(i/columns)*166});
  state.positions=positions;
  const membership=new Map();
  for(const module of p.nodes.filter(n=>n.kind==='module')){
    const group=visible.find(n=>n.id===module.id||(n.kind==='package'&&module.path.startsWith(n.path+'/')));
    if(group)membership.set(module.id,group.id);
  }
  const edges=new Set();
  for(const e of p.edges){const a=membership.get(e.source),b=membership.get(e.target);if(a&&b&&a!==b)edges.add(JSON.stringify([a,b]));}
  let graphEdges=[...edges].map(key=>{const [source,target]=JSON.parse(key);return {source,target};});
  if(p.comparison){
    const live=new Set(p.edges.filter(e=>!e.diff_removed).map(e=>JSON.stringify([membership.get(e.source),membership.get(e.target)])));
    graphEdges=graphEdges.map(e=>live.has(JSON.stringify([e.source,e.target]))?e:{...e,context:'removed',diff_removed:true});
  }
  if(script){
    const index=new Map(p.nodes.map(n=>[n.id,n])),visibleIds=new Set(visible.map(n=>n.id));
    const representative=id=>{while(id&&id!==script.id){if(visibleIds.has(id))return id;id=index.get(id)?.parent;}return null;};
    const grouped=new Map();state.offPageCalls=0;
    for(const e of p.call_edges||[]){
      if(index.get(e.source)?.module_id!==script.id)continue;
      const source=representative(e.source),target=representative(e.target);
      if(!!source!==!!target){state.offPageCalls++;continue;}
      if(!source||!target||source===target&&e.source!==e.target)continue;
      const key=JSON.stringify([source,target]);
      if(!grouped.has(key))grouped.set(key,{source,target,kind:'call',lines:[],diff_removed:true});
      grouped.get(key).lines.push(...e.lines);
      if(!e.diff_removed)grouped.get(key).diff_removed=false;
    }
    graphEdges=[...grouped.values()].map(e=>e.diff_removed?{...e,context:'removed'}:e);
  }
  const frameWidth=columns*290,frameHeight=Math.max(210,Math.ceil(visible.length/columns)*166+100);
  let html=script?`<g class="script-frame" data-scope-node="${esc(script.id)}" role="button" tabindex="0" aria-label="Métricas del script ${esc(script.path)}"><rect x="8" y="8" width="${frameWidth}" height="${frameHeight}" rx="14"/><text x="30" y="35" class="script-kind">SCRIPT PYTHON · CLIC PARA VER MÉTRICAS DEL ARCHIVO</text><text x="30" y="61" class="script-title">${esc(script.path)}</text><text x="30" y="83" class="script-summary">${script.metrics.functions} funciones y métodos · ${fmt(script.metrics.lines)} líneas · ${visible.length}/${children.length} componentes de este nivel</text></g>`:'';
  html+=prepareConnections(graphEdges,230);
  html+=visible.map(n=>{const pos=positions[n.id],color=nodeColor(n),title=n.name.length>25?n.name.slice(0,23)+'…':n.name;
    return `<g class="graph-node ${n.diff_status?'diff-node diff-'+n.diff_status:''} ${state.selected===n.id?'selected':''}" transform="translate(${pos.x},${pos.y})" data-node="${esc(n.id)}" role="button" tabindex="0" aria-label="${esc(n.qualified_name)}"><title>${esc(n.qualified_name)} · doble clic para abrir</title><rect width="230" height="106" rx="7" style="stroke:${colors[color]}"/><circle cx="16" cy="18" r="3" fill="${colors[color]}"/><text x="27" y="22" class="n-kind">${esc(n.kind.toUpperCase())} · DOBLE CLIC →</text><text x="14" y="46" class="n-title">${esc(title)}</text><text x="14" y="68" class="n-metric">${n.kind==='package'?n.metrics.modules+' módulos':n.kind==='module'?n.metrics.functions+' funciones':'L'+n.line+'–'+n.end_line}</text><text x="14" y="91" class="n-assess" fill="${colors[color]}">${n.diff_status?diffLabels[n.diff_status]:state.busy.has(n.id)?'Evaluando…':n.assessment?.stale?'Desactualizada':n.assessment?labels[color]:'Pendiente · nivel visible'}</text></g>`;}).join('');
  $('viewport').innerHTML=html;$('graph-empty').classList.toggle('hidden',visible.length>0);
  renderConnections();
  state.graph.width=columns*290+20;state.graph.height=script?frameHeight+24:Math.max(180,Math.ceil(visible.length/columns)*166+20);
  if(fit)fitGraph();else transformGraph();
  $('footer-note').textContent='Solo lectura SSH · los colores pertenecen al nivel evaluado · descendientes bajo demanda';
  scheduleLazy();
}
function openLevel(id){
  if(state.project?.origin?.kind!=='ssh'&&!state.project?.comparison)return;
  const node=state.project.nodes.find(n=>n.id===id);
  if(!node)return;
  if(!state.project.nodes.some(n=>n.parent===id)){state.tab='code';selectNode(id).catch(catchError);return;}
  state.level=id;state.page=0;state.search='';$('search').value='';
  state.scope=node.kind==='package'?node.path:node.path.split('/').slice(0,-1).join('/');
  $('package-scope').value=state.scope;renderTree();renderGraph(true);
}
function scheduleLazy(){clearTimeout(state.lazyTimer);state.lazyTimer=setTimeout(processLazy,400);}
function validLazy(n){const a=n.assessment;return a&&!a.stale&&a.fingerprint===state.project.fingerprint&&a.provider===profile.provider&&a.model===profile.model&&a.policy_version===state.config.policy_version;}
async function processLazy(){
  if(state.lazyRunning)return;
  state.lazyRunning=true;state.lazyFailures??=new Set();
  try{
    while(modelsOn()&&state.project?.origin?.kind==='ssh'&&!$('diff-only').checked&&!state.project.needs_rescan&&state.view==='architecture'&&$('lazy-enabled').checked){
      const pid=state.project.id,fp=state.project.fingerprint,chosen={...profile};
      const key=id=>[pid,fp,chosen.provider,chosen.model,id].join('|');
      const n=(state.visibleModules||[]).map(id=>state.project.nodes.find(n=>n.id===id)).find(n=>n&&!validLazy(n)&&!state.busy.has(n.id)&&!state.lazyFailures.has(key(n.id)));
      if(!n)break;
      state.busy.add(n.id);$('lazy-status').textContent=`${chosen.model||chosen.provider} · ${n.name}…`;
      try{
        const job=await api(`/projects/${pid}/evaluate`,{component_id:n.id,...chosen,force:false});
        let assessment;
        if(job.cached)assessment=job.result;
        else{
          for(;;){const progress=await api('/jobs/'+job.job_id);if(progress.status==='completed'){assessment=progress.result.assessment;break;}if(progress.status==='failed')throw new Error(progress.message);await new Promise(resolve=>setTimeout(resolve,1200));}
        }
        if(state.project?.id===pid&&state.project.fingerprint===fp){
          n.assessment=assessment;
          const current=state.project.nodes.find(x=>x.id===n.id);if(current)current.assessment=assessment;
          if(state.detail?.id===n.id){state.detail.assessment=assessment;renderInspector();}
          renderStats();renderTree();renderGraph();
        }
      }catch(error){state.lazyFailures.add(key(n.id));$('lazy-status').textContent='No evaluado: '+error.message;status(error.message,true);break;}
      finally{state.busy.delete(n.id);if(state.project?.id===pid)renderGraph();}
    }
  }finally{state.lazyRunning=false;if($('diff-only').checked)$('lazy-status').textContent='Diff estático · modelo pausado en esta vista';else if(!state.lazyFailures.size)$('lazy-status').textContent=$('lazy-enabled').checked?'Nivel visible al día · GPT-6 Luna por defecto':'Evaluación automática pausada';}
}
bind('lazy-enabled','change',()=>{state.lazyFailures=new Set();scheduleLazy();});
bind('page-prev','click',()=>{state.page=Math.max(0,(state.page||0)-1);renderGraph(true);});
bind('page-next','click',()=>{state.page=(state.page||0)+1;renderGraph(true);});
bind('level-up','click',()=>{const n=state.project.nodes.find(n=>n.id===state.level);state.level=n?.parent||null;state.page=0;state.search='';$('search').value='';const parent=state.project.nodes.find(n=>n.id===state.level);state.scope=parent?.kind==='package'?parent.path:'';$('package-scope').value=state.scope;renderTree();renderGraph(true);});
$('graph').addEventListener('dblclick',e=>{const node=e.target.closest('[data-node]');if(node)openLevel(node.dataset.node);});
$('graph').addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.dataset.node)openLevel(e.target.dataset.node);});

function transformGraph(){const g=state.graph;$('viewport').setAttribute('transform',`translate(${g.x} ${g.y}) scale(${g.scale})`);$('zoom-label').textContent=Math.round(g.scale*100)+'%';}
function fitGraph(){const g=state.graph;g.scale=Math.min(1.35,840/g.width,540/g.height);g.x=(900-g.width*g.scale)/2;g.y=Math.max(10,(600-g.height*g.scale)/2);transformGraph();}
function zoom(factor){const g=state.graph;const next=Math.max(.15,Math.min(3.5,g.scale*factor));g.x=450-(450-g.x)*next/g.scale;g.y=300-(300-g.y)*next/g.scale;g.scale=next;transformGraph();}
async function selectNode(id,preserveGraph=false) {
  if(id?.startsWith('package:')&&state.project.origin?.kind!=='ssh'&&!state.project.comparison){state.scope=id.slice(8);$('package-scope').value=state.scope;state.search='';$('search').value='';renderTree();renderGraph(true);return;}
  if(!id||id.startsWith('external:'))return;
  state.selected=id;
  renderTree();if(!preserveGraph)renderGraph();else renderConnections();
  // Metrics come from the index; viewing them needs neither source fetch nor CLI.
  state.detail=state.project.nodes.find(n=>n.id===id);
  // Leaving a diff can replace the inspector with a placeholder while retaining
  // the Code tab. Rebuild its shell before showing the asynchronous load state.
  renderInspector(state.tab==='code');
  if(state.tab==='metrics'||state.project.comparison&&state.tab!=='code')return;
  const projectId=state.project.id;
  const comparison=state.diffJobId;
  const detail=await api(state.project.comparison?`/diffs/${comparison}/component?id=${encodeURIComponent(id)}`:`/projects/${projectId}/component?id=${encodeURIComponent(id)}`);
  if(state.selected!==id||state.project.id!==projectId||comparison!==state.diffJobId)return;
  state.detail=detail;
  renderInspector();
}
function metric(label,value,note=''){return `<div class="metric"><span>${label}</span><b>${fmt(value)}</b>${note?`<small>${note}</small>`:''}</div>`;}
function openCode() {
  const n=state.detail;if(!n?.source)return;
  $('code-title').textContent=n.qualified_name;
  $('code-path').textContent=`${n.path} · líneas ${n.line}–${n.end_line}`;
  $('code-expanded').innerHTML=PythonHighlight.render(n.source,n.line);
  $('code-dialog').showModal();
  $('code-expanded').scrollTop=0;$('code-expanded').scrollLeft=0;
  $('code-expanded').focus();
}
function resizeCode(delta) {
  state.codeFontSize=Math.max(12,Math.min(24,(state.codeFontSize||15)+delta));
  $('code-expanded').style.fontSize=state.codeFontSize+'px';
  $('code-font-size').textContent=state.codeFontSize+' px';
  $('code-smaller').disabled=state.codeFontSize===12;$('code-larger').disabled=state.codeFontSize===24;
}
function renderStaticMetrics(n,panel) {
  const m=n.metrics,a=m.aggregate,c=n.coverage;
  if(!a){panel.innerHTML='<p>Este índice necesita actualizar las métricas. Pulsa ↻ para recalcularlas sin modelo.</p>';return;}
  const group=['module','package'].includes(n.kind),fn=['function','method'].includes(n.kind);
  const ratio=(label,value,total)=>metric(label,total?Math.round(100*value/total):null,`${fmt(value)} / ${fmt(total)} · ${total?'%':'no aplicable'}`);
  panel.innerHTML=`<div class="info-box">Calculadas automáticamente · sin CLI ni modelo<br><small>AST + imports estáticos · analizador ${esc(m.measurement.analyzer_version)}</small></div>
    <p class="hint">${n.kind==='package'?'Agregado de los módulos analizados del paquete.':'Componente y descendientes; cada ámbito AST se cuenta una sola vez.'} No se ejecuta el código.</p>
    <h3>Estructura y contexto</h3><div class="metric-grid">
    ${n.kind==='package'?metric('Módulos',m.modules):''}${metric('Líneas físicas',m.lines,'Incluyen blancos y comentarios')}
    ${metric('Funciones y métodos',a.functions)}${metric('Clases',a.classes)}${metric('Sentencias AST',a.statements)}
    ${metric(fn?'CC del componente':'CC máxima de función',fn?m.cc:a.max_cc,'Radon · no determina el color')}
    ${metric('Anidamiento máximo AST',a.max_nesting)}${metric('Llamadas estáticas',a.calls,'Expresiones de llamada; no ejecuciones')}</div>
    <h3>Contratos observables</h3><div class="metric-grid">
    ${ratio('Parámetros anotados',a.annotated_parameters,a.parameters)}${ratio('Retornos anotados',a.return_annotations,a.functions)}
    ${ratio('Funciones con docstring',a.documented_functions,a.functions)}</div>
    <p class="hint">Presencia sintáctica. No mide la calidad del contrato ni valida los tipos en ejecución. Se incluyen funciones anidadas; se excluye el receptor self/cls de métodos cuando corresponde.</p>
    ${group?`<h3>Dependencias y alcance</h3><div class="metric-grid">${metric('Dependencias entrantes',m.fan_in,'Módulos únicos fuera del componente')}${metric('Dependencias salientes',m.fan_out,'Módulos internos fuera del componente')}${metric('Imports no resueltos',m.external_dependencies,'Externos o fuera del índice')}${metric('Módulos en ciclos',m.cyclic_modules,'Solo imports de runtime')}${metric('Tests que lo importan',m.test_importers,'Módulos de test con import directo')}${metric('Módulos de test dentro',m.test_modules)}</div>`:'<p class="hint">Las dependencias se miden en el módulo; no se atribuyen imports a esta función o clase.</p>'}
    ${m.local_calls_resolved!==undefined?`<h3>Llamadas del ámbito propio</h3><div class="metric-grid">${metric('Llamadas locales resueltas',m.local_calls_resolved,'Por nombre léxico, sin ejecutar')}${metric('Llamadas sin resolver',m.calls_unresolved,'Incluye atributos, imports, builtins y alias')}</div><p class="hint">El grafo local es parcial. No representa ejecución ni resuelve despacho dinámico. Los cuerpos de funciones anidadas se cuentan en sus propias cajas.</p>`:''}
    <h3>Verificación y observabilidad</h3><div class="metric-grid">
    ${metric('Assert explícitos',a.asserts)}${metric('Raise explícitos',a.raises)}${metric('Manejadores except',a.exception_handlers)}
    ${metric('Except amplios',a.broad_exception_handlers,'Sin tipo, Exception o BaseException literales')}
    ${metric('Candidatos a logging',a.logging_candidates,'Heurística por nombre de método')}${metric('Global / nonlocal',a.global_declarations,'Nombres declarados por ámbito')}</div>
    <p class="hint">Los candidatos a logging no confirman instrumentación. Un import desde un test no demuestra cobertura; cero coincidencias no demuestra ausencia de tests.</p>
    <h3>Cobertura de ejecución</h3>${c?`<div class="metric-grid">${metric('Líneas cubiertas',c.percent,`${c.lines_hit}/${c.lines_total} · %`)}${metric('Ramas cubiertas',c.branches_total?Math.round(100*c.branches_hit/c.branches_total):null,c.branches_total==null?'No medidas':`${c.branches_hit}/${c.branches_total}`)}</div><p class="hint">Informe importado · versión no verificada. Atribución por rango de líneas, incluyendo cuerpos anidados.</p>`:'<p>Sin informe importado para este componente. No equivale a 0 %.</p>'}
    <p class="hint">Estas medidas están disponibles antes de evaluar. El modelo interpreta la evidencia y asigna el color; las métricas no predicen por sí solas el rendimiento de un agente.</p>`;
}
function renderInspector(loadingCode=false) {
  const n=state.detail;if(!n)return;
  const assessment=n.assessment;
  $('inspector').innerHTML=`<div class="inspect-head"><div class="eyebrow"><span>${esc(n.kind.toUpperCase())}</span>${state.project.comparison?diffBadge(n):badge(n)}</div><h2>${esc(n.name)}</h2><div class="inspect-path">${esc(n.path)}:${n.line}–${n.end_line}</div></div><nav class="inspect-tabs"><button data-tab="overview" class="${state.tab==='overview'?'active':''}">Evaluación</button><button data-tab="code" class="${state.tab==='code'?'active':''}">Código</button><button data-tab="metrics" class="${state.tab==='metrics'?'active':''}">Métricas</button><button data-tab="agent" class="${state.tab==='agent'?'active':''}">✦ Consultar</button></nav><div class="inspect-body" id="inspect-body"></div>`;
  const panel=$('inspect-body');
  if(state.tab==='code') {
    if(loadingCode){panel.textContent='Leyendo código…';return;}
    panel.innerHTML=n.kind==='package'?'<p>Este paquete agrupa archivos. Abre un módulo para consultar su código.</p>':`<div class="code-preview-toolbar"><span>Python · solo lectura</span><button class="secondary small" data-action="expand-code">⛶ Ampliar código</button></div><div class="source-code" tabindex="0" role="region" aria-label="Código Python">${PythonHighlight.render(n.source||'',n.line)}</div>`;return;
  }
  if(state.tab==='metrics') {renderStaticMetrics(n,panel);return;}
  if(state.project.comparison){panel.innerHTML=diffBadge(n)+'<p>Comparación estática Git. Consulta las métricas o el código de esta revisión.</p><p class=hint>Impacto potencial significa relación por imports o llamadas, no un fallo demostrado. Los componentes eliminados muestran código y métricas de la revisión anterior. Contexto del consumidor permite explorar sus funciones sin afirmar que cada una esté afectada.</p>';return;}
  if(state.tab==='agent') {renderChat();return;}
  let html='';
  if(!assessment)html=`<div class="eval-empty"><div class="eyebrow">EVIDENCIA ANTES QUE COLOR</div><p>Este componente todavía no tiene evaluación. El modelo leerá su código, métricas y contexto para explicar qué facilita o dificulta modificarlo.</p><button class="primary" data-action="evaluate">✦ Evaluar componente</button></div>`;
  else {
    html=`${assessment.stale?'<div class="profile-warning">El código o la evidencia han cambiado. Reevalúa antes de utilizar este resultado.</div>':''}<div class="eyebrow">ESTIMACIÓN DEL MODELO · ${esc(assessment.provider)}</div><p class="assessment-summary">${esc(assessment.summary)}</p><p class="hint">${esc(assessment.model)} · ${date(assessment.at)} · ${fmt(assessment.duration_seconds)} s</p>`;
    if(assessment.provider!==profile.provider || (profile.model&&assessment.model!==profile.model))html+='<div class="profile-warning">Evaluación de otro perfil. Conservada para comparación; reevalúa para usar el perfil seleccionado.</div>';
    html+='<h3>Responsabilidad</h3><p>'+esc(assessment.responsibility)+'</p><h3>Condiciones para agentes</h3>'+assessment.dimensions.map(d=>`<div class="dimension"><div><b>${dimensions[d.key]}</b><span class="level ${d.level}">${levels[d.level]}</span></div><p>${esc(d.explanation)}</p></div>`).join('');
    html+='<h3>Hallazgos y evidencia</h3>'+assessment.findings.map(f=>`<div class="finding"><strong>${esc(f.title)}</strong><p>${esc(f.detail)}</p>${f.evidence_refs.map(ref=>`<button class="evidence-ref" data-action="context">${esc(ref)}</button>`).join('')}</div>`).join('');
    if(assessment.next_actions.length)html+='<h3>Próximas comprobaciones</h3><ul class="unknowns">'+assessment.next_actions.map(a=>`<li>${esc(a)}</li>`).join('')+'</ul>';
    if(assessment.unknowns.length)html+='<h3>Lo que aún no sabemos</h3><ul class="unknowns">'+assessment.unknowns.map(a=>`<li>${esc(a)}</li>`).join('')+'</ul>';
    html+='<div class="eval-actions"><button class="secondary" data-action="evaluate">↻ Reevaluar</button><button class="secondary" data-action="context">Ver contexto</button></div>';
  }
  if(state.busy.has(n.id))html+='<div class="busy-inline">✦ El modelo está evaluando este componente…</div>';
  html+='<h3>Contexto disponible</h3><button class="secondary context-button" data-action="context">▤ Inspeccionar el paquete enviado al modelo ↗</button>';
  if(n.docstring)html+='<h3>Contrato documentado</h3><div class="docstring">'+esc(n.docstring)+'</div>';
  const children=state.project.nodes.filter(x=>x.parent===n.id);
  if(children.length)html+='<h3>Componentes internos</h3>'+children.map(x=>`<button class="symbol-button" data-node="${esc(x.id)}">${x.kind==='class'?'C':'ƒ'} ${esc(x.name)}<small>L${x.line} →</small></button>`).join('');
  panel.innerHTML=html;
}
function renderChat(){const n=state.detail;const messages=state.conversations[state.project.id+'|'+n.id]||[];$('inspect-body').innerHTML=`<div class="eyebrow">CONVERSACIÓN SOBRE EL COMPONENTE</div><p class="hint">El modelo recibe el mismo paquete de evidencia. Cada pregunta es independiente e incorpora tu pregunta completa.</p><div class="question-chips"><button data-question="¿Qué contrato falta para modificar este componente con confianza?">Contratos pendientes</button><button data-question="Propón un ensayo reproducible para comprobar un cambio en este componente, sin ejecutarlo.">Diseñar un ensayo</button></div>${messages.map(m=>`<div class="chat-message ${m.role}"><span class="chat-label">${m.role==='user'?'TÚ':'MODELO · RESPUESTA ESTIMADA'}</span>${esc(m.text)}</div>`).join('')}<form class="chat-form" id="chat-form"><textarea id="chat-question" required placeholder="¿Qué comprobarías antes de cambiar esta responsabilidad?" aria-label="Pregunta sobre el componente"></textarea><button class="primary" ${state.busy.has(n.id)?'disabled':''}>${state.busy.has(n.id)?'Consultando…':'Preguntar al modelo →'}</button></form>`;}

async function runEvaluation(question='') {
  if(state.project?.comparison){toast('La vista diff es estática. Vuelve al proyecto actual para evaluar con el modelo.');return;}
  if(!modelsOn()){toast('La evaluación con modelos está desactivada en este servidor.');return;}
  if(!state.detail)return;
  const projectId=state.project.id,id=state.detail.id;
  if(state.busy.has(id)){toast('Este componente ya tiene una consulta en curso.');return;}
  state.busy.add(id);renderInspector();
  const conversationKey=projectId+'|'+id;
  if(question){(state.conversations[conversationKey]??=[]).push({role:'user',text:question});renderChat();}
  try {
    const response=await api(`/projects/${projectId}/evaluate`,{component_id:id,...profile,question,force:!question});
    const result=response.cached?{assessment:response.result}:await poll(response.job_id,'El modelo está contrastando código, contratos y evidencia…');
    if(question){state.conversations[conversationKey].push({role:'assistant',text:result.assessment.answer||result.assessment.summary});}
    if(state.project.id===projectId){await loadProject(projectId,true);if(question&&state.selected===id){state.tab='agent';renderInspector();}}
    toast(question?'Respuesta recibida.':'Evaluación guardada con sus evidencias.');
  } finally {state.busy.delete(id);if(state.project.id===projectId&&state.selected===id)renderInspector();}
}
async function showContext(){if(!state.detail)return;const ctx=await api(`/projects/${state.project.id}/context?id=${encodeURIComponent(state.detail.id)}`);$('context-code').textContent=JSON.stringify(ctx,null,2);$('context-dialog').showModal();}

async function evaluateMap() {
  if(state.project?.comparison)return;
  if(!modelsOn()){toast('La evaluación con modelos está desactivada en este servidor.');return;}
  if(!state.project){toast('Abre primero un proyecto.');return;}
  if(state.batch){toast('La evaluación del mapa ya está en curso.');return;}
  const projectId=state.project.id;
  const batchProfile={...profile};
  const ids=(state.visibleModules||[]).slice(0,12);
  state.batch=true;$('evaluate-map').disabled=true;
  try {
    for(let i=0;i<ids.length;i++) {
      const id=ids[i];state.busy.add(id);
      $('evaluate-map').textContent=`✦ ${i+1}/${ids.length}`;
      try {
        const response=await api(`/projects/${projectId}/evaluate`,{component_id:id,...batchProfile,force:false});
        if(!response.cached)await poll(response.job_id,`Evaluando módulo ${i+1} de ${ids.length}…`);
        if(state.project.id===projectId)await loadProject(projectId,true);
      } finally {state.busy.delete(id);}
    }
    toast(`${ids.length} módulos evaluados. Los colores proceden del modelo.`);
  } finally {state.batch=false;$('evaluate-map').disabled=!modelsOn();$('evaluate-map').textContent='✦ Evaluar mapa';renderInspector();}
}

function renderEvidence() {
  if(!state.project){$('evidence-content').innerHTML='<div class="empty-state">Abre un proyecto para importar evidencia.</div>';return;}
  const p=state.project, covered=p.nodes.filter(n=>n.kind==='module'&&n.coverage);
  let html=`<div class="evidence-card"><h3>Cobertura de ejecución</h3><p>Importa el JSON generado por coverage.py. Los datos se asocian por ruta; su revisión de origen no puede verificarse automáticamente.</p>${covered.length?'<table class="coverage-table"><thead><tr><th>MÓDULO</th><th>LÍNEAS</th><th>RAMAS</th></tr></thead><tbody>'+covered.map(n=>`<tr><td>${esc(n.name)}</td><td>${n.coverage.percent==null?'N/A':n.coverage.percent+' %'} · ${n.coverage.lines_hit}/${n.coverage.lines_total}</td><td>${n.coverage.branches_total==null?'No medidas':n.coverage.branches_hit+'/'+n.coverage.branches_total}</td></tr>`).join('')+'</tbody></table>':'<div class="empty-state">Sin informe de cobertura. No es lo mismo que 0 %.</div>'}</div>`;
  const runs=p.runs,accepted=runs.filter(r=>r.accepted).length;
  html+=`<div class="evidence-card"><h3>Ensayos registrados · ${runs.length}</h3><p>${accepted} aceptados / ${runs.length} intentados. Registros aportados por el usuario; perfiles y tareas pueden ser diferentes. No constituyen una tasa universal de éxito.</p></div>`;
  html+=runs.slice().reverse().map(r=>`<article class="evidence-card"><div class="row"><h3>${esc(r.task)}</h3><span class="pill ${r.accepted?'green':'orange'}">${r.accepted?'Aceptado':'No aceptado'}</span><span class="pill">Declarado por usuario</span>${r.fingerprint!==p.fingerprint?'<span class="pill yellow">Versión anterior</span>':''}</div><p>${esc(r.component_id)} · ${esc(r.profile)} · ${date(r.at)}</p><p>${r.attempts} intentos · ${r.regressions} regresiones · ${r.human_interventions} intervenciones · ${fmt(r.tokens)} tokens · ${fmt(r.seconds)} segundos</p><details><summary>Criterios y evidencia</summary><p>${esc(r.acceptance)}</p><pre>${esc(r.evidence)}</pre></details></article>`).join('');
  if(!runs.length)html+='<div class="empty-state"><h3>La experiencia también cuenta.</h3><p>Registra una tarea de cambio, sus criterios de aceptación y el resultado.<br>Las estimaciones del modelo permanecerán diferenciadas de estos ensayos.</p></div>';
  html+='<div class="evidence-card"><h3>Alcance del análisis</h3><ul class="unknowns">'+p.limitations.map(x=>`<li>${esc(x)}</li>`).join('')+'</ul>'+ (p.warnings.length?'<ul class="warning-list">'+p.warnings.map(x=>`<li>${esc(x)}</li>`).join('')+'</ul>':'')+`<p>${p.documents.length} documentos Markdown incluidos en el análisis; el paquete por componente utiliza como máximo ocho, con límites de longitud explícitos.</p></div>`;
  $('evidence-content').innerHTML=html;
}
function renderHistory(){if(!state.project)return;const p=state.project;const rows=[{at:p.created_at,title:'Proyecto analizado',detail:`${p.files.length} archivos · huella ${p.fingerprint.slice(0,12)}`},...p.nodes.filter(n=>n.assessment).map(n=>({at:n.assessment.at,title:`Evaluación: ${n.name}`,detail:`${n.assessment.provider} · ${n.assessment.model} · ${n.assessment.stale?'desactualizada':'predictiva'} · ${labels[n.assessment.color]}`})),...p.history.map(h=>({at:h.at,title:'Proyecto vuelto a analizar',detail:h.changed?'Cambios detectados. Evaluaciones anteriores marcadas como desactualizadas.':'Misma huella del código y la documentación.'}))].sort((a,b)=>b.at.localeCompare(a.at));$('history-content').innerHTML=rows.map(r=>`<div class="timeline-row"><span>◉</span><div><strong>${esc(r.title)}</strong><p>${esc(r.detail)}</p></div><time>${date(r.at)}</time></div>`).join('');}
function renderProfile(){ $('profile-label').innerHTML=modelsOn()?`${esc(profile.provider==='codex'?'Codex CLI':'Ollama')}<small>${esc(profile.model||'Modelo predeterminado')}</small>`:'Modelos desactivados<small>Solo análisis estático</small>'; }
function applyModelSwitch(){if(modelsOn())return;$('lazy-enabled').checked=false;$('lazy-enabled').disabled=true;$('evaluate-map').disabled=true;$('lazy-status').textContent='Modelos desactivados en este servidor · solo análisis estático';}
function providerInfo(){const local=$('provider').value==='ollama';$('endpoint-label').classList.toggle('hidden',!local);$('model').placeholder=local?'Nombre del modelo instalado':'Vacío = predeterminado del CLI';$('provider-info').textContent=local?'Ollama recibe el contexto en este ordenador. Usa un modelo instalado que admita salida JSON estructurada.':`Codex CLI ${state.config.codex_available?'detectado':'no detectado'}. Utiliza tu sesión de Codex; el código y los fragmentos de documentación del paquete se envían a su proveedor al pulsar Evaluar o Preguntar. El proceso trabaja en modo de solo lectura.`;}
function openSettings(){$('provider').value=profile.provider;$('model').value=profile.model;$('endpoint').value=profile.endpoint;providerInfo();$('settings-dialog').showModal();}
function openRun(){if(!state.project){toast('Abre primero un proyecto.');return;}$('run-component').innerHTML=state.project.nodes.map(n=>`<option value="${esc(n.id)}">${esc(n.qualified_name)}</option>`).join('');$('run-component').value=state.selected;$('run-profile').value=(profile.provider+' '+profile.model).trim();$('run-dialog').showModal();}

document.addEventListener('click',e=>{
  const close=e.target.closest('.close-dialog');if(close){close.closest('dialog').close();return;}
  const view=e.target.closest('[data-view]');if(view){showView(view.dataset.view);return;}
  const tab=e.target.closest('[data-tab]');if(tab){state.tab=tab.dataset.tab;if(state.tab==='code'&&state.detail?.source===undefined){selectNode(state.selected,true).catch(catchError);}else renderInspector();return;}
  const toggle=e.target.closest('[data-toggle]');if(toggle){const id=toggle.dataset.toggle;state.expanded.has(id)?state.expanded.delete(id):state.expanded.add(id);renderTree();return;}
  const frame=e.target.closest('[data-scope-node]');if(frame){state.tab='metrics';selectNode(frame.dataset.scopeNode,true).catch(catchError);return;}
  const node=e.target.closest('[data-node]');if(node){if(state.graphKind==='calls'&&node.closest('#graph'))state.tab='metrics';selectNode(node.dataset.node,!!node.closest('#graph')).catch(catchError);return;}
  const recent=e.target.closest('[data-project]');if(recent){$('open-dialog').close();loadProject(recent.dataset.project).catch(catchError);return;}
  const action=e.target.closest('[data-action]');if(action){if(action.dataset.action==='expand-code'){openCode();return;}(action.dataset.action==='evaluate'?runEvaluation():showContext()).catch(catchError);return;}
  const question=e.target.closest('[data-question]');if(question&&$('chat-question'))$('chat-question').value=question.dataset.question;
});
document.addEventListener('submit',e=>{if(e.target.id==='chat-form'){e.preventDefault();runEvaluation($('chat-question').value.trim()).catch(catchError);}});
bind('connect-form','submit',e=>{e.preventDefault();state.lazyFailures=new Set();return scan($('connect-path').value.trim(),$('connect-host').value.trim());});
bind('open-btn','click',openProjectDialog);bind('welcome-open','click',openProjectDialog);
bind('open-form','submit',e=>{e.preventDefault();return scan($('project-path').value.trim(),$('ssh-host').value.trim());});
bind('demo-btn','click',()=>scan(state.config.example_path));
bind('refresh-btn','click',()=>state.project?scan(state.project.root,state.project.origin?.kind==='ssh'?state.project.origin.host:''):openProjectDialog());
bind('search','input',e=>{state.page=0;state.search=e.target.value;renderTree();renderGraph(true);});
bind('package-scope','change',e=>{state.scope=e.target.value;state.level=state.scope?'package:'+state.scope:null;state.page=0;state.search='';$('search').value='';renderTree();renderGraph(true);});
bind('show-tests','change',()=>renderGraph(true));bind('show-external','change',()=>renderGraph(true));
bind('connection-mode','change',renderConnections);
bind('diff-only','change',e=>e.target.checked?applyDiff():leaveDiff());
bind('diff-refresh','click',applyDiff);bind('diff-refs','click',loadGitRefs);
bind('diff-impact','change',updateDiffFilter);
bind('diff-pr-load','click',loadPullRequests);bind('diff-pr-state','change',loadPullRequests);
bind('diff-pr','change',()=>{$('diff-pr-number').value='';describePR();if($('diff-only').checked)return applyDiff();});
bind('diff-pr-number','input',()=>{$('diff-pr').value='';describePR();});
async function syncDiffMode(){
  const mode=$('diff-mode').value,working=mode==='working',pr=mode==='pr';
  $('diff-head-field').classList.toggle('hidden',working||pr);$('diff-base-field').classList.toggle('hidden',pr);
  $('diff-pr-fields').classList.toggle('hidden',!pr);$('diff-refs').classList.toggle('hidden',pr);
  $('diff-base-label').textContent=mode==='branches'?'Rama destino':'Comparar con';
  if(working)$('diff-base').value='HEAD';
  else if($('diff-base').value==='HEAD')$('diff-base').value=(state.gitRefs||[]).find(r=>['main','origin/main','master','origin/master'].includes(r))||'';
  if(pr)await loadPullRequests();
}
bind('diff-mode','change',syncDiffMode);
// Deep link: /?project=<abs path>&pr=<n>&diff=1&impact=1 or &base=<ref>&rev=<ref>.
// The server validates every parameter (allowlisted roots); the UI then runs the normal flow.
async function openDeepLink(query){
  const link=await api('/deep-link'+query);
  if(link.project_id){try{await loadProject(link.project_id);}catch{link.project_id=null;}}
  if(!link.project_id)await scan(link.path);
  if(!link.mode)return;
  $('diff-mode').value=link.mode;
  await syncDiffMode();
  if(link.mode==='branches'){$('diff-base').value=link.base;$('diff-head').value=link.rev;}
  if(link.mode==='pr'){
    // Set after the PR list loads: loading the list clears the number field.
    const listed=(state.pullRequests||[]).some(p=>p.number===link.pr);
    $('diff-pr').value=listed?String(link.pr):'';$('diff-pr-number').value=listed?'':String(link.pr);describePR();
    if(!listed)$('diff-pr-info').textContent=`PR #${link.pr} (enlace directo). Se leerán sus commits sin modificar el repositorio.`;
  }
  $('diff-impact').checked=link.impact;
  if(link.diff)await applyDiff();
}
bind('code-smaller','click',()=>resizeCode(-1));bind('code-larger','click',()=>resizeCode(1));
bind('code-wrap','change',e=>$('code-expanded').classList.toggle('wrap-code',e.target.checked));
bind('evaluate-map','click',evaluateMap);
bind('zoom-in','click',()=>zoom(1.2));bind('zoom-out','click',()=>zoom(1/1.2));bind('fit-btn','click',fitGraph);
bind('settings-btn','click',openSettings);bind('profile-btn','click',openSettings);bind('provider','change',providerInfo);
bind('settings-form','submit',e=>{e.preventDefault();profile={provider:$('provider').value,model:$('model').value.trim(),endpoint:$('endpoint').value.trim()};localStorage.setItem('checker-profile',JSON.stringify(profile));renderProfile();renderInspector();$('settings-dialog').close();state.lazyFailures=new Set();scheduleLazy();toast('Perfil guardado. Las evaluaciones previas conservan su procedencia.');});
bind('rubric-btn','click',()=>$('rubric-dialog').showModal());
bind('export-btn','click',()=>{if(state.project)window.location.href=`/api/projects/${state.project.id}/export`;});
bind('copy-context','click',async()=>{await navigator.clipboard.writeText($('context-code').textContent);toast('Contexto copiado.');});
bind('coverage-btn','click',()=>{if(state.project)$('coverage-file').click();else toast('Abre primero un proyecto.');});
bind('coverage-file','change',async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>7_000_000)throw new Error('El informe supera 7 MB.');const result=await api(`/projects/${state.project.id}/coverage`,{report:JSON.parse(await file.text()),fingerprint:state.project.fingerprint});await loadProject(state.project.id,true);toast(`Cobertura importada para ${result.mapped} módulos; ${result.unmapped.length} rutas sin asociar.`);}finally{e.target.value='';}});
bind('run-btn','click',openRun);
bind('run-form','submit',async e=>{e.preventDefault();const value=id=>$(id).value;await api(`/projects/${state.project.id}/runs`,{component_id:value('run-component'),task:value('run-task'),profile:value('run-profile'),accepted:value('run-result')==='true',acceptance:value('run-acceptance'),evidence:value('run-evidence'),attempts:Number(value('run-attempts')),regressions:Number(value('run-regressions')),human_interventions:Number(value('run-human')),tokens:value('run-tokens')===''?null:Number(value('run-tokens')),seconds:value('run-seconds')===''?null:Number(value('run-seconds'))});$('run-dialog').close();$('run-form').reset();await loadProject(state.project.id,true);showView('evidence');toast('Ensayo guardado con procedencia declarada.');});
$('graph').addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.dataset.node)selectNode(e.target.dataset.node).catch(catchError);});
$('graph').addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)&&e.target.dataset.scopeNode){e.preventDefault();state.tab='metrics';selectNode(e.target.dataset.scopeNode,true).catch(catchError);}});
$('graph-wrap').addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY<0?1.08:1/1.08);},{passive:false});
let drag=null;
$('graph').addEventListener('pointerdown',e=>{if(e.target.closest('[data-node],[data-scope-node]'))return;drag={x:e.clientX,y:e.clientY,gx:state.graph.x,gy:state.graph.y};$('graph').setPointerCapture(e.pointerId);});
$('graph').addEventListener('pointermove',e=>{if(!drag)return;const rect=$('graph').getBoundingClientRect();state.graph.x=drag.gx+(e.clientX-drag.x)*900/rect.width;state.graph.y=drag.gy+(e.clientY-drag.y)*600/rect.height;transformGraph();});
$('graph').addEventListener('pointerup',()=>drag=null);
$('graph').addEventListener('pointercancel',()=>drag=null);
(async()=>{state.config=await api('/config');renderProfile();applyModelSwitch();if(location.search.length>1){await openDeepLink(location.search);return;}const saved=localStorage.getItem('checker-project');if(saved){try{await loadProject(saved);}catch{localStorage.removeItem('checker-project');}}})().catch(catchError);
setInterval(async()=>{
  if(!state.project||$('diff-only').checked||state.busy.size||state.batch||state.refreshing)return;
  const projectId=state.project.id;
  try{
    state.refreshing=true;
    const fresh=await api(`/projects/${projectId}/freshness`);
    if(fresh.changed&&state.project.id===projectId){
      const {job_id}=await api('/scan',{path:state.project.root,ssh_host:state.project.origin?.kind==='ssh'?state.project.origin.host:''});
      const result=await poll(job_id,'Cambios detectados. Actualizando el mapa…');
      if(state.project.id===projectId&&!$('diff-only').checked)await loadProject(result.project_id,true);
    }
  }catch(error){status('No se pudo actualizar el proyecto: '+error.message,true);}
  finally{state.refreshing=false;}
},20000);
