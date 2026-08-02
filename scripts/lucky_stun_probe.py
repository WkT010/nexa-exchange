#!/usr/bin/env python3
"""Probe Lucky STUN API structure:
1. Force fresh login → token
2. GET all plausible STUN endpoints
3. Read frontend JS to discover STUN form fields and API paths
4. Print findings (read-only, no mutations yet)
"""
import json
import time
import os
import sys
import re
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_lucky_setup import SimpleWS, cdp_call, get_pages


def eval_js(ws, expr, timeout=180):
    r = cdp_call(ws, "Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True}, timeout=timeout)
    if not r:
        return None
    res = r.get("result") or {}
    if res.get("exceptionDetails"):
        return {"__error__": str(res.get("exceptionDetails"))[:2000]}
    rv = res.get("result") or {}
    if rv.get("type") == "undefined":
        return None
    return rv.get("value")


def main():
    pages = get_pages(9333)
    lucky_page = [p for p in pages if (p.get("type") or "page") == "page" and "localhost:16601" in (p.get("url") or "")][0]
    ws = SimpleWS(lucky_page["webSocketDebuggerUrl"])

    expr = r"""
(async () => {
    // --- 1. Force fresh login ---
    location.hash = '#/login';
    await new Promise(r=>setTimeout(r, 2200));
    const s1 = Date.now();
    let ai=null, pi=null, btn=null;
    while (Date.now()-s1 < 8000) {
        const inputs = Array.from(document.querySelectorAll('input'));
        ai = inputs.find(i => (i.placeholder||'').includes('666') && i.type==='text');
        pi = inputs.find(i => (i.placeholder||'').includes('666') && i.type==='password');
        const bs = Array.from(document.querySelectorAll('button'));
        btn = bs.find(b => /登|Login|Submit/.test(b.textContent||''));
        if (ai && pi && btn) break;
        await new Promise(r=>setTimeout(r, 250));
    }
    if (ai && pi && btn) {
        const setV = (el,v) => {
            const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
            s.call(el,v); el.dispatchEvent(new Event('input',{bubbles:true}));
            el.dispatchEvent(new Event('change',{bubbles:true}));
        };
        setV(ai,'666'); setV(pi,'666');
        await new Promise(r=>setTimeout(r,400));
        btn.click();
        const s2 = Date.now();
        while (Date.now()-s2 < 6000) { if (location.hash!=='#/login') break; await new Promise(r=>setTimeout(r,200)); }
    }
    const lucky = JSON.parse(localStorage.getItem('lucky') || '{}');
    const TOKEN = lucky.token || null;
    if (!TOKEN) return {error:'no token after login'};

    const hdrs = {'Accept':'application/json, text/plain, */*','Lucky-Admin-Token': TOKEN};
    const GET = async (p) => {
        try {
            const r = await fetch('/api/'+p+'?_='+Date.now(), {credentials:'include', headers:hdrs});
            const t = await r.text();
            let j=null; try{j=JSON.parse(t);}catch(e){}
            return {status:r.status, json:j, text:t.slice(0,1500)};
        } catch(e) { return {error:String(e).slice(0,300)}; }
    };

    // --- 2. Probe STUN GET endpoints ---
    const stunPaths = [
        'stun/rules','stun/rule','stun/clients','stun/client','stun/status','stun',
        'stun/list','stun/info','stun/config','stun/server','stun/servers',
        'stun/task','stun/tasks',
        'stun/listenaddr','stun/domains',
    ];
    const gets = {};
    for (const p of stunPaths) {
        const r = await GET(p);
        if (r.status === 404) continue;
        gets[p] = r;
    }

    // --- 3. Read index JS to find STUN chunk filenames ---
    let stunChunks = [];
    try {
        const idx = await (await fetch('/static/js/lucky_index-DyslG9Ot.js', {credentials:'include'})).text();
        // find any js file with stun in name
        stunChunks = [...new Set(idx.match(/lucky_[A-Za-z0-9_-]*[Ss]tun[A-Za-z0-9_-]*\.js/g) || [])];
        if (!stunChunks.length) {
            stunChunks = [...new Set(idx.match(/lucky_[A-Za-z0-9_-]*\.js/g) || [])].filter(n => /stun/i.test(n));
        }
        // also find all chunk filenames to inspect
        const allChunks = [...new Set(idx.match(/lucky_[A-Za-z0-9_-]+\.js/g) || [])];
        gets.__all_chunks__ = allChunks.slice(0, 60);
    } catch(e) { gets.__idx_error__ = String(e); }

    // --- 4. Read each STUN chunk JS, extract field names & API paths ---
    const chunkAnalysis = {};
    for (const fn of stunChunks) {
        try {
            const txt = await (await fetch('/static/js/' + fn, {credentials:'include'})).text();
            // extract api paths
            const apiPaths = [...new Set(txt.match(/['"`](\/?api\/[a-zA-Z0-9_\/-]+)['"`]/g) || [])].map(s=>s.replace(/['"`]/g,''));
            // extract identifier-looking strings with stun/rule/client/domain/addr/port keywords
            const ids = [...new Set(txt.match(/['"`]([A-Za-z_][A-Za-z0-9_]{1,40})['"`]/g) || [])]
                .map(s=>s.replace(/['"`]/g,''))
                .filter(s => /stun|rule|client|domain|addr|port|server|listen|forward|tunnel| penetrat|subdomain|host/i.test(s));
            chunkAnalysis[fn] = {len: txt.length, apiPaths: apiPaths.slice(0,30), fields: ids.slice(0,80)};
        } catch(e) { chunkAnalysis[fn] = {error: String(e)}; }
    }
    gets.__stun_chunk_analysis__ = chunkAnalysis;
    gets.__stun_chunks__ = stunChunks;

    return {token_prefix: TOKEN.slice(0,24)+'...', hash: location.hash, data: gets};
})()
"""
    data = eval_js(ws, expr, timeout=300)
    ws.close()

    if not data:
        print("[x] empty result")
        return 1
    if isinstance(data, dict) and data.get("__error__"):
        print(f"[x] {data['__error__']}")
        return 2
    if isinstance(data, dict) and data.get("error"):
        print(f"[x] {data}")
        return 3

    print(f"hash={data.get('hash')}  token={data.get('token_prefix')}")
    d = data.get("data") or {}

    print("\n" + "="*70)
    print("  STUN API PROBE RESULTS")
    print("="*70)

    # Print GET results
    for k, v in d.items():
        if k.startswith("__"):
            continue
        if isinstance(v, dict):
            st = v.get("status")
            j = v.get("json")
            ret = j.get("ret") if isinstance(j, dict) else None
            msg = j.get("msg") if isinstance(j, dict) else None
            print(f"\n[GET /api/{k}] status={st} ret={ret} msg={msg}")
            if isinstance(j, dict) and j.get("data") is not None:
                s = json.dumps(j.get("data"), ensure_ascii=False)
                print(f"  data: {s[:600]}")
            elif v.get("text") and st != 404:
                print(f"  text: {v['text'][:300]}")
        else:
            print(f"\n[GET /api/{k}] {v}")

    # Print chunk analysis
    chunks = d.get("__stun_chunks__") or []
    print(f"\n--- STUN JS chunks found: {chunks} ---")
    all_chunks = d.get("__all_chunks__") or []
    print(f"--- All chunks (first 60): {all_chunks} ---")

    ca = d.get("__stun_chunk_analysis__") or {}
    for fn, info in ca.items():
        print(f"\n=== {fn} ===")
        if isinstance(info, dict) and info.get("error"):
            print(f"  error: {info['error']}")
            continue
        print(f"  length: {info.get('len')}")
        print(f"  apiPaths: {info.get('apiPaths')}")
        print(f"  fields: {info.get('fields')}")

    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
