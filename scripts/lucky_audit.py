#!/usr/bin/env python3
"""Quickly re-login to Lucky via existing Chrome CDP, extract JWT, then dump current
WebService rules (reverse proxy rules) and public-access configs via direct HTTP API.

No UI mutations — read-only audit.
"""
import json
import time
import urllib.request
import urllib.error
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_lucky_setup import SimpleWS, cdp_call, get_pages


def main():
    # --- 1. Use existing Chrome CDP session (port 9333) ---
    try:
        pages = get_pages(9333)
    except Exception as e:
        print(f"[x] Cannot connect to Chrome CDP on port 9333: {e}")
        print("    Make sure chrome is running with --remote-debugging-port=9333")
        return 1

    # Find page on lucky admin; if none, just take first
    page = None
    for p in pages:
        if "localhost:16601" in (p.get("url") or ""):
            page = p
            break
    if page is None:
        # Navigate first page to lucky
        first = pages[0]
        ws = SimpleWS(first["webSocketDebuggerUrl"])
        cdp_call(ws, "Page.navigate", {"url": "http://localhost:16601/"}, timeout=30)
        time.sleep(4)
        page = first
        ws.close()

    ws = SimpleWS(page["webSocketDebuggerUrl"])

    # --- 2. Login via UI, extract token from localStorage.lucky ---
    login_expr = r"""
(async () => {
    const tryLogin = () => new Promise((resolve) => {
        const inputs = Array.from(document.querySelectorAll('input'));
        const ai = inputs.find(i => i && i.placeholder && i.placeholder.includes('666') && i.type === 'text');
        const pi = inputs.find(i => i && i.placeholder && i.placeholder.includes('666') && i.type === 'password');
        if (!ai || !pi) { resolve({need_login:false}); return; }
        const setValue = (el, val) => {
            const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            s.call(el, val);
            el.dispatchEvent(new Event('input', {bubbles:true}));
        };
        setValue(ai, '666'); setValue(pi, '666');
        setTimeout(() => {
            const btns = Array.from(document.querySelectorAll('button'));
            const loginBtn = btns.find(b => /登录|Login|Submit/.test(b.textContent || ''));
            if (loginBtn) loginBtn.click();
            setTimeout(resolve, 3500);
        }, 500);
    });
    await tryLogin();
    const luckyRaw = localStorage.getItem('lucky') || '{}';
    let lucky = {};
    try { lucky = JSON.parse(luckyRaw); } catch(e){}
    return {
        token: lucky.token || null,
        hash: window.location.hash,
        url: window.location.href,
        user: lucky.user || null,
    };
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": login_expr, "returnByValue": True, "awaitPromise": True}, timeout=90)
    res = (r.get("result") or {}).get("result") or {}
    login_res = res.get("value") if res.get("type") == "object" else None
    if not login_res:
        print("[x] Failed to get login result from Runtime.evaluate")
        print(json.dumps(r, indent=2, ensure_ascii=False)[:800])
        ws.close()
        return 2
    TOKEN = login_res.get("token")
    print(f"[+] page={login_res.get('url')}")
    print(f"[+] hash={login_res.get('hash')}")
    print(f"[+] user={login_res.get('user')}")
    if TOKEN:
        print(f"[+] token preview: {TOKEN[:40]}...")
    else:
        print("[x] NO token (login failed or already on non-login page)")
        ws.close()
        return 3
    ws.close()

    # --- 3. Direct HTTP API reads ---
    BASE = "http://localhost:16601"

    def api(method, path, body=None):
        url = BASE + "/api/" + path
        if method == "GET":
            url += "?_=" + str(int(time.time() * 1000))
        req = urllib.request.Request(url, method=method)
        req.add_header("Lucky-Admin-Token", TOKEN)
        req.add_header("Accept", "application/json, text/plain, */*")
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, data=data, timeout=12) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                try:
                    return {"status": resp.status, "json": json.loads(text)}
                except Exception:
                    return {"status": resp.status, "text": text[:600]}
        except urllib.error.HTTPError as e:
            return {"status": e.code, "text": e.read().decode("utf-8", errors="replace")[:600]}
        except Exception as e:
            return {"error": str(e)}

    print("\n" + "="*60)
    print("[*] Dumping Lucky Configs (read-only via API)")
    print("="*60)

    # 3.1 info
    info = api("GET", "info")
    j = info.get("json") or {}
    print(f"[GET /api/info] ret={j.get('ret')} data_keys={list((j.get('data') or {}).keys()) if isinstance(j.get('data'), dict) else 'N/A'}")
    if isinstance(j.get("data"), dict):
        d = j["data"]
        for k in ["version", "hostname", "arch", "os", "uptime"]:
            if k in d:
                print(f"   - {k}: {d[k]}")

    # 3.2 WebService rules
    for p in ["webservice/rules", "webservice/rules_lite", "webservice/status"]:
        r = api("GET", p)
        j = r.get("json") or {}
        status = r.get("status")
        ret = j.get("ret") if isinstance(j, dict) else None
        print(f"\n[GET /api/{p}] HTTP {status} ret={ret}")
        if isinstance(j, dict) and "data" in j and isinstance(j["data"], list):
            rules = j["data"]
            print(f"   rule_count={len(rules)}")
            for i, rule in enumerate(rules):
                # summarize common fields
                summary = {}
                for k in ["id", "name", "remark", "status", "listenType", "listenAddr", "listenPort", "domains", "subRules"]:
                    if k in rule:
                        v = rule[k]
                        if isinstance(v, list) and len(v) > 8:
                            v = f"[list len={len(v)}]"
                        if isinstance(v, dict) and len(v) > 12:
                            v = f"{{dict keys={list(v.keys())[:12]}}}"
                        summary[k] = v
                print(f"   [{i}] {json.dumps(summary, ensure_ascii=False)[:500]}")
        elif isinstance(j, dict):
            print(f"   payload shape: {json.dumps(j, ensure_ascii=False)[:600]}")

    # 3.3 STUN / DDNS / network — common lucky modules
    modules_to_probe = [
        "stun/client",
        "stun/clients",
        "stun/status",
        "stun/rules",
        "stun/rule",
        "ddns/rules",
        "ddns/rule",
        "ddns/status",
        "ddns/list",
        "network/status",
        "network/info",
        "network/interfaces",
        "portfwd/rules",
        "portfwd/status",
    ]
    print("\n" + "-"*60)
    print("[*] Probing STUN/DDNS/Network read endpoints")
    print("-"*60)
    for p in modules_to_probe:
        r = api("GET", p)
        st = r.get("status")
        txt = r.get("text", "")[:120]
        j = r.get("json") if isinstance(r.get("json"), dict) else None
        if st == 200:
            ret = j.get("ret") if j else None
            print(f"  [200] GET /api/{p:<28} ret={ret}")
            if j and "data" in j and isinstance(j["data"], list) and j["data"]:
                print(f"        sample_keys={list(j['data'][0].keys())[:15] if isinstance(j['data'][0], dict) else type(j['data'][0])}")
                print(f"        first_item_preview={str(j['data'][0])[:300]}")
        elif st == 404:
            continue
        else:
            print(f"  [{st}]  GET /api/{p:<28} {txt}")

    print("\n[DONE]")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
