#!/usr/bin/env python3
"""Dump Lucky reverse proxy + STUN + DDNS configs via Chrome CDP by evaluating JS inside
the already-authenticated lucky admin page (fetch API reuses browser session automatically).
"""
import json
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_lucky_setup import SimpleWS, cdp_call, get_pages


def eval_js(ws, expr, timeout=120):
    r = cdp_call(
        ws, "Runtime.evaluate",
        {"expression": expr, "returnByValue": True, "awaitPromise": True},
        timeout=timeout,
    )
    if not r:
        return None
    res = r.get("result") or {}
    # Handle exception
    if res.get("exceptionDetails"):
        return {"__error__": str(res.get("exceptionDetails"))[:500]}
    rv = res.get("result") or {}
    if rv.get("type") == "undefined":
        return None
    return rv.get("value")


def main():
    # Connect to an authenticated lucky page
    pages = get_pages(9333)
    lucky_page = None
    for p in pages:
        url = p.get("url") or ""
        if "localhost:16601" in url and (p.get("type") or "page") == "page":
            lucky_page = p
            break
    if lucky_page is None:
        # take any page, navigate
        lucky_page = [p for p in pages if (p.get("type") or "page") == "page"][0]
        ws = SimpleWS(lucky_page["webSocketDebuggerUrl"])
        print(f"[+] Navigate to Lucky admin: {lucky_page.get('url')}")
        cdp_call(ws, "Page.navigate", {"url": "http://localhost:16601/#/about"}, timeout=30)
        time.sleep(5)
    else:
        ws = SimpleWS(lucky_page["webSocketDebuggerUrl"])
        print(f"[+] Reusing existing lucky page: {lucky_page.get('url')}")

    # If not logged in, try a login step
    check_login_expr = r"""
(async () => {
    let token = null;
    try { token = JSON.parse(localStorage.getItem('lucky') || '{}').token || null; } catch(e){}
    if (token) return {status: 'authenticated', token_preview: token.slice(0, 32) + '...'};
    // try login
    const inputs = Array.from(document.querySelectorAll('input'));
    const ai = inputs.find(i => i && (i.placeholder||'').includes('666') && i.type==='text');
    const pi = inputs.find(i => i && (i.placeholder||'').includes('666') && i.type==='password');
    if (!ai || !pi) return {status: 'no_login_form_found', url: location.href};
    const setV = (el,v) => { const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; s.call(el,v); el.dispatchEvent(new Event('input',{bubbles:true})); };
    setV(ai,'666'); setV(pi,'666');
    await new Promise(r=>setTimeout(r,400));
    const btn = Array.from(document.querySelectorAll('button')).find(b => /登|Login|Submit/.test(b.textContent||''));
    if (btn) btn.click();
    await new Promise(r=>setTimeout(r,3500));
    try { token = JSON.parse(localStorage.getItem('lucky') || '{}').token || null; } catch(e){}
    return {status: token?'authenticated':'login_failed', token_preview: token?(token.slice(0,32)+'...'):null};
})()
"""
    login = eval_js(ws, check_login_expr, timeout=120)
    print(f"[+] auth status: {json.dumps(login, ensure_ascii=False)}")

    dump_expr = r"""
(async () => {
    let TOKEN = null;
    try { TOKEN = JSON.parse(localStorage.getItem('lucky') || '{}').token || null; } catch(e){}
    const baseHeaders = {'Accept':'application/json, text/plain, */*'};
    if (TOKEN) baseHeaders['Lucky-Admin-Token'] = TOKEN;

    const get = async (path, opts={}) => {
        const r = await fetch('/api/' + path + '?_=' + Date.now(), {
            credentials: 'include',
            headers: {...baseHeaders, ...(opts.headers||{})},
            ...Object.fromEntries(Object.entries(opts).filter(([k])=>k!=='headers'))
        });
        const t = await r.text();
        let j = null; try { j = JSON.parse(t); } catch(e){}
        return {status: r.status, json: j, text: t.slice(0, 800)};
    };
    const post = async (path, body) => get(path, {
        method: 'POST',
        body: JSON.stringify(body),
        headers: {'Content-Type':'application/json'}
    });

    // --- common lucky module endpoints (probe GETs) ---
    const reads = [
        'info',
        'webservice/rules','webservice/rules_lite','webservice/rule','webservice/status','webservice','webservice/logs','webservice/lastlogs',
        'stun/rules','stun/rule','stun/clients','stun/client','stun/status','stun',
        'ddns/rules','ddns/rule','ddns/status','ddns/list','ddns',
        'socat/rules','socat/status','socat',
        'frpc/rules','frpc/status','frpc',
        'network/status','network/info','network/interfaces',
        'portfwd/rules','portfwd/status','portfwd',
        'system/info','system/status',
    ];
    const out = {};
    for (const p of reads) {
        const r = await get(p);
        if (r.status === 404) continue;
        out[p] = r.json !== null ? r.json : {status: r.status, text: r.text};
    }
    return out;
})()
"""
    print("[+] Dumping via browser fetch (authenticated context)...")
    data = eval_js(ws, dump_expr, timeout=180)
    ws.close()

    if data is None:
        print("[x] Got empty result from eval_js")
        return 1
    if isinstance(data, dict) and "__error__" in data:
        print(f"[x] JS exception: {data['__error__']}")
        return 2

    print("\n" + "="*72)
    print(" LUCKY CONFIG DUMP (via authenticated browser session)")
    print("="*72)
    for key, val in data.items():
        # Pretty print: parse ret, data shape
        print(f"\n[ /api/{key} ]")
        if isinstance(val, dict):
            ret = val.get("ret")
            msg = val.get("msg")
            d = val.get("data")
            print(f"  ret={ret!r} msg={msg!r}")
            if isinstance(d, list):
                print(f"  data is LIST length={len(d)}")
                for i, item in enumerate(d):
                    # summarize
                    summary = {}
                    if isinstance(item, dict):
                        for k in ["id","name","remark","status","listenType","listenAddr","listenPort","domains","subRules","type","protocol","serverName","addr","domain","backends"]:
                            if k in item:
                                v = item[k]
                                if isinstance(v, list): v = f"[len={len(v)}]"
                                if isinstance(v, dict): v = f"{{keys={list(v.keys())[:10]}}}"
                                summary[k] = v
                    else:
                        summary = str(item)[:300]
                    print(f"    [{i}] {json.dumps(summary, ensure_ascii=False)[:500]}")
            elif isinstance(d, dict):
                print(f"  data keys: {list(d.keys())[:20]}")
                s = json.dumps(d, ensure_ascii=False)
                print(f"  data preview: {s[:600]}")
            else:
                s = json.dumps(val, ensure_ascii=False)
                print(f"  payload preview: {s[:600]}")
        else:
            print(f"  value={str(val)[:500]}")

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
