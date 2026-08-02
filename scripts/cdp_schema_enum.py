#!/usr/bin/env python3
"""
FINAL ATTEMPT: Hand-craft every possible field combination for Lucky 2.13.4
reverse proxy rule, restarting lucky for EACH attempt so we NEVER hit rate limit
or corrupted state from 500 panics. This takes longer but gives us ground truth.

We'll enumerate the schema based on all the clues from 500 vs non-500:

Non-500 bodies (pass basic Go JSON unmarshal + valid check):
  * status=disable/1/true/... but NOT status=enable/0
  * listenType=tcp/udp/https/stcp/... but NOT listenType=http/sudp
  * listenAddr+listenPort(int) OK
  * domains=null or [] or [single] OK
  * subRules=null or [] or [null] OK, but subRules=[{}] PANIC
  * subRules=[{id,status}] OK (minimum subrule element)
  * backends=null or [] OK, but backends=[{}] PANIC
  * backends=[{id,status}] OK (minimum backend element)
  * backends=[{id,status,addr/host+port/address+port}] OK (addr strings OK)
  * backends=[{id,status,addr,weight(int)}] PANIC (weight name is wrong or type mismatch)

So weight field doesn't exist, or is not "weight". Maybe "priority"? "wrr"?

Goal: Find smallest body that produces ret=0 (success) on PUT.

Algorithm: binary search. Build up the body incrementally and verify each field
added produces non-500. If we achieve non-500 but not ret=0, print the message
which tells us required fields.
"""
import json
import time
import urllib.request
import urllib.parse
import subprocess
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_lucky_setup import SimpleWS, cdp_call, get_pages, new_page


def restart_lucky():
    subprocess.run(["pkill", "-9", "-f", "lucky"], check=False)
    time.sleep(2)
    os.makedirs("/goodluck", exist_ok=True)
    subprocess.Popen(
        ["nohup", "/opt/lucky_v2.13.4", "-c", "/goodluck/lucky.conf"],
        cwd="/goodluck",
        stdout=open("/tmp/lucky.log", "w"),
        stderr=subprocess.STDOUT,
    )
    time.sleep(8)


def ensure_chrome():
    try:
        get_pages(9333)
    except Exception:
        subprocess.Popen([
            "google-chrome", "--no-sandbox", "--headless", "--disable-gpu",
            "--disable-dev-shm-usage",
            "--remote-debugging-port=9333",
            "--user-data-dir=/tmp/chrome-cdp-profile",
            "about:blank",
        ], stdout=open("/tmp/chrome-cdp.log", "w"), stderr=subprocess.STDOUT)
        time.sleep(8)


def api(TOKEN, method, path, body=None):
    BASE = "http://localhost:16601"
    url = BASE + "/api/" + path
    req = urllib.request.Request(url, method=method)
    req.add_header("Lucky-Admin-Token", TOKEN)
    req.add_header("Accept", "application/json, text/plain, */*")
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            try:
                j = json.loads(text)
                return {"status": resp.status, "json": j}
            except Exception:
                return {"status": resp.status, "text": text[:2000]}
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")[:2000]
        return {"status": e.code, "text": text}
    except Exception as e:
        return {"error": str(e)}


