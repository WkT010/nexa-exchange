#!/usr/bin/env python3
"""Debug: in-page eval to understand the exact headers lucky expects, by watching the fetch
of the frontend's own next /api/info call after a page navigation. Also dump: localStorage,
cookies, and intercept XHRs to capture real request headers.
"""
import json
import time
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_lucky_setup import SimpleWS, cdp_call, get_pages


def eval_js(ws, expr, timeout=90):
    r = cdp_call(ws, "Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True}, timeout=timeout)
    if not r:
        return None
    res = r.get("result") or {}
    if res.get("exceptionDetails"):
        return {"__error__": str(res.get("exceptionDetails"))[:1200]}
    rv = res.get("result") or {}
    if rv.get("type") == "undefined":
        return None
    return rv.get("value")


def main():
    pages = get_pages(9333)
    lucky_page = [p for p in pages if (p.get("type") or "page") == "page" and "localhost:16601" in (p.get("url") or "")][0]
    ws = SimpleWS(lucky_page["webSocketDebuggerUrl"])

    check = r"""
(async () => {
    const lucky = JSON.parse(localStorage.getItem('lucky') || '{}');
    const cookies = document.cookie;
    // Try calling with explicit `Token` header (older lucky versions use this too)
    const headers_variants = [
        {name: 'Lucky-Admin-Token', val: lucky.token},
        {name: 'Token', val: lucky.token},
        {name: 'Authorization', val: 'Bearer ' + lucky.token},
        {name: 'X-Token', val: lucky.token},
    ];
    const results = [];
    for (const h of headers_variants) {
        if (!h.val) continue;
        const hdrs = {'Accept':'application/json, text/plain, */*'};
        hdrs[h.name] = h.val;
        try {
            const r = await fetch('/api/info?_=' + Date.now(), {credentials:'include', headers: hdrs});
            const t = await r.text();
            results.push({header: h.name, status: r.status, resp: t.slice(0,200)});
        } catch(e) {
            results.push({header: h.name, error: String(e).slice(0,200)});
        }
    }
    // Also: call via same helper lucky uses. Check which global vars exist.
    const globals = [];
    for (const k of ['Lucky', 'lucky', 'http', '$http', 'axios', 'request', 'api']) {
        globals.push([k, typeof window[k]]);
    }
    return {
        lucky_keys: Object.keys(lucky),
        user: lucky.user || null,
        token_prefix: (lucky.token||'').slice(0,16)+'...',
        cookies: cookies.slice(0,300),
        header_results: results,
        globals_types: globals,
    };
})()
"""
    data = eval_js(ws, check, timeout=120)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    ws.close()
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
