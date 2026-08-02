#!/usr/bin/env python3
"""Configure Lucky STUN penetration to obtain a fixed domain for ANAME record.

Steps:
1. Ensure logged in (token from localStorage)
2. GET /api/stun/configure -> check STUN global config (enable, server, etc.)
3. GET /api/stunrulelist -> check existing STUN rules
4. If STUN not enabled -> PUT /api/stun/configure to enable
5. Create STUN rule for local reverse proxy port 8081 (POST /api/stunrule)
6. Poll status -> extract assigned STUN domain (ANAME target)
7. Print the ANAME record to set for canival.fyi
"""
import json
import time
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


# Big JS payload: login check + all STUN API calls
JS = r"""
(async () => {
    let TOKEN = null;
    try { TOKEN = JSON.parse(localStorage.getItem('lucky') || '{}').token || null; } catch(e){}
    if (!TOKEN) {
        // try to login
        location.hash = '#/login';
        await new Promise(r=>setTimeout(r,2000));
        const inputs = Array.from(document.querySelectorAll('input'));
        const ai = inputs.find(i => (i.placeholder||'').includes('666') && i.type==='text');
        const pi = inputs.find(i => (i.placeholder||'').includes('666') && i.type==='password');
        const btn = Array.from(document.querySelectorAll('button')).find(b => /登|Login/.test(b.textContent||''));
        if (ai && pi && btn) {
            const setV=(el,v)=>{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}));};
            setV(ai,'666'); setV(pi,'666');
            await new Promise(r=>setTimeout(r,300));
            btn.click();
            await new Promise(r=>setTimeout(r,3000));
            TOKEN = JSON.parse(localStorage.getItem('lucky')||'{}').token || null;
        }
    }
    if (!TOKEN) return {error:'no token'};

    const hdrs = {'Accept':'application/json, text/plain, */*','Lucky-Admin-Token': TOKEN};
    const GET = async (p) => {
        const r = await fetch('/api/'+p+'?_='+Date.now(), {credentials:'include', headers:hdrs});
        const t = await r.text();
        let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,2000)};
    };
    const POST = async (p, body) => {
        const r = await fetch('/api/'+p, {method:'POST', credentials:'include',
            headers:{...hdrs,'Content-Type':'application/json'}, body: JSON.stringify(body)});
        const t = await r.text();
        let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,2000)};
    };
    const PUT = async (p, body) => {
        const r = await fetch('/api/'+p, {method:'PUT', credentials:'include',
            headers:{...hdrs,'Content-Type':'application/json'}, body: JSON.stringify(body)});
        const t = await r.text();
        let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,2000)};
    };

    const out = {token_prefix: TOKEN.slice(0,20)+'...'};

    // 1. STUN global config
    out.stun_configure = await GET('stun/configure');

    // 2. STUN rule list (full + lite)
    out.stunrulelist = await GET('stunrulelist');
    out.stunrulelist_lite = await GET('stunrulelist_lite');

    return out;
})()
"""


def stage1(ws):
    print("[Stage 1] Login + read STUN config & existing rules")
    r = eval_js(ws, JS, timeout=120)
    if not r:
        print("[x] empty"); return None
    if isinstance(r, dict) and (r.get("error") or r.get("__error__")):
        print(f"[x] {r}"); return None
    print(json.dumps(r, indent=2, ensure_ascii=False)[:3000])
    return r


