#!/usr/bin/env python3
"""Configure STUN rule properly + restore GlobalStunServerList + detect public IP.
Then provide the ANAME record value.
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
        return {status:r.status, json:j, text:t.slice(0,4000)};
    };
    const PUT = async (p, body) => {
        const r = await fetch('/api/'+p, {method:'PUT', credentials:'include',
            headers:hdrs, body: JSON.stringify(body)});
        const t = await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
        return {status:r.status, json:j, text:t.slice(0,4000)};
    };
    const out = {};

    // 1. Restore STUN config with GlobalStunServerList + EnableModule
    const stunServers = [
        "stun.radiojar.com:3478","stun.ringostat.com:3478","stun.irishvoip.com:3478",
        "stun.voipgate.com:3478","stun.tula.nu:3478","stun.yesdates.com:3478",
        "stun.telnyx.com:3478","stun.vavadating.com:3478","stun.bau-ha.us:3478",
        "stun.bridesbay.com:3478","stun.3wayint.com:3478","stun.finsterwalder.com:3478",
        "stun.romaaeterna.nl:3478","stun.fitauto.ru:3478","stun.antisip.com:3478",
        "stun.heeds.eu:3478","stun.hot-chilli.net:3478","stun.eurosys.be:3478",
        "stun.vincross.com:3478","stun.cibercloud.com.br:3478","stun.siptrunk.com:3478"
    ];
    const stunConf = {
        EnableModule: true,
        WebhookEnable: false,
        WebhookOnlyAddrChange: false,
        ConfVer: 0,
        WebhookURL: "",
        WebhookMethod: "",
        WebhookHeaders: [],
        WebhookRequestBody: "",
        WebhookDisableCallbackSuccessContentCheck: false,
        WebhookSuccessContent: [],
        WebhookNetworkType: "",
        WebhookLocalAddr: "",
        WebhookProxy: "",
        WebhookProxyAddr: "",
        WebhookProxyUser: "",
        WebhookProxyPassword: "",
        WebhookInsecureSkipVerify: false,
        WebHookTimeout: 0,
        RetryCount: 0,
        RetryInterval: 0,
        GlobalStunServerList: stunServers,
    };
    out.stun_conf_put = await PUT('stun/configure', stunConf);
    await new Promise(r=>setTimeout(r,1000));
    out.stun_conf_after = await GET('stun/configure');

    // 2. Update the STUN rule with proper fields
    // First get the rule list to find the Key
    const list = await GET('stunrulelist');
    const rules = (list.json && list.json.list) || [];
    out.stun_rules_before = rules.map(r => ({Key:r.Key, Name:r.Name, StunType:r.StunType, StunLocalAddr:r.StunLocalAddr, PublicAddr:r.PublicAddr, Enable:r.Enable}));

    if (rules.length > 0) {
        const rule = rules[0];
        const key = rule.Key;
        // Update the rule with StunLocalAddr and StunType
        // StunLocalAddr = local address to expose (the reverse proxy port)
        // Try PUT /api/stunrule with the full rule body + updated fields
        const updateBody = Object.assign({}, rule, {
            StunLocalAddr: "127.0.0.1:8081",
            Enable: true,
        });
        out.stun_rule_update = await PUT('stunrule', updateBody);
        await new Promise(r=>setTimeout(r,2000));

        // Check updated rule
        const list2 = await GET('stunrulelist');
        const rules2 = (list2.json && list2.json.list) || [];
        out.stun_rules_after = rules2.map(r => ({Key:r.Key, Name:r.Name, StunType:r.StunType, StunLocalAddr:r.StunLocalAddr, PublicAddr:r.PublicAddr, PublicAddrInfo:r.PublicAddrInfo, Enable:r.Enable, TargetAddrList:r.TargetAddrList}));

        // Get rule detail
        out.stun_rule_detail = await GET('stun/'+key);
        // Get last logs
        out.stun_rule_logs = await GET('stun/'+key+'/lastlogs');
    }

    // 3. Wait a bit and poll for PublicAddr (STUN detection takes time)
    await new Promise(r=>setTimeout(r,8000));
    const list3 = await GET('stunrulelist');
    const rules3 = (list3.json && list3.json.list) || [];
    out.stun_rules_final = rules3.map(r => ({Key:r.Key, Name:r.Name, StunType:r.StunType, StunLocalAddr:r.StunLocalAddr, PublicAddr:r.PublicAddr, PublicAddrInfo:r.PublicAddrInfo, Enable:r.Enable}));

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
