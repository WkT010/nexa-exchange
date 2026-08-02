#!/usr/bin/env python3
"""
We have good data so far:
- body -> HTTP 500 means that body panics the server (likely wrong field type,
  or missing a required slice that we pass nil instead of [] or similar)
- body -> HTTP 429 means the previous request was accepted enough not to crash
  (but then rate-limit kicked in, which is good)

So we know which bodies DO NOT cause a panic. Let's refine:

Bodies that caused 500 (bad, avoid):
  status=enable alone          -> (wait, that was first) Actually status=enable,status=0 caused 500
  listenType=http              -> 500 (http alone)
  listenType=sudp              -> 500
  base (status only)           -> 500
  + listenAddr                 -> 500
  subRules=[{}]                -> 500
  backends=[{}]                -> 500
  full + backends with weight  -> 500

Bodies that caused 429 (good, got parsed OK enough to count):
  status=disable/1/true/...
  listenType=tcp/udp/https/HTTPS/TCP/UDP/stcp/shttp/sni/ssh/ws/wss
  + domains=null/[]/[canival.fyi]
  + listenPort(int)
  + listenAddr + listenPort (combined)
  + base (no subRules), subRules=null, subRules=[], subRules=[null]
  + subRules=[{id,status}], +remark, +path, +domain
  + backends=null, backends=[]
  + backends=[{id,status}], +addr, +host/port, +address/port
  + address, backend, upstream, target

Interesting: status=enable (string) causes 500. status=disable is OK via 429.
So "enable" as a status value for a top-level field is WRONG? Or maybe we're missing
a required field when status="enable" that's not required for disable?

Also: listenType=http -> 500 (alone), but combined with other fields it might be OK?
Actually phase 4 line "+ listenAddr + listenPort" 429d - but that was with a base that
includes listenType=http. Wait no - let me check: phase 4 base = "base http + domains"
which has listenType=http, and the "+listenAddr+listenPort" appended to it. So that
line was 429 - meaning listenType=http combined with listenAddr+Port+domains is OK.
Great!

Also: subRules=[{}] caused 500. backends=[{}] caused 500. This means each element of
those arrays needs specific fields to not panic. Since backends=[{id,status}] was 429
(OK!), the minimum subrule element needs at least id+status. Good!

And backends with addr as string was OK 429. But adding weight=1 caused 500 - so
weight is probably not int type (maybe float? or string? or not called weight?).

OK now let's write a script that:
1. Re-starts lucky every time (to avoid any 429 issue with clean state, new token, etc.)
2. Sends one request per restart
3. Uses the known safe field values (disable status first to not cause issues, check
   if field values work; since the problem with "enable" being 500 might be coincidence
   from it being the very first request after restart? Let's verify)
4. With known valid shape, then try to create a valid rule.

But first let's just get the rule created. Also, we should use the DevTools MCP which
has a "real" headless Chrome that might render Vue components (CDP headless=new didn't
render the reverse proxy component). The DevTools MCP server is at
mcp_trae-remote-official_plugin_chrome-devtools_chrome-devtools.
Let's use that via run_mcp.
"""
import os
import json
import subprocess
import time
import sys
import urllib.request
import urllib.parse

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


def try_once(body, method="PUT", path="webservice/rule/0", token=None):
    """Send a single request and print result. Returns status code."""
    time.sleep(0.6)
    r = api(token, method, path, body=body)
    status = r.get("status")
    j = r.get("json") if isinstance(r.get("json"), dict) else {}
    txt = r.get("text", "")
    if j:
        msg = f"ret={j.get('ret')} msg={str(j.get('msg',''))[:400]}"
        if "data" in j:
            msg += f" data={str(j['data'])[:300]}"
    else:
        msg = f"text={txt[:400]}"
    print(f"  {method} {path:<26} -> HTTP {status:3} {msg}")
    return status


