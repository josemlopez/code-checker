const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../web/app.js'), 'utf8');
const extract = (start, end) => source.slice(source.indexOf(start), source.indexOf(end));

// Run the real selection, diff-exit and inspector functions with a small DOM
// adapter. Replacing the inspector removes its children, just as in a browser.
function setup() {
  const elements = new Map();
  function element(id) {
    const el = {textContent:'', classList:{add(){},remove(){}}, disabled:false};
    let html = '';
    Object.defineProperty(el, 'innerHTML', {
      get:()=>html,
      set(value) {
        html=value;
        if(id==='inspector') {
          elements.delete('inspect-body');
          if(value.includes('id="inspect-body"'))element('inspect-body');
        }
      }
    });
    elements.set(id,el);return el;
  }
  for(const id of ['inspector','diff-refresh','diff-summary','diff-files','evaluate-map','export-btn','coverage-btn','run-btn','origin-note'])element(id);
  const node = {id:'app.py',kind:'module',name:'app',path:'app.py',line:1,end_line:2};
  const project = {id:'live',origin:{kind:'ssh'},nodes:[node]};
  const state = {project:{...project,comparison:{}},fullProject:project,tab:'code',diffJobId:'old-diff'};
  const pending = [];
  const context = {
    state, $:id=>elements.get(id)||null, esc:String, badge:()=>'', diffBadge:()=>'',
    PythonHighlight:{render:s=>s},
    api:path=>new Promise(resolve=>pending.push({path,resolve})),
    renderTree(){},renderGraph(){},renderConnections(){},renderScopes(){},renderStats(){},scheduleLazy(){}
  };
  vm.createContext(context);
  vm.runInContext([
    extract('function leaveDiff()', 'function badge('),
    extract('async function selectNode(', 'function metric('),
    extract('function renderInspector(', 'function renderChat(')
  ].join('\n'),context);
  return {context,state,elements,pending,node};
}

test('Code selection rebuilds the inspector after leaving a diff, including refresh reselection', async()=>{
  const {context,state,elements,pending,node}=setup();
  context.leaveDiff();
  assert.equal(state.tab,'code');
  assert.equal(elements.has('inspect-body'),false);
  const selection=context.selectNode(node.id);
  assert.equal(elements.get('inspect-body')?.textContent,'Leyendo código…');
  assert.match(elements.get('inspector').innerHTML,/<h2>app<\/h2>/);
  assert.equal(pending[0].path,'/projects/live/component?id=app.py');
  pending[0].resolve({...node,source:'print(1)'});
  await selection;
  assert.match(elements.get('inspect-body').innerHTML,/print\(1\)/);
  const refresh=context.selectNode(node.id);
  assert.equal(elements.get('inspect-body').textContent,'Leyendo código…');
  pending[1].resolve({...node,source:'print(2)'});
  await refresh;
  assert.match(elements.get('inspect-body').innerHTML,/print\(2\)/);
});

test('An old code response cannot replace the placeholder after leaving a diff', async()=>{
  const {context,elements,pending,node}=setup();
  const selection=context.selectNode(node.id);
  context.leaveDiff();
  pending[0].resolve({...node,source:'old revision'});
  await selection;
  assert.equal(elements.has('inspect-body'),false);
  assert.match(elements.get('inspector').innerHTML,/Proyecto completo/);
});
