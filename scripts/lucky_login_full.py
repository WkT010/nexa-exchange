#!/usr/bin/env python3
"""Full flow: navigate to login page, wait for form, actually submit login via button,
wait for redirect, intercept a real XHR (the frontend's own next /api call) so we can
capture exactly what auth headers it sends — that's the ground truth."""
import json
import time
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_lucky_setup import SimpleWS, cdp_call, get_pages


def main():
    pages = get_pages(9333)
    lucky_page = [p for p in pages if (p.get("type") or "page") == "page" and "localhost:16601" in (p.get("url") or "")][0]
    ws = SimpleWS(lucky_page["webSocketDebuggerUrl"])

    # Enable Network domain to capture XHR/Fetch request headers
    cdp_call(ws, "Network.enable", {}, timeout=30)

    # Navigate to lucky admin root (this should land on /#/login if not authed)
    cdp_call(ws, "Page.navigate", {"url": "http://localhost:16601/#/login"}, timeout=30)
    time.sleep(4)

    do_login_expr = r"""
(async () => {
    // Wait up to 8s for form inputs to appear
    const start = Date.now();
    let ai = null, pi = null, loginBtn = null;
    while (Date.now() - start < 8000) {
        const inputs = Array.from(document.querySelectorAll('input'));
        ai = inputs.find(i => (i.placeholder||'').includes('666') && i.type==='text');
        pi = inputs.find(i => (i.placeholder||'').includes('666') && i.type==='password');
        const btns = Array.from(document.querySelectorAll('button'));
        loginBtn = btns.find(b => /登|Login|Submit/.test(b.textContent||''));
        if (ai && pi && loginBtn) break;
        await new Promise(r=>setTimeout(r,250));
    }
    if (!ai || !pi) return {error: 'no_login_form', url: location.href, inputs: Array.from(document.querySelectorAll('input')).map(i=>({p:i.placeholder,t:i.type,n:i.name}))};
    const setV = (el,v) => {
        const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
        s.call(el, v);
        el.dispatchEvent(new Event('input',{bubbles:true}));
        el.dispatchEvent(new Event('change',{bubbles:true}));
    };
    setV(ai,'666'); setV(pi,'666');
    await new Promise(r=>setTimeout(r,500));
    if (!loginBtn) return {error: 'no_login_button'};
    loginBtn.click();
    // Wait up to 6s for hash change
    const s = Date.now();
    while (Date.now() - s < 6000) {
        if (location.hash !== '#/login') break;
        await new Promise(r=>setTimeout(r,200));
    }
    const lucky = JSON.parse(localStorage.getItem('lucky') || '{}');
    return {
        post_login_hash: location.hash,
        post_login_url: location.href,
        lucky_keys: Object.keys(lucky),
        token_preview: (lucky.token || '').slice(0, 40) + '...',
        user: lucky.user || null,
        raw_lucky: lucky,
    };
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": do_login_expr, "returnByValue": True, "awaitPromise": True}, timeout=60)
    login_info = None
    if r:
        res = r.get("result") or {}
        if res.get("exceptionDetails"):
            print(f"[eval exception] {str(res.get('exceptionDetails'))[:600]}")
        else:
            rv = res.get("result") or {}
            if rv.get("type") != "undefined":
                login_info = rv.get("value")
    print("[login] " + json.dumps(login_info, ensure_ascii=False)[:1200])

    # Now: click "Web 服务" menu entry or navigate via hash
    nav_expr = r"""
(async () => {
    location.hash = '#/webservice';
    await new Promise(r=>setTimeout(r, 3500));
    return {hash: location.hash, url: location.href, title: document.title};
})()
"""
    r2 = cdp_call(ws, "Runtime.evaluate", {"expression": nav_expr, "returnByValue": True, "awaitPromise": True}, timeout=60)
    nav_info = (r2.get("result") or {}).get("result", {}).get("value") if r2 else None
    print(f"\n[nav] {json.dumps(nav_info, ensure_ascii=False)[:500]}")

    time.sleep(2)  # give time for the frontend to fire its own /api/webservice/rules XHR

    # Fetch Network.requestWillBeSentExtraInfo events we captured — but we didn't attach
    # to them individually. Instead just poll via log / or better: attach a fetch request
    # interceptor NOW and then cause a refresh. We'll use simpler approach: call fetch
    # from the page's context with ALL headers that localStorage stores (including if
    # lucky stores the exact header name inside localStorage itself)
    capture_own_call_expr = r"""
(async () => {
    // Try reading sessionStorage too
    const ss_all = {}; for (let i=0; i<sessionStorage.length; i++) { const k=sessionStorage.key(i); ss_all[k]=sessionStorage.getItem(k); }
    const ls_all = {}; for (let i=0; i<localStorage.length; i++) { const k=localStorage.key(i); ls_all[k]=localStorage.getItem(k); }

    // Also look for IndexedDB hint? skip.
    // Try GET /api/webservice/rules first with Lucky-Admin-Token but ALSO also try adding
    // a Referer + Accept + common XHR headers the frontend sends.
    const paths = [
        'info',
        'webservice/rules',
        'webservice/rules_lite',
        'stun/rules',
    ];
    const tries = [
        {name: 'Lucky-Admin-Token', get: (ls) => ({'Lucky-Admin-Token': ls.token})},
        {name: 'Token',            get: (ls) => ({'Token': ls.token})},
    ];
    const ls = JSON.parse(localStorage.getItem('lucky') || '{}');
    const baseHdrs = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': location.origin + '/',
    };
    const out = [];
    for (const t of tries) {
        if (!ls.token) continue;
        const extra = t.get(ls);
        for (const p of paths) {
            try {
                const r = await fetch('/api/'+p+'?_='+Date.now(), {
                    credentials: 'include',
                    headers: {...baseHdrs, ...extra},
                });
                const txt = await r.text();
                out.push({try: t.name, path: p, status: r.status, resp: txt.slice(0,200)});
            } catch(e) {
                out.push({try: t.name, path: p, error: String(e).slice(0,200)});
            }
        }
    }
    return {sessionStorage: ss_all, localStorage_other: ls_all, api_results: out};
})()
"""
    r3 = cdp_call(ws, "Runtime.evaluate", {"expression": capture_own_call_expr, "returnByValue": True, "awaitPromise": True}, timeout=120)
    capture = None
    if r3:
        res3 = r3.get("result") or {}
        if res3.get("exceptionDetails"):
            print(f"\n[capture exception] {str(res3.get('exceptionDetails'))[:1000]}")
        else:
            rv = res3.get("result") or {}
            if rv.get("type") != "undefined":
                capture = rv.get("value")
    print(f"\n[capture] {json.dumps(capture, ensure_ascii=False)[:3000]}")

    ws.close()
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
