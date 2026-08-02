#!/usr/bin/env python3
"""Probe Lucky DDNS module fully + fix STUN module enable.
DDNS is what provides a fixed hostname (ANAME target) that tracks dynamic public IP.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_lucky_setup import SimpleWS, cdp_call, get_pages


def eval_js(ws, expr, timeout=180):
    r = cdp_call(ws, "Runtime.evaluate",
                 {"expression": expr, "returnByValue": True, "awaitPromise": True},
                 timeout=timeout)
    if not r:
        return None
    res = r.get("result") or {}
    if res.get("exceptionDetails"):
        return {"__error__": str(res.get("exceptionDetails"))[:3000]}
    rv = res.get("result") or {}
    if rv.get("type") == "undefined":
        return None
    return rv.get("value")


JS = r"""
(async () => {
    let TOKEN = JSON.parse(localStorage.getItem('lucky')||'{}').token || null;
    if (!TOKEN) return {error:'no token'};
    const hdrs = {'Accept':'application/json, text/plain, */*','Lucky-Admin-Token': TOKEN,
                  'Content-Type':'application/json'};
    const GET = async (p) => {
        const r = await fetch('/api/'+p+'?_='+Date.now(), {credentials:'include', headers:hdrs});
        const t = await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,4000)};
    };
    const PUT = async (p, body) => {
        const r = await fetch('/api/'+p, {method:'PUT', credentials:'include',
            headers:hdrs, body: JSON.stringify(body)});
        const t = await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,4000)};
    };
    const POST = async (p, body) => {
        const r = await fetch('/api/'+p, {method:'POST', credentials:'include',
            headers:hdrs, body: JSON.stringify(body)});
        const t = await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,4000)};
    };
    const out = {};

    // ===== A. Fix STUN module: re-enable EnableModule =====
    const stunConf = await GET('stun/configure');
    out.stun_configure_before = stunConf;
    const sc = (stunConf.json && stunConf.json.configure) || {};
    // Re-PUT with EnableModule:true to be safe
    const stunBody = Object.assign({}, sc, {EnableModule: true});
    out.stun_enable_put = await PUT('stun/configure', stunBody);
    await new Promise(r=>setTimeout(r,1500));
    out.stun_configure_after = await GET('stun/configure');

    // ===== B. DDNS module: full probe =====
    // 1. DDNS configure
    out.ddns_configure = await GET('ddns/configure');

    // 2. DDNS rule list - try multiple endpoints
    const ddnsListPaths = ['ddns/rules','ddns/rule','ddns/list','ddns/rules_lite',
        'ddnsrulelist','ddnsrulelist_lite','ddnsrule','ddns/ruleslist','ddns/tasklist'];
    out.ddns_list_probe = {};
    for (const p of ddnsListPaths) {
        const r = await GET(p);
        if (r.status === 404) continue;
        out.ddns_list_probe[p] = {status:r.status, ret:r.json?.ret, msg:r.json?.msg,
            data_preview: JSON.stringify(r.json||r.text).slice(0,600)};
    }

    // 3. Read DDNS JS chunk to discover API paths + form fields
    try {
        const idx = await (await fetch('/static/js/lucky_index-DyslG9Ot.js', {credentials:'include'})).text();
        // find ddns chunk
        let ddnsChunks = [...new Set(idx.match(/lucky_[A-Za-z0-9_-]*[Dd]dns[A-Za-z0-9_-]*\.js/g) || [])];
        if (!ddnsChunks.length) {
            ddnsChunks = [...new Set(idx.match(/lucky_[A-Za-z0-9_-]*\.js/g) || [])].filter(n => /ddns/i.test(n));
        }
        out.ddns_chunks = ddnsChunks;
        out.ddns_js = {};
        for (const fn of ddnsChunks) {
            const txt = await (await fetch('/static/js/'+fn, {credentials:'include'})).text();
            const apiPaths = [...new Set(txt.match(/['"`](\/?api\/[a-zA-Z0-9_\/-]+)['"`]/g) || [])].map(s=>s.replace(/['"`]/g,''));
            const fields = [...new Set(txt.match(/['"`]([A-Za-z_][A-Za-z0-9_]{1,40})['"`]/g) || [])]
                .map(s=>s.replace(/['"`]/g,''))
                .filter(s => /ddns|domain|host|record|provider|token|secret|api|key|type|name|enable|cloud|aliyun|tencent|cloudflare|godaddy|dnspod|namesilo|reg/i.test(s));
            out.ddns_js[fn] = {len: txt.length, apiPaths, fields: fields.slice(0,80)};
        }
    } catch(e) { out.idx_error = String(e); }

    return out;
})()
"""


def main():
    pages = get_pages(9333)
    lucky_page = [p for p in pages if (p.get("type") or "page") == "page" and "localhost:16601" in (p.get("url") or "")][0]
    ws = SimpleWS(lucky_page["webSocketDebuggerUrl"])
    print(f"[+] Using page: {lucky_page.get('url')}")
    r = eval_js(ws, JS, timeout=200)
    ws.close()
    if not r:
        print("[x] empty"); return 1
    print(json.dumps(r, indent=2, ensure_ascii=False)[:8000])
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