def stage2(ws, stage1_data):
    """Enable STUN if needed and create a STUN rule for port 8081."""
    print("\n[Stage 2] Enable STUN + create STUN rule for port 8081")
    expr = r"""
(async () => {
    let TOKEN = JSON.parse(localStorage.getItem('lucky')||'{}').token || null;
    if (!TOKEN) return {error:'no token'};
    const hdrs = {'Accept':'application/json, text/plain, */*','Lucky-Admin-Token': TOKEN,
                  'Content-Type':'application/json'};
    const GET = async (p) => {
        const r = await fetch('/api/'+p+'?_='+Date.now(), {credentials:'include', headers:hdrs});
        const t = await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,2000)};
    };
    const PUT = async (p, body) => {
        const r = await fetch('/api/'+p, {method:'PUT', credentials:'include',
            headers:hdrs, body: JSON.stringify(body)});
        const t = await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,2000)};
    };
    const POST = async (p, body) => {
        const r = await fetch('/api/'+p, {method:'POST', credentials:'include',
            headers:hdrs, body: JSON.stringify(body)});
        const t = await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,2000)};
    };
    const out = {};

    // 1. Read current STUN configure
    const conf = await GET('stun/configure');
    out.before_configure = conf;
    const cur = (conf.json && conf.json.data) || {};

    // Enable STUN if not enabled. Common field names: Enable, StunEnable, enable
    // Build the merged config based on what we got back
    let enableBody = Object.assign({}, cur);
    let needEnable = false;
    if (cur.Enable === false) { enableBody.Enable = true; needEnable = true; }
    if (cur.StunEnable === false) { enableBody.StunEnable = true; needEnable = true; }
    if (cur.enable === false) { enableBody.enable = true; needEnable = true; }

    if (needEnable) {
        out.enable_result = await PUT('stun/configure', enableBody);
        await new Promise(r=>setTimeout(r,1500));
        out.after_configure = await GET('stun/configure');
    } else {
        out.enable_skipped = 'already enabled or unknown field';
        // Try a minimal enable PUT in case fields are missing
        const tryBody = Object.assign({Enable:true, StunEnable:true}, cur, {Enable:true, StunEnable:true});
        out.force_enable_result = await PUT('stun/configure', tryBody);
        await new Promise(r=>setTimeout(r,1500));
        out.after_force_configure = await GET('stun/configure');
    }

    return out;
})()
"""
    r = eval_js(ws, expr, timeout=120)
    print(json.dumps(r, indent=2, ensure_ascii=False)[:3000] if r else "[x] empty")
    return r


def stage3(ws):
    """Inspect existing STUN rule detail to learn the schema, then create a rule."""
    print("\n[Stage 3] Inspect STUN rule schema + create rule for port 8081")
    expr = r"""
(async () => {
    let TOKEN = JSON.parse(localStorage.getItem('lucky')||'{}').token || null;
    if (!TOKEN) return {error:'no token'};
    const hdrs = {'Accept':'application/json, text/plain, */*','Lucky-Admin-Token': TOKEN,
                  'Content-Type':'application/json'};
    const GET = async (p) => {
        const r = await fetch('/api/'+p+'?_='+Date.now(), {credentials:'include', headers:hdrs});
        const t = await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,2500)};
    };
    const POST = async (p, body) => {
        const r = await fetch('/api/'+p, {method:'POST', credentials:'include',
            headers:hdrs, body: JSON.stringify(body)});
        const t = await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,2500)};
    };
    const out = {};

    // 1. Check if a STUN rule for port 8081 already exists
    const list = await GET('stunrulelist');
    out.rulelist = list;
    const rules = (list.json && list.json.ruleList) || (list.json && list.json.data && list.json.data.ruleList) || [];
    let existing = null;
    for (const r of rules) {
        if (r.ListenPort === 8081 || r.LocalPort === 8081 || r.Port === 8081) existing = r;
    }
    if (existing) { out.existing_rule = existing; return out; }

    // 2. Try multiple rule body variants to discover the schema
    // Variant A: based on reverse-proxy-like fields
    const bodyA = {
        RuleName: "NEXA-STUN",
        Enable: true,
        Network: "tcp4",
        ListenIP: "127.0.0.1",
        ListenPort: 8081,
        Comment: "NEXA ANAME tunnel",
    };
    out.create_A = await POST('stunrule', bodyA);

    // Variant B
    const bodyB = {
        name: "NEXA-STUN",
        enable: true,
        localAddr: "127.0.0.1",
        localPort: 8081,
        protocol: "tcp",
    };
    out.create_B = await POST('stunrule', bodyB);

    // Variant C - empty body to trigger validation errors that reveal required fields
    out.create_empty = await POST('stunrule', {});

    return out;
})()
"""
    r = eval_js(ws, expr, timeout=120)
    print(json.dumps(r, indent=2, ensure_ascii=False)[:4000] if r else "[x] empty")
    return r


def main():
    pages = get_pages(9333)
    lucky_page = [p for p in pages if (p.get("type") or "page") == "page" and "localhost:16601" in (p.get("url") or "")][0]
    ws = SimpleWS(lucky_page["webSocketDebuggerUrl"])
    print(f"[+] Using page: {lucky_page.get('url')}")

    s1 = stage1(ws)
    s2 = stage2(ws, s1)
    s3 = stage3(ws)

    ws.close()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
