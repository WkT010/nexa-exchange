#!/usr/bin/env python3
"""Update STUN rule WITHOUT NatPMP/UPnP (they fail in sandbox).
Just set StunType, ListenIP, ListenPort, TargetAddressList for IP detection.
Then get public IP and provide ANAME record value.
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
        return {status:r.status, json:j, text:t.slice(0,5000)};
    };
    const PUT = async (p, body) => {
        const r = await fetch('/api/'+p, {method:'PUT', credentials:'include',
            headers:hdrs, body: JSON.stringify(body)});
        const t = await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,5000)};
    };
    const out = {};

    // 1. Get current rule
    const list = await GET('stunrulelist');
    const rules = (list.json && list.json.list) || [];
    if (rules.length === 0) return {error:'no stun rule'};
    const key = rules[0].Key;
    const detail = await GET('stun/'+key);
    const rule = (detail.json && detail.json.rule) || rules[0];

    // 2. Update rule WITHOUT NatPMP/UPnP (they fail in sandbox)
    //    DisablePortForward=true to skip the port mapping test
    const updateBody = Object.assign({}, rule, {
        Enable: true,
        StunType: "TCP",
        StunListenType: "tcp4",
        ListenIP: "0.0.0.0",
        ListenPort: 8081,
        TargetAddressList: ["127.0.0.1"],
        TargetPort: 8081,
        UPnP: false,
        NatPMP: false,
        DisablePortForward: true,
        AutoOptionsFirewall: false,
        UseGlobalStunServerList: true,
        StunAutoRetry: true,
        StunHeartbeatInterval: 30,
        StunTimeout: 5,
        StunRetryInterval: 10,
        AutoAddPubAddrWhiteList: false,
    });
    out.update_result = await PUT('stunrule', updateBody);
    await new Promise(r=>setTimeout(r,2000));

    // 3. Check updated rule
    const detail2 = await GET('stun/'+key);
    const rule2 = (detail2.json && detail2.json.rule) || {};
    out.rule_after = {
        Key: rule2.Key, Name: rule2.Name, StunType: rule2.StunType,
        ListenIP: rule2.ListenIP, ListenPort: rule2.ListenPort,
        TargetAddressList: rule2.TargetAddressList, TargetPort: rule2.TargetPort,
        PublicAddr: rule2.PublicAddr, PublicAddrInfo: rule2.PublicAddrInfo,
        Enable: rule2.Enable, DisablePortForward: rule2.DisablePortForward,
        StunListenType: rule2.StunListenType,
    };

    // 4. Get logs
    out.lastlogs = await GET('stun/'+key+'/lastlogs');

    // 5. Poll for PublicAddr (STUN IP detection)
    for (let i = 0; i < 4; i++) {
        await new Promise(r=>setTimeout(r,8000));
        const d = await GET('stun/'+key);
        const rr = (d.json && d.json.rule) || {};
        out['poll_'+i] = {PublicAddr: rr.PublicAddr, PublicAddrInfo: rr.PublicAddrInfo};
        if (rr.PublicAddr) break;
    }

    // 6. Also get public IP directly
    try {
        const r = await fetch('https://icanhazip.com');
        out.direct_public_ip = (await r.text()).trim();
    } catch(e) { out.direct_public_ip_err = String(e).slice(0,200); }

    // 7. Verify reverse proxy rule still exists
    out.webservice_rules = await GET('webservice/rules');

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
    print(json.dumps(r, indent=2, ensure_ascii=False)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
