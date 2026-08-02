#!/usr/bin/env python3
"""Check created STUN rule detail + status to extract public IP / assigned domain.
Also probe DDNS module if present (Lucky may have built-in DDNS that gives a fixed subdomain).
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
        return {status:r.status, json:j, text:t.slice(0,3000)};
    };
    const out = {};

    // 1. STUN rule list (full)
    out.stunrulelist = await GET('stunrulelist');

    // 2. For each rule, get detail
    const list = (out.stunrulelist.json && out.stunrulelist.json.list) || [];
    out.rule_count = list.length;
    out.rule_details = {};
    for (const r of list) {
        const key = r.RuleKey || r.key || r.ruleKey || r.ID || r.id;
        out.rule_details[String(key)] = { summary: r };
        // GET /api/stun/{key}
        const det = await GET('stun/'+key);
        out.rule_details[String(key)].detail = det;
        // GET /api/stun/{key}/lastlogs
        const logs = await GET('stun/'+key+'/lastlogs');
        out.rule_details[String(key)].lastlogs = logs;
    }

    // 3. Probe DDNS endpoints (Lucky may have DDNS that provides a fixed subdomain)
    const ddnsPaths = [
        'ddns/configure','ddns/rules','ddns/rule','ddns/list','ddns/status',
        'ddns','ddns/domains','ddns/task','ddns/tasks',
    ];
    out.ddns_probe = {};
    for (const p of ddnsPaths) {
        const r = await GET(p);
        if (r.status === 404) continue;
        out.ddns_probe[p] = {status:r.status, ret:r.json?.ret, msg:r.json?.msg,
            data_preview: JSON.stringify(r.json||r.text).slice(0,400)};
    }

    // 4. Read index JS to find DDNS chunk
    try {
        const idx = await (await fetch('/static/js/lucky_index-DyslG9Ot.js', {credentials:'include'})).text();
        const ddnsChunks = [...new Set(idx.match(/lucky_[A-Za-z0-9_-]*[Dd][Dd][Nn][Ss][A-Za-z0-9_-]*\.js/g) || [])];
        out.ddns_chunks = ddnsChunks;
        // also look for any chunk with "domain" or "tunnel" or "frp"
        const tunnelChunks = [...new Set(idx.match(/lucky_[A-Za-z0-9_-]*(tunnel|frp|nat|cloud)[A-Za-z0-9_-]*\.js/gi) || [])];
        out.tunnel_chunks = tunnelChunks;
    } catch(e) { out.idx_error = String(e); }

    return out;
})()
"""


def main():
    pages = get_pages(9333)
    lucky_page = [p for p in pages if (p.get("type") or "page") == "page" and "localhost:16601" in (p.get("url") or "")][0]
    ws = SimpleWS(lucky_page["webSocketDebuggerUrl"])
    print(f"[+] Using page: {lucky_page.get('url')}")
    r = eval_js(ws, JS, timeout=180)
    ws.close()
    if not r:
        print("[x] empty"); return 1
    print(json.dumps(r, indent=2, ensure_ascii=False)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
