#!/usr/bin/env python3
"""Configure Lucky via CDP: create reverse proxy rule + STUN tunnel.
Uses browser's authenticated fetch context (auto-attaches Lucky-Admin-Token header).
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
    print(f"[+] Using page: {lucky_page.get('url')}")

    # --- Step 1: Create reverse proxy rule ---
    create_rule_expr = r"""
(async () => {
    let TOKEN = null;
    try { TOKEN = JSON.parse(localStorage.getItem('lucky') || '{}').token || null; } catch(e){}
    if (!TOKEN) return {error: 'no token'};

    const hdrs = {
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        'Lucky-Admin-Token': TOKEN,
    };
    const GET = async (p) => {
        const r = await fetch('/api/'+p+'?_='+Date.now(), {credentials:'include', headers: hdrs});
        const t = await r.text();
        let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,1000)};
    };
    const POST = async (p, body) => {
        const r = await fetch('/api/'+p, {method:'POST', credentials:'include',
            headers: hdrs, body: JSON.stringify(body)});
        const t = await r.text();
        let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,1000)};
    };
    const PUT = async (p, body) => {
        const r = await fetch('/api/'+p, {method:'PUT', credentials:'include',
            headers: hdrs, body: JSON.stringify(body)});
        const t = await r.text();
        let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,1000)};
    };

    // 1. Check existing rules
    const existing = await GET('webservice/rules');
    const rules = (existing.json && existing.json.ruleList) || [];
    let ruleKey = null;
    for (const r of rules) {
        if (r.RuleName === 'NEXA' || r.ListenPort === 8081) {
            ruleKey = r.RuleKey;
        }
    }

    if (ruleKey) {
        return {action: 'rule_exists', ruleKey: ruleKey, existing_count: rules.length};
    }

    // 2. Create rule
    const ruleBody = {
        RuleName: "NEXA",
        Network: "tcp4",
        ListenIP: "0.0.0.0",
        ListenPort: 8081,
        Enable: true,
        EnableTLS: false,
        DiaglogShowMode: "diy",
        AutoOptionsFirewall: true,
        TLSMinVersion: 2,
        Http3: false,
        ProxyList: [{
            Remark: "main",
            Domains: ["canival.fyi"],
            Locations: ["http://127.0.0.1:8080"],
            WebServiceType: "reverseproxy",
            Enable: true,
            EasyLucky: true,
            EnableAccessLog: true,
            LogLevel: 4,
            LocationInsecureSkipVerify: true,
            SafeIPMode: "blacklist",
            SafeUserAgentMode: "blacklist",
            HttpClientNetwork: "tcp",
            HttpClientTimeout: 10,
            ForwardedByClientIP: false,
            DisableLongConnection: false,
            EnableCrossDomain: false,
            EnableBasicAuth: false,
            CustomRobotTxt: false,
            DealCacheBeforeReverseProxy: true,
            FileServerShowDir: true,
            FileServerIndexNames: "index.html\nindex.htm",
            AccessLogMaxNum: 256,
            WebListShowLastLogMaxCount: 10,
            DisplayInFrontendList: false,
            MaxContinuous404Count: 0,
        }],
        DefaultProxy: {
            WebServiceType: "reverseproxy",
            EnableAccessLog: true,
            LogLevel: 4,
            LocationInsecureSkipVerify: true,
            EasyLucky: false,
            SafeIPMode: "blacklist",
            SafeUserAgentMode: "blacklist",
            HttpClientNetwork: "tcp",
            HttpClientTimeout: 10,
            ForwardedByClientIP: false,
            DisableLongConnection: false,
            EnableCrossDomain: false,
            EnableBasicAuth: false,
            CustomRobotTxt: false,
            DealCacheBeforeReverseProxy: true,
            FileServerShowDir: true,
            FileServerIndexNames: "index.html\nindex.htm",
            AccessLogMaxNum: 256,
            WebListShowLastLogMaxCount: 10,
            DisplayInFrontendList: false,
            MaxContinuous404Count: 0,
        },
    };

    // Try POST webservice/rule
    const result = await POST('webservice/rule', ruleBody);
    return {action: 'create_rule', result: result};
})()
"""
    print("\n[Step 1] Creating reverse proxy rule...")
    r = eval_js(ws, create_rule_expr, timeout=120)
    print(json.dumps(r, indent=2, ensure_ascii=False)[:2000])

    # --- Step 2: Verify rule + test connectivity ---
    verify_expr = r"""
