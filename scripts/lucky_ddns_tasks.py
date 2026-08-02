#!/usr/bin/env python3
"""Query DDNS task list + read task form schema + get current public IP.
Then present ANAME configuration options.
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
    const hdrs = {'Accept':'application/json, text/plain, */*','Lucky-Admin-Token': TOKEN};
    const GET = async (p) => {
        const r = await fetch('/api/'+p+'?_='+Date.now(), {credentials:'include', headers:hdrs});
        const t = await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,4000)};
    };
    const out = {};

    // 1. DDNS task list
    out.ddnstasklist = await GET('ddnstasklist');

    // 2. DDNS configure
    out.ddns_configure = await GET('ddns/configure');

    // 3. DDNS enable status
    out.ddns_enable = await GET('ddns/enable');

    // 4. Get current public IP via Lucky's IP detection
    // Lucky has /api/status which may include public IP
    out.status = await GET('status');
    out.info = await GET('info');

    // 5. Read DDNS panel JS for task form schema
    try {
        const ddnsJs = await (await fetch('/static/js/lucky_panel-DLPu5bxN.js', {credentials:'include'})).text();
        // Extract the DNS provider type enum values
        const providerMatches = [...new Set(ddnsJs.match(/['"`](cloudflare|dnspod|aliyun|tencent|namesilo|godaddy|he|dynv6|huawei|callback|cloudxns)['"`]/gi) || [])];
        out.providers = providerMatches;
        // Extract field names that look like form fields
        const fields = [...new Set(ddnsJs.match(/['"`]([A-Za-z_][A-Za-z0-9_]{2,40})['"`]/g) || [])]
            .map(s=>s.replace(/['"`]/g,''))
            .filter(s => /domain|host|record|provider|token|secret|apikey|login|password|type|name|enable|reg|cmd|ipv|addr|ttl|line|remark|comment|proxy|secure|skip/i.test(s))
            .filter(s => !/^(?:true|false|null|undefined|none|GET|POST|PUT|DELETE|Content|Accept|Application|JSON|String|Object|Number|Array|Error|Date|Math|JSON|console|window|document|fetch|Promise|Object)$/.test(s));
        out.form_fields = [...new Set(fields)].slice(0,100);
    } catch(e) { out.js_error = String(e); }

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