def do_login():
    ensure_chrome()
    page = new_page(9333, "http://localhost:16601/")
    ws = SimpleWS(page["webSocketDebuggerUrl"])
    time.sleep(5)
    login_script = r"""
(async () => {
    const inputs = Array.from(document.querySelectorAll('input'));
    const ai = inputs.find(i => i.placeholder === '默认666' && i.type === 'text');
    const pi = inputs.find(i => i.placeholder === '默认666' && i.type === 'password');
    const setValue = (el, val) => {
        const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        s.call(el, val);
        el.dispatchEvent(new Event('input', {bubbles:true}));
    };
    setValue(ai, '666'); setValue(pi, '666');
    await new Promise(r => setTimeout(r, 400));
    const btns = Array.from(document.querySelectorAll('button'));
    const loginBtn = btns.find(b => /登录|Login/.test(b.textContent || ''));
    if (loginBtn) loginBtn.click();
    await new Promise(r => setTimeout(r, 3000));
    const lucky = JSON.parse(localStorage.getItem('lucky') || '{}');
    return {token: lucky.token || null};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": login_script, "returnByValue": True, "awaitPromise": True}, timeout=60)
    login_res = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    TOKEN = login_res.get("token")
    ws.close()
    return TOKEN


# Candidates for field name variations
STATUS_VALUES = ["disable"]  # we know disable is non-500
# We'll try enable after we have all required fields
LISTEN_TYPES = ["tcp", "http"]  # we know tcp is non-500


def attempt(token, method, path, body, desc):
    time.sleep(0.5)
    r = api(token, method, path, body=body)
    status = r.get("status")
    j = r.get("json") if isinstance(r.get("json"), dict) else {}
    txt = r.get("text", "")
    if j:
        msg = f"ret={j.get('ret')} msg={str(j.get('msg',''))[:400]}"
        if "data" in j and j["data"]:
            msg += f" data={str(j['data'])[:300]}"
    else:
        msg = f"text={txt[:400]}"
    print(f"  {method:>5} /api/{path:<22} [{desc:70}] -> HTTP {status:3} {msg}")
    return status, j


def main():
    # Build up candidates. Each body has all REQUIRED top-level fields: id,status,listenAddr,listenPort,listenType,domains,subRules,ruleGroup?
    # We need to find which combination succeeds.
    candidate_bodies = []
    # Known minimum (proven non-500 individually):
    # +id(0) +status(disable) +listenType(tcp) +listenAddr(0.0.0.0) +listenPort(int) +domains([]) +subRules([{id,status}])
    min_subrule = {"id": 0, "status": "disable"}
    min_backend = {"id": 0, "status": "disable"}
    min_subrule_with_backend_null = {"id": 0, "status": "disable", "backends": None}
    min_subrule_with_backends_empty = {"id": 0, "status": "disable", "backends": []}
    min_subrule_with_backend = {"id": 0, "status": "disable", "backends": [dict(min_backend)]}
    min_subrule_with_backend_addr = {"id": 0, "status": "disable", "remark": "main", "domain": "", "path": "/",
                                      "backends": [{"id": 0, "status": "disable", "addr": "127.0.0.1:8080"}]}
    # Field variations
    subrule_fields_variants = [
        min_subrule,
        min_subrule_with_backend_null,
        min_subrule_with_backends_empty,
        min_subrule_with_backend,
        min_subrule_with_backend_addr,
    ]
    for sr in subrule_fields_variants:
        for status in ["disable", "enable"]:
            for listenType in ["tcp", "http"]:
                for dom in [["canival.fyi"]]:
                    base = {
                        "id": 0, "status": status, "listenType": listenType,
                        "listenAddr": "0.0.0.0", "listenPort": 8083,
                        "domains": list(dom),
                        "subRules": [dict(sr)],
                    }
                    # Add optional fields one-by-one and also include some likely fields
                    # we haven't tried but strings from other modules suggest:
                    for extra in [
                        {},
                        {"name": "NEXA"},
                        {"comment": "NEXA"},
                        {"remark": "NEXA"},
                        {"groupName": ""},
                        {"groupId": 0},
                        {"ruleGroup": ""},
                        {"ssl": "disable"},
                        {"useSSL": False},
                        {"tls": "disable"},
                        {"http2https": "disable"},
                        {"https2http": "disable"},
                        {"httpsRedirect": "disable"},
                        {"listenHTTP": True},
                        {"listenHTTPS": False},
                        {"httpPort": 8083},
                        {"httpsPort": 0},
                        {"certName": ""},
                        {"certId": 0},
                        {"balance": "roundrobin"},
                        {"lbType": "roundrobin"},
                        {"balanceType": "rr"},
                        {"sticky": "disable"},
                        {"healthCheck": "disable"},
                        {"realIpFromHeader": "disable"},
                        {"realIpHeader": "X-Forwarded-For"},
                        {"maxBodySize": 0},
                        {"websocket": "disable"},
                        {"forwardHost": "disable"},
                        {"useTargetHostHeader": False},
                        {"addForwardedHeaders": True},
                        {"enabled": True},
                        {"createAt": 0},
                        {"updateAt": 0},
                    ]:
                        body = dict(base)
                        body.update(extra)
                        candidate_bodies.append((body, f"s={status} lt={listenType} sub=[...keys={list(sr.keys())}] extra={list(extra.keys())}"))

    print(f"\nPrepared {len(candidate_bodies)} candidate bodies. Attempting each with fresh lucky restart...")
    # Only try first N (it will be slow). Limit to reasonable amount ~50.
    # To reduce count, iterate systematically instead of this:
    return

    results = []
    success = False
    for idx, (body, desc) in enumerate(candidate_bodies[:120]):
        restart_lucky()
        token = do_login()
        if not token:
            continue
        status, j = attempt(token, "PUT", "webservice/rule/0", body, f"#{idx:03d} {desc}")
        # Also GET /api/webservice/rules to see if something was created
        time.sleep(1)
        r1 = api(token, "GET", "webservice/rules")
        rj = r1.get("json") if isinstance(r1.get("json"), dict) else {}
        rules = rj.get("ruleList") or rj.get("list") or []
        n_rules = len(rules) if isinstance(rules, list) else 0
        if status != 500 and status != 404 and status != 429:
            results.append((idx, status, j, n_rules, body, desc))
        if n_rules > 0 or (isinstance(j, dict) and j.get("ret") == 0):
            print(f"  === SUCCESS! idx={idx} rules={n_rules} ===")
            print(json.dumps(body, ensure_ascii=False, indent=2))
            if rules:
                print(f"Created rule content: {json.dumps(rules[0], ensure_ascii=False, indent=2)[:2000]}")
            success = True
            break

    print(f"\n--- Summary of non-500 results ({len(results)}): ---")
    for idx, status, j, nr, body, desc in results:
        print(f"  idx={idx:03d} HTTP {status:3} ret={j.get('ret') if isinstance(j, dict) else None} msg={str(j.get('msg','') if isinstance(j, dict) else '')[:200]} n_rules={nr} [{desc}]")
    if not success:
        print("Not yet. Keep trying with variations...")


if __name__ == "__main__":
    sys.exit(main() or 0)
