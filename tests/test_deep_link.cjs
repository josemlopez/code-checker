const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../web/app.js'), 'utf8');
const extract = (start, end) => source.slice(source.indexOf(start), source.indexOf(end));

// Run the real deep-link opener with the app flow (load/scan, mode, PR list, diff) stubbed.
function setup(link, {knownFails=false, listed=[]}={}) {
  const elements = new Map();
  for (const id of ['diff-mode','diff-base','diff-head','diff-pr','diff-pr-number','diff-pr-info','diff-impact'])
    elements.set(id, {value:'', checked:false, textContent:''});
  elements.get('diff-mode').value='working';
  const calls = [];
  const state = {};
  const context = {
    state, $:id=>elements.get(id), String, Number,
    api:async path=>{calls.push(['api',path]);return structuredClone(link);},
    loadProject:async id=>{calls.push(['load',id]);if(knownFails)throw new Error('gone');},
    scan:async path=>{calls.push(['scan',path]);},
    syncDiffMode:async()=>{
      calls.push(['mode',elements.get('diff-mode').value]);
      // Mirrors the real list load, which clears the number field and may reset base.
      if(elements.get('diff-mode').value==='pr'){state.pullRequests=listed.map(number=>({number}));elements.get('diff-pr-number').value='';}
      else elements.get('diff-base').value='main';
    },
    describePR(){},
    applyDiff:async()=>{calls.push(['diff',{pr:elements.get('diff-pr-number').value||elements.get('diff-pr').value,impact:elements.get('diff-impact').checked,base:elements.get('diff-base').value,head:elements.get('diff-head').value}]);},
  };
  vm.createContext(context);
  vm.runInContext(extract('async function openDeepLink(', "bind('code-smaller'"), context);
  return {context, calls, elements};
}

const pr = {path:'/srv/repo', project_id:null, mode:'pr', pr:465, base:null, rev:null, diff:true, impact:true};

test('A PR deep link scans an unknown project and opens the diff with impact, no clicks', async()=>{
  const {context, calls} = setup(pr);
  await context.openDeepLink('?project=/srv/repo&pr=465&diff=1&impact=1');
  assert.deepEqual(calls, [
    ['api','/deep-link?project=/srv/repo&pr=465&diff=1&impact=1'], ['scan','/srv/repo'], ['mode','pr'],
    ['diff',{pr:'465',impact:true,base:'',head:''}],
  ]);
});

test('A known project is reused, a listed PR is selected in the dropdown', async()=>{
  const {context, calls, elements} = setup({...pr, project_id:'0123456789abcdef', impact:false}, {listed:[465]});
  await context.openDeepLink('?q');
  assert.deepEqual(calls.map(c=>c[0]), ['api','load','mode','diff']);
  assert.equal(elements.get('diff-pr').value, '465');
  assert.equal(elements.get('diff-pr-number').value, '');
  assert.equal(calls[3][1].impact, false);
});

test('A stale stored index falls back to a scan', async()=>{
  const {context, calls} = setup({...pr, project_id:'0123456789abcdef'}, {knownFails:true});
  await context.openDeepLink('?q');
  assert.deepEqual(calls.map(c=>c[0]), ['api','load','scan','mode','diff']);
});

test('A branch link keeps base and rev after the mode switch', async()=>{
  const {context, calls} = setup({...pr, mode:'branches', pr:null, base:'release', rev:'feature'});
  await context.openDeepLink('?q');
  assert.deepEqual(calls.at(-1), ['diff',{pr:'',impact:true,base:'release',head:'feature'}]);
});

test('diff=0 prepares the comparison without computing it; no comparison opens the project only', async()=>{
  let {context, calls, elements} = setup({...pr, diff:false});
  await context.openDeepLink('?q');
  assert.deepEqual(calls.map(c=>c[0]), ['api','scan','mode']);
  assert.equal(elements.get('diff-pr-number').value, '465');
  ({context, calls} = setup({...pr, mode:null, pr:null, diff:false, impact:false}));
  await context.openDeepLink('?q');
  assert.deepEqual(calls.map(c=>c[0]), ['api','scan']);
});
