#!/usr/bin/env python3
"""
We know so far:
- DELETE /api/webservice/rule/<id> works (deletes rule by numeric ID)
- GET /api/webservice/rule/<id>  -> returns ret=12 (ItemNotFoundForKey) if id missing. Good.
- PUT /api/webservice/rule/<id> -> we got:
    * {}                         -> HTTP 500 (panic: required fields, probably slices/arrays with wrong types)
    * {id:0,listenPort:"8081"}   -> HTTP 400 请求解析出错 (so listenPort type is wrong, needs int)
    * {id:0,subRules:[]}         -> HTTP 500 (maybe subRules is not empty-array-ok? needs specific elem fields?)
    * {id:0,listenType:HTTPS}    -> HTTP 500
    * {id:0, upstream: field}    -> HTTP 500

So there are specific fields that cause panics. We need to enumerate which exact field sets
cause NO 500. The pattern: empty body 500 means unmarshalling into a Go struct with
certain array fields or struct fields that panic on zero-val or nil.

Go trick: If a struct has a field of type `[]*struct{...}` (slice of pointers),
passing an empty array `[]` is OK, but if a sub-struct has required fields, we might
still panic. Passing `null` for a slice also might be OK vs `[]`.

Goal: Find the smallest set of top-level fields that cause NOT 500 (either OK or validation error).

Approach: Probe field by field, restart lucky after every HTTP 500 to avoid corrupt state.
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
        with urllib.request.urlopen(req, data=data, timeout=10) as resp:
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


def main():
    restart_lucky()
    TOKEN = [do_login()]
    print(f"[+] Token: {'ok' if TOKEN[0] else 'NONE'}")
    if not TOKEN[0]:
        return 1

    def try_body(body, desc, restart_if_500=True):
        time.sleep(0.4)
        r = api(TOKEN[0], "PUT", "webservice/rule/0", body=body)
        status = r.get("status")
        j = r.get("json") if isinstance(r.get("json"), dict) else {}
        txt = r.get("text", "")
        if j:
            msg = f"ret={j.get('ret')} msg={str(j.get('msg',''))[:200]}"
            if "data" in j:
                msg += f" data={str(j['data'])[:200]}"
        else:
            msg = f"text={txt[:200]}"
        print(f"  PUT rule/0 [{desc:65}] -> HTTP {status:3} {msg}")
        if status == 500 and restart_if_500:
            # 500s often mean the Go server panics. Sometimes it recovers. Not always, so re-login after 500.
            time.sleep(0.6)
        return status

    # Goal: Find fields that turn 500 into a different status.
    # We know empty body = 500. So add fields one by one and check.
    # First find what status & listenType enum values it expects without causing 500.
    print("\n=== Phase 1: status field enum values ===")
    for v in ["enable", "disable", "enabled", "disabled", "on", "off", "1", "0", "true", "false", "running", "stopped"]:
        try_body({"id": 0, "status": v}, f"status={v}")

    # After each batch, check server still alive by calling GET info
    def healthcheck():
        r = api(TOKEN[0], "GET", "info")
        if isinstance(r.get("json"), dict) and r["json"].get("ret") == 0:
            return True
        print("  [HC FAIL - restarting lucky and re-login]")
        restart_lucky()
        TOKEN[0] = do_login()
        return False

    healthcheck()
    print("\n=== Phase 2: listenType enum values ===")
    for v in ["tcp", "udp", "http", "https", "HTTP", "HTTPS", "TCP", "UDP", "stcp", "sudp", "shttp", "httptlssni", "sni", "ssh", "ws", "wss"]:
        try_body({"id": 0, "status": "enable", "listenType": v}, f"status=enable, listenType={v}")
    healthcheck()

    print("\n=== Phase 3: Find if 'domains' is []/null/string ===")
    for body, desc in [
        ({"id": 0, "status": "enable"}, "base (status)"),
        ({"id": 0, "status": "enable", "listenType": "http"}, "listenType=http"),
        ({"id": 0, "status": "enable", "listenType": "http", "domains": None}, "+ domains=null"),
        ({"id": 0, "status": "enable", "listenType": "http", "domains": []}, "+ domains=[]"),
        ({"id": 0, "status": "enable", "listenType": "http", "domains": ["canival.fyi"]}, "+ domains=[single]"),
        ({"id": 0, "status": "enable", "listenType": "tcp", "domains": []}, "tcp + domains=[]"),
    ]:
        try_body(body, desc)
    healthcheck()

    print("\n=== Phase 4: listenAddr / listenPort (with proper types) ===")
    for body, desc in [
        ({"id": 0, "status": "enable", "listenType": "http", "domains": ["canival.fyi"]}, "base http + domains"),
        ({"id": 0, "status": "enable", "listenType": "http", "domains": ["canival.fyi"], "listenAddr": "0.0.0.0"}, "+ listenAddr"),
        ({"id": 0, "status": "enable", "listenType": "http", "domains": ["canival.fyi"], "listenPort": 8081}, "+ listenPort(int)"),
        ({"id": 0, "status": "enable", "listenType": "http", "domains": ["canival.fyi"], "listenAddr": "0.0.0.0", "listenPort": 8081}, "+ listenAddr + listenPort"),
    ]:
        try_body(body, desc)
    healthcheck()

    print("\n=== Phase 5: find which 'backends' field shape in subRules avoids 500 ===")
    # Try with no subRules field first (omit) vs subRules=null vs subRules=[]
    base = {"id": 0, "status": "enable", "listenType": "http", "domains": ["canival.fyi"], "listenAddr": "0.0.0.0", "listenPort": 8081}
    for body, desc in [
        (base, "base (no subRules field)"),
        ({**base, "subRules": None}, "subRules=null"),
        ({**base, "subRules": []}, "subRules=[]"),
        ({**base, "subRules": [None]}, "subRules=[null]"),
        ({**base, "subRules": [{}]}, "subRules=[{}]"),
        ({**base, "subRules": [{"id": 0, "status": "enable"}]}, "subRules=[{id,status}]"),
        ({**base, "subRules": [{"id": 0, "status": "enable", "remark": "main"}]}, "+ remark"),
        ({**base, "subRules": [{"id": 0, "status": "enable", "remark": "main", "path": "/"}]}, "+ path"),
        ({**base, "subRules": [{"id": 0, "status": "enable", "remark": "main", "path": "/", "domain": ""}]}, "+ domain"),
        # Backends variations
        ({**base, "subRules": [{"id": 0, "status": "enable", "remark": "main", "path": "/", "domain": "", "backends": None}]}, "+ backends=null"),
        ({**base, "subRules": [{"id": 0, "status": "enable", "remark": "main", "path": "/", "domain": "", "backends": []}]}, "+ backends=[]"),
        ({**base, "subRules": [{"id": 0, "status": "enable", "remark": "main", "path": "/", "domain": "", "backends": [{}]}]}, "+ backends=[{}]"),
        ({**base, "subRules": [{"id": 0, "status": "enable", "remark": "main", "path": "/", "domain": "",
                                "backends": [{"id": 0, "status": "enable"}]}]}, "+ backends=[{id,status}]"),
        ({**base, "subRules": [{"id": 0, "status": "enable", "remark": "main", "path": "/", "domain": "",
                                "backends": [{"id": 0, "status": "enable", "addr": "127.0.0.1:8080"}]}]}, "+ backend addr"),
        ({**base, "subRules": [{"id": 0, "status": "enable", "remark": "main", "path": "/", "domain": "",
                                "backends": [{"id": 0, "status": "enable", "host": "127.0.0.1", "port": 8080}]}]}, "+ backend host/port"),
        ({**base, "subRules": [{"id": 0, "status": "enable", "remark": "main", "path": "/", "domain": "",
                                "backends": [{"id": 0, "status": "enable", "address": "127.0.0.1", "port": 8080}]}]}, "+ backend address/port"),
    ]:
        try_body(body, desc)
    healthcheck()

    print("\n=== Phase 6: if we got a validation error instead of 500, inspect field names ===")
    # Repeat the last one which was best with slight field renames
    best_candidate = {"id": 0, "status": "enable", "listenType": "http", "domains": ["canival.fyi"],
                      "listenAddr": "0.0.0.0", "listenPort": 8081,
                      "subRules": [{"id": 0, "status": "enable", "remark": "main", "path": "/", "domain": "",
                                    "backends": [{"id": 0, "status": "enable", "addr": "127.0.0.1:8080"}]}]}
    # Try this first to see status
    s = try_body(best_candidate, "FULL CANDIDATE v1")
    healthcheck()
    # If 500, try with different names:
    print("\n=== Phase 7: Alternative field names for backend ===")
    import copy
    for backend_field_shapes in [
        [{"id": 0, "status": "enable", "addr": "127.0.0.1:8080"}],
        [{"id": 0, "status": "enable", "addr": "127.0.0.1:8080", "weight": 1}],
        [{"id": 0, "status": "enable", "address": "127.0.0.1:8080"}],
        [{"id": 0, "status": "enable", "backend": "127.0.0.1:8080"}],
        [{"id": 0, "status": "enable", "host": "127.0.0.1", "port": 8080}],
        [{"id": 0, "status": "enable", "hostname": "127.0.0.1", "port": 8080}],
        [{"id": 0, "status": "enable", "upstream": "127.0.0.1:8080"}],
        [{"id": 0, "status": "enable", "target": "127.0.0.1:8080"}],
    ]:
        b = copy.deepcopy(best_candidate)
        b["subRules"][0]["backends"] = backend_field_shapes
        s = try_body(b, f"backends={backend_field_shapes}")

    # Finally GET /api/webservice/rules to see if any rule was created (ret=0 success)
    healthcheck()
    print("\n=== GET /api/webservice/rules (final state) ===")
    r = api(TOKEN, "GET", "webservice/rules")
    print(json.dumps(r.get("json", {}), ensure_ascii=False, indent=2)[:600])

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
