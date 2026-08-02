#!/usr/bin/env python3
"""Recreate the NEXA reverse proxy rule (port 8081, canival.fyi -> 127.0.0.1:8080).
Uses the browser's authenticated fetch context.
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
        return {status:r.status, json:j, text:t.slice(0,2000)};
    };
    const POST = async (p, body) => {
        const r = await fetch('/api/'+p, {method:'POST', credentials:'include',
            headers:hdrs, body: JSON.stringify(body)});
        const t = await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,2000)};
    };

    // 1. Check existing rules
    const existing = await GET('webservice/rules');
    const rules = (existing.json && existing.json.ruleList) || [];
    if (rules.length > 0) {
        return {action:'exists', rules: rules.map(r=>({RuleName:r.RuleName,ListenPort:r.ListenPort,RuleKey:r.RuleKey}))};
    }

    // 2. Create NEXA reverse proxy rule
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

    const result = await POST('webservice/rules', ruleBody);

    // 3. Verify
    await new Promise(r=>setTimeout(r,1000));
    const verify = await GET('webservice/rules');
    const vrules = (verify.json && verify.json.ruleList) || [];

    return {action:'create', create_result: result, verify: vrules.map(r=>({RuleName:r.RuleName,ListenPort:r.ListenPort,RuleKey:r.RuleKey,Enable:r.Enable}))};
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
    print(json.dumps(r, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