def main():
    # Strategy A: Use DevTools MCP (chrome-devtools) browser to actually render the UI
    # and click around to capture the request, since our headless Chrome didn't render
    # the reverse proxy page.
    #
    # Before this, strategy B: single-shot rule creation with known-safe body values,
    # restarting lucky fresh for each attempt so we never hit 429 and we know exactly
    # what the response code means.

    # First let's try strategy B: create rule with minimal safe shape and
    # iterate on validation messages.
    # From previous:
    #   - status=enable caused 500 first req after restart? Let's retry:
    #   - actually status=disable was 429 (safe). Try status=disable first and see
    #     if maybe "enable" triggers port binding checks that fail?

    bodies = [
        # Simplest: TCP forward without sub-rules
        ({"id": 0, "status": "disable", "listenType": "tcp",
          "listenAddr": "0.0.0.0", "listenPort": 8082,
          "domains": ["canival.fyi"],
          "subRules": [{"id": 0, "status": "disable", "remark": "main", "path": "/", "domain": "",
                        "backends": [{"id": 0, "status": "disable", "addr": "127.0.0.1:8080"}]}]},
         "TCP, status=disable everywhere"),
        # Same but status=enable top level
        ({"id": 0, "status": "enable", "listenType": "tcp",
          "listenAddr": "0.0.0.0", "listenPort": 8082,
          "domains": ["canival.fyi"],
          "subRules": [{"id": 0, "status": "enable", "remark": "main", "path": "/", "domain": "",
                        "backends": [{"id": 0, "status": "enable", "addr": "127.0.0.1:8080"}]}]},
         "TCP, status=enable everywhere"),
        # HTTP variant
        ({"id": 0, "status": "enable", "listenType": "http",
          "listenAddr": "0.0.0.0", "listenPort": 8082,
          "domains": ["canival.fyi"],
          "subRules": [{"id": 0, "status": "enable", "remark": "main", "path": "/", "domain": "",
                        "backends": [{"id": 0, "status": "enable", "addr": "127.0.0.1:8080"}]}]},
         "HTTP, full enable"),
        # Try backend.weight field with different types since int caused 500
        ({"id": 0, "status": "disable", "listenType": "http",
          "listenAddr": "0.0.0.0", "listenPort": 8082,
          "domains": ["canival.fyi"],
          "subRules": [{"id": 0, "status": "disable", "remark": "main", "path": "/", "domain": "",
                        "backends": [{"id": 0, "status": "disable", "addr": "127.0.0.1:8080", "weight": "1"}]}]},
         "weight as string '1'"),
        ({"id": 0, "status": "disable", "listenType": "http",
          "listenAddr": "0.0.0.0", "listenPort": 8082,
          "domains": ["canival.fyi"],
          "subRules": [{"id": 0, "status": "disable", "remark": "main", "path": "/", "domain": "",
                        "backends": [{"id": 0, "status": "disable", "addr": "127.0.0.1:8080", "weight": 1.0}]}]},
         "weight as float 1.0"),
    ]

    for idx, (body, desc) in enumerate(bodies):
        print(f"\n--- Try {idx+1}/{len(bodies)}: {desc} ---")
        restart_lucky()
        token = do_login()
        # First GET /api/webservice/rules to confirm we have empty state
        r0 = api(token, "GET", "webservice/rules")
        rulelist_before = (r0.get("json") or {}).get("ruleList")
        s = try_once(body, "PUT", "webservice/rule/0", token=token)
        # Now check if rule was created
        time.sleep(1.5)
        r1 = api(token, "GET", "webservice/rules")
        j = r1.get("json") or {}
        print(f"  Rules list before: {rulelist_before}, after: ruleList keys={j.get('ruleList') and 'has items' or None} ret={j.get('ret')}")
        if j.get("ruleList"):
            print(f"  Rule list content (first rule): {json.dumps(j['ruleList'][0], ensure_ascii=False)[:1000]}")
            print("🎉 SUCCESS - Rule created!")
            break
        # Also try with POST /api/webservice/rules instead
        # if we haven't already
        s2 = try_once(body, "POST", "webservice/rules", token=token)

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
