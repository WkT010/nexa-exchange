#!/usr/bin/env python3
"""Try to login to Lucky via direct HTTP API (no Chrome needed).
Probe login endpoint and password encryption requirements.
"""
import json
import time
import urllib.request
import urllib.error

BASE = "http://localhost:16601"

def api(method, path, body=None, headers=None):
    url = BASE + "/api/" + path
    if method == "GET":
        url += "?_=" + str(int(time.time() * 1000))
    req = urllib.request.Request(url, method=method)
    req.add_header("Accept", "application/json, text/plain, */*")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=10) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            try:
                return {"status": resp.status, "json": json.loads(text), "text": text[:800]}
            except Exception:
                return {"status": resp.status, "text": text[:800]}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "text": e.read().decode("utf-8", errors="replace")[:800]}
    except Exception as e:
        return {"error": str(e)}


def main():
    print("=== 1. Probe login endpoints (GET) ===")
    for p in ["login", "user/login", "auth/login", "account/login", "info", "baseConfInfo"]:
        r = api("GET", p)
        print(f"  GET /api/{p:<20} -> {r.get('status', r.get('error','?'))} {str(r.get('json',r.get('text','')))[:200]}")

    print("\n=== 2. Try POST login with plaintext password ===")
    bodies = [
        {"account": "666", "password": "666"},
        {"account": "666", "password": "666", "encrypted": False},
        {"username": "666", "password": "666"},
        {"account": "666", "password": "666", "loginType": "account"},
    ]
    for p in ["login", "user/login", "auth/login"]:
        for b in bodies:
            r = api("POST", p, body=b)
            st = r.get("status", "?")
            j = r.get("json", {})
            ret = j.get("ret") if isinstance(j, dict) else None
            msg = j.get("msg") if isinstance(j, dict) else None
            token = j.get("token") if isinstance(j, dict) else None
            # Also check if token is nested in data
            if not token and isinstance(j, dict) and isinstance(j.get("data"), dict):
                token = j["data"].get("token")
            print(f"  POST /api/{p:<15} body={str(b)[:60]:<60} -> {st} ret={ret} msg={msg} token={'YES' if token else 'no'}")
            if token:
                print(f"  [!!!] GOT TOKEN: {token[:60]}...")
                # Quick test: use token to GET info
                r2 = api("GET", "info", headers={"Lucky-Admin-Token": token})
                j2 = r2.get("json", {})
                print(f"  [test] GET /api/info with token -> ret={j2.get('ret') if isinstance(j2,dict) else '?'} {str(j2)[:200]}")
                return token

    print("\n=== 3. Download frontend JS to find login encryption ===")
    try:
        idx = urllib.request.urlopen(BASE + "/static/js/lucky_index-DyslG9Ot.js", timeout=10).read().decode("utf-8", errors="replace")
        import re
        # Find login-related chunk files
        login_chunks = sorted(set(re.findall(r'lucky_[A-Za-z0-9_-]*[Ll]ogin[A-Za-z0-9_-]*\.js', idx) or []))
        if not login_chunks:
            login_chunks = sorted(set(re.findall(r'lucky_[A-Za-z0-9_-]*\.js', idx) or []))
            login_chunks = [c for c in login_chunks if 'login' in c.lower() or 'account' in c.lower() or 'user' in c.lower()]
        print(f"  login-related chunks: {login_chunks[:10]}")
        # Also find all chunks
        all_chunks = sorted(set(re.findall(r'lucky_[A-Za-z0-9_-]+\.js', idx) or []))
        print(f"  all chunks ({len(all_chunks)}): {all_chunks[:30]}")
        # Look for 'login' or 'encrypt' or 'password' in index JS
        for kw in ['/api/login', '/api/user', 'encrypt', 'CryptoJS', 'AES', 'loginByAccount']:
            matches = [m.start() for m in re.finditer(re.escape(kw), idx)]
            if matches:
                for pos in matches[:2]:
                    snippet = idx[max(0,pos-40):pos+80].replace('\n',' ')
                    print(f"  [{kw}] ...{snippet}...")
    except Exception as e:
        print(f"  error reading index JS: {e}")

    return None


if __name__ == "__main__":
    token = main()
    if token:
        print(f"\n[SUCCESS] token={token[:40]}...")
    else:
        print("\n[FAIL] could not get token via API")
