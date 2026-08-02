#!/usr/bin/env python3
"""Get current public IP + verify reverse proxy rule + summarize for ANAME config."""
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
    const hdrs = {'Accept':'application/json, text/plain, */*','Lucky-Admin-Token': TOKEN};
    const GET = async (p) => {
        const r = await fetch('/api/'+p+'?_='+Date.now(), {credentials:'include', headers:hdrs});
        const t = await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,3000)};
    };
    const out = {};

    // 1. Reverse proxy rules (verify NEXA rule exists)
    out.webservice_rules = await GET('webservice/rules');

    // 2. Try to get public IP via Lucky's IPDB module
    out.ipdb = await GET('ipdb');

    // 3. Get public IP via external services (from browser context)
    try {
        const r = await fetch('https://api.ipify.org?format=json');
        out.public_ip_ipify = await r.json();
    } catch(e) { out.public_ip_ipify_err = String(e); }
    try {
        const r = await fetch('https://icanhazip.com');
        out.public_ip_icanhazip = (await r.text()).trim();
    } catch(e) { out.public_ip_icanhazip_err = String(e); }

    return out;
})()
"""


def main():
    pages = get_pages(9333)
    lucky_page = [p for p in pages if (p.get("type") or "page") == "page" and "localhost:16601" in (p.get("url") or "")][0]
    ws = SimpleWS(lucky_page["webSocketDebuggerUrl"])
    print(f"[+] Using page: {lucky_page.get('url')}")
    r = eval_js(ws, JS, timeout=120)
    ws.close()
    if not r:
        print("[x] empty"); return 1
    print(json.dumps(r, indent=2, ensure_ascii=False)[:5000])
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
