#!/usr/bin/env python3
"""Set STUN rule fields correctly (ListenIP, ListenPort, TargetAddressList, StunType, UPnP).
Then poll for PublicAddr detection.
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

    // 1. Get current STUN rule detail (full)
    const list = await GET('stunrulelist');
    const rules = (list.json && list.json.list) || [];
    if (rules.length === 0) return {error:'no stun rule'};
    const key = rules[0].Key;
    const detail = await GET('stun/'+key);
    const rule = (detail.json && detail.json.rule) || rules[0];
    out.rule_before = {Key:rule.Key, Name:rule.Name, StunType:rule.StunType, ListenIP:rule.ListenIP, ListenPort:rule.ListenPort, TargetAddressList:rule.TargetAddressList, TargetPort:rule.TargetPort, UPnP:rule.UPnP, NatPMP:rule.NatPMP, PublicAddr:rule.PublicAddr, Enable:rule.Enable, StunListenType:rule.StunListenType};

    // 2. Update rule with proper fields to expose port 8081
    // StunType: "TCP" for HTTP reverse proxy
    // ListenIP/ListenPort: where Lucky STUN listens (the reverse proxy port)
    // TargetAddressList/TargetPort: where to forward (the actual backend)
    // UPnP/NatPMP: enable for auto port forwarding
    const updateBody = Object.assign({}, rule, {
        Enable: true,
        StunType: "TCP",
        StunListenType: "tcp4",
        ListenIP: "0.0.0.0",
        ListenPort: 8081,
        TargetAddressList: ["127.0.0.1"],
        TargetPort: 8081,
        UPnP: true,
        NatPMP: true,
        AutoOptionsFirewall: true,
        DisablePortForward: false,
        UseGlobalStunServerList: true,
        StunAutoRetry: true,
        StunHeartbeatInterval: 30,
        StunTimeout: 5,
        StunRetryInterval: 10,
        AutoAddPubAddrWhiteList: true,
    });
    out.update_result = await PUT('stunrule', updateBody);
    await new Promise(r=>setTimeout(r,2000));

    // 3. Check updated rule
    const detail2 = await GET('stun/'+key);
    const rule2 = (detail2.json && detail2.json.rule) || {};
    out.rule_after = {Key:rule2.Key, Name:rule2.Name, StunType:rule2.StunType, ListenIP:rule2.ListenIP, ListenPort:rule2.ListenPort, TargetAddressList:rule2.TargetAddressList, TargetPort:rule2.TargetPort, UPnP:rule2.UPnP, NatPMP:rule2.NatPMP, PublicAddr:rule2.PublicAddr, PublicAddrInfo:rule2.PublicAddrInfo, Enable:rule2.Enable};

    // 4. Get logs to see STUN activity
    out.lastlogs = await GET('stun/'+key+'/lastlogs');

    // 5. Wait for STUN detection (poll 3 times with 10s intervals)
    for (let i = 0; i < 3; i++) {
        await new Promise(r=>setTimeout(r,10000));
        const d = await GET('stun/'+key);
        const rr = (d.json && d.json.rule) || {};
        out['poll_'+i] = {PublicAddr: rr.PublicAddr, PublicAddrInfo: rr.PublicAddrInfo, StunType: rr.StunType};
        if (rr.PublicAddr) break;
    }

    // 6. Final rule list
    out.final_list = await GET('stunrulelist');

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
