#!/usr/bin/env python3
"""Final Lucky config reporter:
  - Force fresh login → new token
  - Dump full webservice rule (reverse proxy) details
  - Dump STUN / DDNS rules
  - Print summary for ANAME/STUN setup guidance
"""
import json
import time
import os
import sys
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
    // --- 1. Force fresh login to get a valid token -----------------------
    location.hash = '#/login';
    await new Promise(r=>setTimeout(r, 2500));
    let ai = null, pi = null, btn = null;
    const s1 = Date.now();
    while (Date.now()-s1 < 9000) {
        const inputs = Array.from(document.querySelectorAll('input'));
        ai = inputs.find(i => (i.placeholder||'').includes('666') && i.type==='text');
        pi = inputs.find(i => (i.placeholder||'').includes('666') && i.type==='password');
        const bs = Array.from(document.querySelectorAll('button'));
        btn = bs.find(b => /登|Login|Submit/.test(b.textContent||''));
        if (ai && pi && btn) break;
        await new Promise(r=>setTimeout(r, 250));
    }
    if (!ai || !pi) return {error: 'no_login_form'};
    const setV = (el,v) => {
        const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
        s.call(el,v); el.dispatchEvent(new Event('input',{bubbles:true}));
        el.dispatchEvent(new Event('change',{bubbles:true}));
    };
    setV(ai,'666'); setV(pi,'666');
    await new Promise(r=>setTimeout(r,400));
    btn.click();
    const s2 = Date.now();
    while (Date.now()-s2 < 7000) {
        if (location.hash !== '#/login') break;
        await new Promise(r=>setTimeout(r,200));
    }
    const lucky = JSON.parse(localStorage.getItem('lucky') || '{}');
    const TOKEN = lucky.token || null;
    if (!TOKEN) return {error:'no token after login'};

    // --- 2. Helper fetch with correct auth header ------------------------
    const hdrs = {
        'Accept':'application/json, text/plain, */*',
        'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': location.origin + '/',
        'Lucky-Admin-Token': TOKEN,
    };
    const GET = async (p) => {
        const r = await fetch('/api/'+p+'?_='+Date.now(), {credentials:'include', headers:hdrs});
        const t = await r.text();
        let j = null; try { j = JSON.parse(t); } catch(e){}
        return {status:r.status, json:j, text:t.slice(0,2000)};
    };
    const POST = async (p, body) => {
        const r = await fetch('/api/'+p, {method:'POST', credentials:'include',
            headers:{...hdrs, 'Content-Type':'application/json'}, body:JSON.stringify(body)});
        const t = await r.text();
        let j = null; try { j = JSON.parse(t); } catch(e){}
        return {status:r.status, json:j, text:t.slice(0,2000)};
    };

    // --- 3. GET known endpoints ------------------------------------------
    const out = {};
    out.info               = await GET('info');
    out.webservice_rules   = await GET('webservice/rules');
    out.webservice_lite    = await GET('webservice/rules_lite');
    // try to GET each individual rule detail (lucky pattern: GET webservice/rule?key=xxx)
    const ruleKeys = [];
    const list = (out.webservice_rules.json && out.webservice_rules.json.ruleList) || [];
    for (const rl of list) ruleKeys.push({RuleKey: rl.RuleKey, RuleName: rl.RuleName});
    out.rule_details = [];
    for (const {RuleKey} of ruleKeys) {
        // common lucky patterns for reading single rule detail
        for (const p of [
            'webservice/rule?Key='+RuleKey,
            'webservice/rule?key='+RuleKey,
            'webservice/rule/'+RuleKey,
        ]) {
            const rr = await GET(p);
            if (rr.status === 200 && rr.json && rr.json.ret === 0) {
                out.rule_details.push({query: p, result: rr.json});
                break;
            }
        }
    }
    // STUN
    out.stun_rules      = await GET('stun/rules');
    out.stun_clients    = await GET('stun/clients');
    out.stun_status     = await GET('stun/status');
    // DDNS
    out.ddns_rules      = await GET('ddns/rules');
    out.ddns_status     = await GET('ddns/status');

    return {token_prefix: TOKEN.slice(0,24)+'...', post_login_hash: location.hash, data: out};
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
        print(f"[x] script error: {data}")
        return 3

    print(f"post_login_hash={data.get('post_login_hash')}")
    print(f"token_prefix  ={data.get('token_prefix')}")
    d = data.get("data") or {}

    # --- Pretty-print summary --------------------------------------------
    def pp(path, obj, depth=0):
        prefix = "  " * depth
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)) and depth < 4:
                    print(f"{prefix}{k}:")
                    pp(path + "/" + k, v, depth + 1)
                else:
                    # trim long strings
                    sv = str(v)
                    if len(sv) > 300:
                        sv = sv[:300] + "...(truncated)"
                    print(f"{prefix}{k}: {sv}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                print(f"{prefix}[{i}]:")
                pp(path + "/" + str(i), item, depth + 1)
        else:
            print(f"{prefix}{obj}")

    print("\n" + "="*70)
    print("  LUCKY ADMIN  –  FULL CONFIG DUMP")
    print("="*70)

    info = ((d.get("info") or {}).get("json") or {}).get("info") or {}
    if info:
        print("\n[INFO] Lucky instance:")
        for k in ["AppName","Version","VersionName","OS","ARCH","Date","RunTime","GoVersion"]:
            if k in info: print(f"  - {k}: {info[k]}")

    rules = ((d.get("webservice_rules") or {}).get("json") or {}).get("ruleList") or []
    print(f"\n[WEBSERVICE] Reverse proxy rules (count={len(rules)}):")
    for r in rules:
        print(f"  • RuleKey={r.get('RuleKey')}  Name={r.get('RuleName')}")
        print(f"      Network={r.get('Network')}  {r.get('ListenIP')}:{r.get('ListenPort')}  TLS={r.get('EnableTLS')}  Enable={r.get('Enable')}")
        if r.get("Message"): print(f"      Message={r['Message']}")
        # Other common keys
        other = {k:v for k,v in r.items() if k not in {'RuleKey','RuleName','Network','ListenIP','ListenPort','EnableTLS','Enable','Message'}}
        # summarize nested
        def shrink(v):
            if isinstance(v, list): return f"[list len={len(v)}]"
            if isinstance(v, dict): return f"{{dict keys={list(v.keys())[:10]}}}"
            return v
        for k, v in other.items():
            print(f"      {k}: {shrink(v)}")

    rd = d.get("rule_details") or []
    if rd:
        print(f"\n[WEBSERVICE] Individual rule details (count={len(rd)}):")
        for item in rd:
            q = item.get("query")
            rj = (item.get("result") or {}).get("data") or (item.get("result") or {}).get("rule") or (item.get("result") or {})
            print(f"  query: {q}")
            pp("  ", rj, 2)

    print("\n[STUN]")
    for name in ["stun_rules", "stun_clients", "stun_status"]:
        r = d.get(name) or {}
        j = r.get("json")
        print(f"  GET /api/{name.replace('_','/')}: status={r.get('status')} ret={(j or {}).get('ret')}")
        if isinstance(j, dict):
            # drop duplicates
            cleaned = {k: v for k, v in j.items() if k != "ret"}
            s = json.dumps(cleaned, ensure_ascii=False)
            if len(s) > 400: s = s[:400] + "..."
            if cleaned: print(f"    {s}")

    print("\n[DDNS]")
    for name in ["ddns_rules", "ddns_status"]:
        r = d.get(name) or {}
        j = r.get("json")
        print(f"  GET /api/{name.replace('_','/')}: status={r.get('status')} ret={(j or {}).get('ret')}")
        if isinstance(j, dict):
            cleaned = {k: v for k, v in j.items() if k != "ret"}
            s = json.dumps(cleaned, ensure_ascii=False)
            if len(s) > 400: s = s[:400] + "..."
            if cleaned: print(f"    {s}")

    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
