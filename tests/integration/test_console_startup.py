"""Exercise script ordering with separate script tags, like a browser."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_dashboard_bootstraps_storage_and_session_checks():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for dashboard execution checks")
    root = Path(__file__).resolve().parents[2]
    script = r"""
const vm = require('node:vm'), fs = require('node:fs'), assert = require('node:assert/strict');
const listeners = {}, calls = [], intervals = [], elements = new Map();
function element(key) {
  if (!elements.has(key)) elements.set(key, {
    value:'', innerHTML:'', textContent:'', className:'',
    classList:{contains:()=>false,add(){},remove(){},toggle(){}},
    addEventListener(){}, dataset:{}, querySelector:()=>null
  });
  return elements.get(key);
}
const sandbox = {
  console, structuredClone, AbortController,
  MutationObserver:class {observe(){}},
  document: {
    querySelector:element, querySelectorAll:()=>[],
    addEventListener(type, fn){(listeners[type] ??= []).push(fn)}
  },
  localStorage:{getItem:()=>null,setItem(){}},
  setTimeout:()=>1, clearTimeout(){}, setInterval(fn){intervals.push(fn)},
  fetch:async(url, options={})=>{
    calls.push([url,options.method||'GET']);
    return {ok:true,json:async()=>({data:url.endsWith('/session')?{status:'connected'}:{state:null}})};
  }
};
sandbox.window=sandbox;
vm.createContext(sandbox);
const html=fs.readFileSync('apps/web-console/src/index.html','utf8');
for(const match of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) vm.runInContext(match[1],sandbox);
(async()=>{
  for(const fn of listeners.DOMContentLoaded||[]) await fn();
  assert(calls.some(([url])=>url.endsWith('/health/live')));
  assert(calls.some(([url,method])=>url.endsWith('/internal/console/state')&&method==='GET'));
  assert(calls.some(([url,method])=>url.endsWith('/internal/console/state')&&method==='PUT'));
  assert(calls.some(([url])=>url.endsWith('/session')));
  assert.equal(intervals.length,2);
  assert.equal(vm.runInContext('state.accounts[0].status',sandbox),'connected');
  assert.equal(vm.runInContext("migrate({...seed,accounts:[{...XHS_ACCOUNT,name:'已修改名称'}]}).accounts[0].name",sandbox),'已修改名称');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run([node, "-e", script], cwd=root, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