(async () => {
    let TOKEN = JSON.parse(localStorage.getItem('lucky') || '{}').token || null;
    const hdrs = {'Accept':'application/json','Lucky-Admin-Token': TOKEN};
    const GET = async (p) => {
        const r = await fetch('/api/'+p+'?_='+Date.now(), {credentials:'include', headers: hdrs});
        const t = await r.text();
        let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,1500)};
    };
    const rules = await GET('webservice/rules');
    const list = (rules.json && rules.json.ruleList) || [];
    const summary = list.map(r => ({
        RuleKey: r.RuleKey, RuleName: r.RuleName, Network: r.Network,
        ListenIP: r.ListenIP, ListenPort: r.ListenPort, Enable: r.Enable,
    }));
    return {rule_count: list.length, rules: summary};
})()
"""
    print("\n[Step 2] Verifying rule...")
    r2 = eval_js(ws, verify_expr, timeout=60)
    print(json.dumps(r2, indent=2, ensure_ascii=False)[:1000])

    # --- Step 3: Probe STUN API ---
    stun_probe_expr = r"""
(async () => {
    let TOKEN = JSON.parse(localStorage.getItem('lucky') || '{}').token || null;
    const hdrs = {'Accept':'application/json','Lucky-Admin-Token': TOKEN};
    const GET = async (p) => {
        const r = await fetch('/api/'+p+'?_='+Date.now(), {credentials:'include', headers: hdrs});
        const t = await r.text();
        let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,1500)};
    };
    const POST = async (p, body) => {
        const r = await fetch('/api/'+p, {method:'POST', credentials:'include',
            headers: {...hdrs, 'Content-Type':'application/json'}, body: JSON.stringify(body)});
        const t = await r.text();
        let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,1500)};
    };

    // Probe STUN GET endpoints
    const paths = [
        'stun/rules','stun/rule','stun/clients','stun/client','stun/status','stun',
        'stun/list','stun/info','stun/config','stun/task','stun/tasks',
    ];
    const results = {};
    for (const p of paths) {
        const r = await GET(p);
        if (r.status === 404) continue;
        results[p] = {status: r.status, ret: r.json?.ret, msg: r.json?.msg, data_preview: JSON.stringify(r.json?.data || r.json || '').slice(0, 300)};
    }

    // Read stun config file
    let stunConf = null;
    try {
        const idx = await (await fetch('/static/js/lucky_index-DyslG9Ot.js', {credentials:'include'})).text();
        const stunChunks = [...new Set(idx.match(/lucky_[A-Za-z0-9_-]*[Ss]tun[A-Za-z0-9_-]*\.js/g) || [])];
        if (stunChunks.length > 0) {
            const stunJs = await (await fetch('/static/js/' + stunChunks[0], {credentials:'include'})).text();
            // Extract API paths
            const apiPaths = [...new Set(stunJs.match(/['"`](\/?api\/[a-zA-Z0-9_\/-]+)['"`]/g) || [])].map(s=>s.replace(/['"`]/g,''));
            const fields = [...new Set(stunJs.match(/['"`]([A-Za-z_][A-Za-z0-9_]{1,40})['"`]/g) || [])]
                .map(s=>s.replace(/['"`]/g,''))
                .filter(s => /stun|rule|client|domain|addr|port|server|listen|forward|tunnel|subdomain|host|penetrat/i.test(s));
            stunConf = {chunk: stunChunks[0], len: stunJs.length, apiPaths: apiPaths.slice(0,20), fields: fields.slice(0,60)};
        }
    } catch(e) { stunConf = {error: String(e)}; }

    return {get_results: results, stun_js: stunConf};
})()
"""
    print("\n[Step 3] Probing STUN API...")
    r3 = eval_js(ws, stun_probe_expr, timeout=180)
    print(json.dumps(r3, indent=2, ensure_ascii=False)[:3000])

    ws.close()
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
