
import argparse
import base64
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.parse

CRYPT = {
    "REQUEST_CRYPT_2": "bAIgvwAuA4tbDr9d",      
    "X_TOKEN_IV": "9791027341711819",            
    "KEY_14": "tVkdaRWRY0ZkV1Vr",                
    "CRYPT_14_IV": "VjFSQ1ZtVkQxRTlQ",           
    "RESPONSE_KEY_14": "RYV0hCV1lV25KYVJ",       
    "SIGN_SALT": "_Leadeon/SecurityOrganization",
    "RSA_N_HEX": "968E9ACF9E59B4E2E1BB24266EE39043788A45F788ECDC5C971F4964C3267CF20AFD3B7F029B68A9A9B65D77D0306B8319DF0C174F3DD82EF3894A6C38E23634F6095A81901AD7E6650911C0910F12C7DE50A6FCEE3AE3563CC5985C46A965DB2AF49E94F69B62F67FF3D5C0F79782572375E5F8B44AA43C0CA6D48E8A969BEB",
    "RSA_E": 0x10001,
}

AUTOLOGIN_URL = "https://client.app.coc.10086.cn/biz-orange/LN/uamrandcodelogin/autoLogin"
SSO_LOGIN = "https://wx.10086.cn/qwhdsso/login"
BASE = "https://wx.10086.cn"
DEFAULT_ACT_URL = BASE + "/qwhdhub/qwhdmark/1021122301?channelId=P00000150517&yx=1569511002"

UA_NATIVE = "okhttp/3.14.9 ChinaMobile/12.5.6 (Linux; Android 12; M2011K2C)"
UA_WEB = ("Mozilla/5.0 (Linux; Android 12; M2011K2C Build/SKQ1.211006.001; wv) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/121.0.6167.71 "
          "MQQBrowser/6.2 TBS/048437 Mobile Safari/537.36 leadeon/12.5.6/CMCCIT")

AES_SBOX = [
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16
]
AES_INV_SBOX = [0] * 256
for _i, _v in enumerate(AES_SBOX):
    AES_INV_SBOX[_v] = _i
_AES_RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36]


def _aes_gmul(a, b):
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return r


def _aes_expand_key(kb):
    w = [list(kb[i * 4:i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = [AES_SBOX[t[1]], AES_SBOX[t[2]], AES_SBOX[t[3]], AES_SBOX[t[0]]]
            t[0] ^= _AES_RCON[i // 4 - 1]
        w.append([t[j] ^ w[i - 4][j] for j in range(4)])
    return w


def _aes_enc_block(blk, w):
    st = [[blk[r + 4 * c] for c in range(4)] for r in range(4)]
    for c in range(4):
        for r in range(4):
            st[r][c] ^= w[c][r]
    for rnd in range(1, 11):
        for r in range(4):
            for c in range(4):
                st[r][c] = AES_SBOX[st[r][c]]
        for r in range(1, 4):
            st[r] = st[r][r:] + st[r][:r]
        if rnd != 10:
            for c in range(4):
                a = [st[r][c] for r in range(4)]
                st[0][c] = _aes_gmul(a[0],2) ^ _aes_gmul(a[1],3) ^ a[2] ^ a[3]
                st[1][c] = a[0] ^ _aes_gmul(a[1],2) ^ _aes_gmul(a[2],3) ^ a[3]
                st[2][c] = a[0] ^ a[1] ^ _aes_gmul(a[2],2) ^ _aes_gmul(a[3],3)
                st[3][c] = _aes_gmul(a[0],3) ^ a[1] ^ a[2] ^ _aes_gmul(a[3],2)
        for c in range(4):
            for r in range(4):
                st[r][c] ^= w[4 * rnd + c][r]
    out = []
    for c in range(4):
        for r in range(4):
            out.append(st[r][c])
    return out


def _aes_dec_block(blk, w):
    st = [[blk[r + 4 * c] for c in range(4)] for r in range(4)]
    for c in range(4):
        for r in range(4):
            st[r][c] ^= w[40 + c][r]
    for rnd in range(9, 0, -1):
        for r in range(1, 4):
            st[r] = st[r][-r:] + st[r][:-r]
        for r in range(4):
            for c in range(4):
                st[r][c] = AES_INV_SBOX[st[r][c]]
        for c in range(4):
            for r in range(4):
                st[r][c] ^= w[4 * rnd + c][r]
        for c in range(4):
            a0, a1, a2, a3 = st[0][c], st[1][c], st[2][c], st[3][c]
            st[0][c] = _aes_gmul(a0,14) ^ _aes_gmul(a1,11) ^ _aes_gmul(a2,13) ^ _aes_gmul(a3,9)
            st[1][c] = _aes_gmul(a0,9) ^ _aes_gmul(a1,14) ^ _aes_gmul(a2,11) ^ _aes_gmul(a3,13)
            st[2][c] = _aes_gmul(a0,13) ^ _aes_gmul(a1,9) ^ _aes_gmul(a2,14) ^ _aes_gmul(a3,11)
            st[3][c] = _aes_gmul(a0,11) ^ _aes_gmul(a1,13) ^ _aes_gmul(a2,9) ^ _aes_gmul(a3,14)
    for r in range(1, 4):
        st[r] = st[r][-r:] + st[r][:-r]
    for r in range(4):
        for c in range(4):
            st[r][c] = AES_INV_SBOX[st[r][c]]
    for c in range(4):
        for r in range(4):
            st[r][c] ^= w[c][r]
    out = []
    for c in range(4):
        for r in range(4):
            out.append(st[r][c])
    return out


def _aes_cbc_encrypt_pp(plain, key, iv):
    w = _aes_expand_key(key.encode())
    prev = list(iv.encode())
    data = plain.encode("utf-8")
    pad = 16 - len(data) % 16
    data += bytes([pad]) * pad
    out = []
    for off in range(0, len(data), 16):
        blk = [data[off + j] ^ prev[j] for j in range(16)]
        cb = _aes_enc_block(blk, w)
        out += cb
        prev = cb
    return base64.b64encode(bytes(out)).decode()


def _aes_cbc_decrypt_pp(data, key, iv):
    w = _aes_expand_key(key.encode())
    prev = list(iv.encode())          
    out = []
    for off in range(0, len(data), 16):
        cblock = list(data[off:off + 16])
        dblock = _aes_dec_block(cblock, w)
        out += [dblock[i] ^ prev[i] for i in range(16)]
        prev = cblock                   
    return bytes(out)


try:
    from Crypto.Cipher import AES as _PyCryptoAES

    def aes_cbc_encrypt(plain: str, key: str, iv: str) -> str:
        data = plain.encode("utf-8")
        pad = 16 - len(data) % 16
        data = data + bytes([pad]) * pad
        c = _PyCryptoAES.new(key.encode(), _PyCryptoAES.MODE_CBC, iv.encode())
        return base64.b64encode(c.encrypt(data)).decode()
except ImportError:
    def aes_cbc_encrypt(plain: str, key: str, iv: str) -> str:
        return _aes_cbc_encrypt_pp(plain, key, iv)


def aes_cbc_decrypt(b64: str, key: str, iv: str) -> str:
    data = base64.b64decode(b64)
    try:
        from Crypto.Cipher import AES as _A
        c = _A.new(key.encode(), _A.MODE_CBC, iv.encode())
        p = c.decrypt(data)
    except ImportError:
        p = _aes_cbc_decrypt_pp(data, key, iv)
    pad = p[-1] if p else 0
    if 1 <= pad <= 16 and len(p) >= pad:
        p = p[:-pad]
    return p.decode("utf-8", "replace")



def rsa_encrypt(text: str) -> str:
    n = int(CRYPT["RSA_N_HEX"], 16)
    e = CRYPT["RSA_E"]
    k = (n.bit_length() + 7) // 8
    msg = text.encode("utf-8")
    ps_len = k - 3 - len(msg)
    ps = bytearray()
    while len(ps) < ps_len:
        b = random.randint(1, 255)
        ps.append(b)
    em = b"\x00\x02" + bytes(ps) + b"\x00" + msg
    m = int.from_bytes(em, "big")
    c = pow(m, e, n)
    return base64.b64encode(c.to_bytes(k, "big")).decode()

def md5hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def _http_via_curl_cmd(method, url, headers=None, data=None, timeout=25):
    import shutil
    import subprocess
    if not shutil.which("curl"):
        return None
    cmd = ["curl", "-sS", "-i", "--compressed", "--max-time", str(int(timeout)),
           "-A", "ChinaMobile/12.5.6 (Linux; Android 12) okhttp/3.14.9",
           "-X", method]
    cmd += ["--noproxy", "*"]
    for k, v in (headers or {}).items():
        if k.lower() in ("content-length", "host"):
            continue
        cmd += ["-H", "%s: %s" % (k, v)]
    if data:
        cmd += ["--data-binary", "@-"]
    cmd.append(url)
    try:
        p = subprocess.run(cmd, input=data if data else None,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout + 8)
    except Exception:
        return None
    raw = p.stdout or b""
    if not raw:
        err = (p.stderr or b"").decode("utf-8", "replace")[:160]
        return 0, {}, "curl 命令失败: %s" % err
    head, _, body = raw.partition(b"\r\n\r\n")
    if not _:
        head, _, body = raw.partition(b"\n\n")
    try:
        lines = head.decode("utf-8", "replace").splitlines()
    except Exception:
        lines = []
    status = 0
    if lines:
        m = re.search(r"HTTP/[\d.]+\s+(\d{3})", lines[0])
        if m:
            status = int(m.group(1))
    hd = {}
    cookies = []
    for ln in lines[1:]:
        if ":" not in ln:
            continue
        k, _, v = ln.partition(":")
        k = k.strip()
        v = v.strip()
        if k.lower() == "set-cookie":
            cookies.append(v)
        else:
            hd[k] = v
    if cookies:
        hd["set-cookie"] = "; ".join(cookies)
    return status, hd, body.decode("utf-8", "replace")


def http_req(method, url, headers=None, data=None, timeout=25):
    try:
        from curl_cffi import requests as creq
    except ImportError:
        creq = None

    if creq is not None:
        try:
            s = creq.Session(impersonate="chrome120", trust_env=False)
            r = s.request(method, url, headers=headers, data=data, timeout=timeout)
            return r.status_code, r.headers, r.text
        except Exception as ex:
            return 0, {}, "curl_cffi 请求失败: %s: %s" % (type(ex).__name__, ex)

    try:
        r = _http_via_curl_cmd(method, url, headers, data, timeout)
        if r is not None:
            if r[0] == 0:
                return r
            return r
    except Exception:
        pass

    import urllib.request, urllib.error, gzip as _g
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        resp = opener.open(req, timeout=timeout)
        body = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            body = _g.decompress(body)
        return resp.status, dict(resp.headers), body.decode("utf-8", "replace")
    except urllib.error.HTTPError as ex:
        body = ex.read()
        try:
            if ex.headers.get("Content-Encoding") == "gzip":
                body = _g.decompress(body)
        except Exception:
            pass
        return ex.code, dict(ex.headers), body.decode("utf-8", "replace")
    except Exception as ex:
        return 0, {}, "urllib 请求失败: %s: %s" % (type(ex).__name__, ex)


def http_selftest(target="https://client.app.coc.10086.cn/"):
    import shutil
    try:
        import curl_cffi
        dep = "curl_cffi %s" % getattr(curl_cffi, "__version__", "?")
        transport = "curl_cffi"
    except ImportError:
        if shutil.which("curl"):
            dep = "curl_cffi 未安装 → 改用系统 curl 兜底（可用）"
            transport = "系统curl"
        else:
            dep = "curl_cffi 未安装且无系统 curl → 只能 urllib（可能被 WAF 拦）"
            transport = "urllib"
    st, _h, body = http_req("GET", target, None, None, timeout=12)
    return "%s | 传输方式: %s" % (dep, transport), st, (body or "")[:120]

def get_setcookies(headers) -> str:
    v = headers.get("set-cookie", "") if hasattr(headers, "get") else ""
    if isinstance(v, (list, tuple)):
        return "; ".join(v)
    return str(v)

def mask(s, keep=12):
    s = str(s)
    return s[:keep] + "...<len=%d>" % len(s) if len(s) > keep * 2 else s

def build_autologin(params: dict, phone: str):
    xk = params.get("xk", "")
    x_time = str(int(time.time() * 1000))
    x_nonce = str(random.randint(10000000, 99999999))
    pathname = urllib.parse.urlsplit(AUTOLOGIN_URL).path

    token_plain = xk + "_" + pathname + "_" + x_time + "_" + x_nonce
    token_enc = aes_cbc_encrypt(token_plain, CRYPT["REQUEST_CRYPT_2"], CRYPT["X_TOKEN_IV"])

    AUX = {"phone", "province_code", "city_code", "ticketID", "jsessionid", "uid", "host"}
    body_obj = {k: v for k, v in params.items() if k not in AUX and v is not None}
    sys_time = str(int(time.time()))
    cn = time.gmtime(int(sys_time) + 8 * 3600)
    ts14 = time.strftime("%Y%m%d%H%M%S", cn)
    req_body = dict(body_obj.get("reqBody") or {})
    req_body.pop("cellNum", None)
    req_body.pop("verifyCode", None)
    req_body.pop("devToken", None)
    req_body["sysTime"] = sys_time
    req_body["cellNum"] = rsa_encrypt("leadeon" + phone + ts14)
    req_body.setdefault("pageUrl", "overtime")
    req_body.setdefault("reqSource", "init")
    req_body.setdefault("channelId", "1")
    req_body.setdefault("sendSmsFlag", "0")
    body_obj["reqBody"] = req_body
    body_obj["tel"] = phone
    body_json = json.dumps(body_obj, ensure_ascii=False, separators=(",", ":"))
    body_final = aes_cbc_encrypt(body_json, CRYPT["KEY_14"], CRYPT["CRYPT_14_IV"])

    xs = md5hex(AUTOLOGIN_URL + "_" + body_json + CRYPT["SIGN_SALT"])
    x_sign = md5hex(token_enc + "_" + x_time + "_" + x_nonce + "_null")

    headers = {
        "Content-Type": "application/Json",
        "x-qen": "14",
        "x-time": x_time,
        "x-nonce": x_nonce,
        "xs": xs,
        "x-token": token_enc,
        "x-sign": x_sign,
        "User-Agent": UA_NATIVE,
        "Accept": "*/*",
        "accept-encoding": "deflate",
        "accept-language": "zh-Hans-US;q=1, en-US;q=0.9",
    }
    return {"url": AUTOLOGIN_URL, "method": "POST", "headers": headers, "body": body_final}

def run_autologin(params: dict, phone: str, dry_run=False):
    req = build_autologin(params, phone)
    if dry_run:
        print("\n===== [1] autoLogin 请求预览（dry-run）=====")
        print(req["method"], req["url"])
        for k, v in req["headers"].items():
            print("  %s: %s" % (k, mask(v, 48) if k in ("x-token", "xs", "x-sign") else v))
        print("  body: " + mask(req["body"], 64))
        return None
    status, headers, body = http_req("POST", req["url"], req["headers"], req["body"].encode())
    sc = get_setcookies(headers)
    jsid = (re.search(r"JSESSIONID=([^;,]+)", sc) or [None, ""])[1]
    uid = (re.search(r"(?:^|[;,]\s*)UID=([^;,]+)", sc) or [None, ""])[1]
    ticket = (re.search(r"ticketID=([^;,]+)", sc) or [None, ""])[1]
    print("[1] autoLogin: HTTP %s" % status)
    if jsid and uid:
        app_token = ("JSESSIONID=%s; UID=%s; Comment=SessionServer-unity; "
                     "Path=/;HTTPOnly; ticketID=%s; Secure" % (jsid, uid, ticket or "POD9"))
        print("    新 app_token: %s" % mask(app_token, 30))
        return app_token
    desc = ""
    ret_code = ""
    try:
        from Crypto.Cipher import AES as _A
        raw = base64.b64decode(body)
        c = _A.new(CRYPT["RESPONSE_KEY_14"].encode(), _A.MODE_CBC, CRYPT["CRYPT_14_IV"].encode())
        p = c.decrypt(raw)
        o = json.loads(p[:-p[-1]].decode("utf-8", "replace"))
        desc = o.get("retDesc", "")
        ret_code = str(o.get("retCode", ""))
        vt = (o.get("rspBody") or {}).get("validityTerm", "")
        print("    retCode=%s retDesc=%s validityTerm=%s" % (ret_code, desc, vt))
    except Exception as ex:
        print("    响应解密失败(%r)，body: %s" % (ex, mask(body, 80)))

    if ret_code == "420000" or "其他设备" in desc:
        raise SystemExit(
            "autoLogin 失败: %s\n"
            "    原因：xk 已失效 —— 同一号码在别的设备/更晚的一次登录后，旧 xk 会被作废（单端登录策略）。\n"
            "    解法：在**当前已登录的那台设备**上重新抓一次登录流量，用 --from-har 生成新凭据：\n"
            "      ① 强制停止移动 App → 重新打开（会触发 autoLogin，抓它最稳）\n"
            "      ② 若直接跳到登录页，则重新登录一次，抓 uam*login 请求\n"
            "    注意：抓完不要再在其它设备登录，否则 xk 再次作废。" % (desc or status))
    raise SystemExit("autoLogin 失败: %s" % (desc or status))

def mint_session(app_token, phone, province, city, act_url, dry_run=False, quiet=False):
    app_ver = "12.5.6"
    u1 = SSO_LOGIN + "?dlwmh=true&actUrl=" + urllib.parse.quote(act_url, safe="")
    def _p(*a):
        if not quiet:
            print(*a)

    if dry_run:
        _p("\n===== [2] SSO 中转页（dry-run）=====")
        _p("GET", u1)
        _p("  User-Agent:", UA_WEB)
        return None
    s1, h1, b1 = http_req("GET", u1, {"User-Agent": UA_WEB,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    m = re.search(r"loginPath\s*=\s*'([^']+)'", b1)
    _p("[2] /qwhdsso/login: HTTP %s, sid=%s" % (s1, mask(m.group(1), 28) if m else "未取到"))
    if not m:
        raise SystemExit("SSO loginPath 未返回: " + mask(b1, 100))
    login_url = BASE + "/qwhdsso" + m.group(1)

    body = {"jwtToken": None, "token": app_token, "provinceCode": province, "cityCode": city,
            "userCheckId": format(int(phone), "x"),
            "carrierOperator": "002", "appVersionCode": app_ver, "took": 150}
    body_txt = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    if dry_run:
        _p("\n===== [3] appTokenLogin（dry-run）=====")
        _p("POST", login_url)
        _p("  Content-Type: application/json;charset=UTF-8")
        _p("  User-Agent:", UA_WEB)
        _p("  body.token:", mask(app_token, 30))
        _p("  body:", mask(body_txt, 120))
        return None
    s2, h2, b2 = http_req("POST", login_url, {
        "Content-Type": "application/json;charset=UTF-8", "User-Agent": UA_WEB,
        "Origin": BASE, "Referer": u1, "Accept": "*/*",
        "X-Requested-With": "com.greenpoint.android.mc10086.activity",
    }, body_txt.encode())
    _p("[3] appTokenLogin: HTTP %s" % s2)
    try:
        d = json.loads(b2)
    except Exception:
        raise SystemExit("appTokenLogin 响应异常: " + mask(b2, 150))
    if d.get("code") != "SUCCESS":
        msg = "%s %s" % (d.get("code"), d.get("msg"))
        if "过期" in str(d.get("msg")):
            msg += ("\n    原因：app_token 已失效（一般几小时~一天）。\n"
                    "    解法：① 用 --cred 里的 xk 走 autoLogin 刷新（模式A，推荐）；\n"
                    "          ② 或从最新抓包里取新的 app_token 写进凭据文件。")
        raise SystemExit("appTokenLogin 失败: %s" % msg)
    data = d.get("data") or {}
    jump = data.get("url", "")
    _p("    code=SUCCESS jwt=%s" % mask(data.get("jwt", ""), 20))

    s3, h3, b3 = http_req("GET", jump, {"User-Agent": UA_WEB, "Accept": "text/html,*/*;q=0.8"})
    sc = get_setcookies(h3)
    mt = re.search(r"QWHD_SESSION_TOKEN=([^;]+)", sc)
    ma = (re.search(r"QWHD_SESSION_TOKEN=[^;]+;Max-Age=(\d+)", sc) or [None, ""])[1]
    _p("[4] 活动页: HTTP %s, QWHD_SESSION_TOKEN=%s Max-Age=%s" % (s3, mask(mt.group(1)) if mt else "未取到", ma))
    if not mt:
        raise SystemExit("未取得 QWHD_SESSION_TOKEN")
    return {"token": mt.group(1), "jump": jump, "max_age": ma}

def verify_session(sess):
    tok = sess["token"]
    print("[5] 验证会话（调用 /qwhdhub/api/mark/user/info）")
    h = {"Content-Type": "application/json;charset=UTF-8", "Accept": "*/*",
         "Origin": BASE, "Referer": sess["jump"], "login-check": "1",
         "x-requested-with": "XMLHttpRequest", "Cookie": "QWHD_SESSION_TOKEN=" + tok,
         "User-Agent": UA_WEB}
    s, hh, b = http_req("POST", BASE + "/qwhdhub/api/mark/user/info", h, b"{}")
    print("    HTTP %s, resp=%s" % (s, mask(b, 100)))
    sc = get_setcookies(hh)
    mt = re.search(r"QWHD_SESSION_TOKEN=([^;]+)", sc)
    ma = (re.search(r"Max-Age=(\d+)", sc) or [None, ""])[1] if mt else ""
    if mt:
        same = "同值(滑动续期)" if mt.group(1) == tok else "新值:" + mask(mt.group(1))
        print("    Set-Cookie 重发: %s, Max-Age=%s" % (same, ma))
    return s, b

RESERVED_KEYS = {"phone", "province_code", "city_code", "app_token", "xk", "device",
                 "note", "act_url", "_updated_at"}


def load_cred(path: str) -> dict:
    if not os.path.exists(path):
        raise SystemExit("凭据文件不存在: %s" % path)
    with open(path, encoding="utf-8") as f:
        cred = json.load(f)

    phone = str(cred.get("phone") or "").strip()
    province = str(cred.get("province_code") or "").strip()
    city = str(cred.get("city_code") or "").strip()
    app_token = str(cred.get("app_token") or "").strip()
    xk = str(cred.get("xk") or "").strip()

    device = dict(cred.get("device") or {})
    if not device:
        device = {k: v for k, v in cred.items() if k not in RESERVED_KEYS and v is not None}
    if xk:
        device["xk"] = xk
    for k, v in (("phone", phone), ("province_code", province), ("city_code", city)):
        if v and not device.get(k):
            device[k] = v
    if not phone:
        phone = str(device.get("phone") or device.get("tel") or "").strip()
    if not province:
        province = str(device.get("province_code") or device.get("prov") or "").strip()
    if not city:
        city = str(device.get("city_code") or device.get("city") or "").strip()

    mode = "xk" if device.get("xk") else ("token" if app_token else "")
    return {"mode": mode, "phone": phone, "province": province, "city": city,
            "app_token": app_token, "device": device, "path": path,
            "act_url": cred.get("act_url") or ""}


def save_cred(cred: dict, app_token: str = ""):
    path = cred.get("path")
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        raw = {}
    if app_token:
        raw["app_token"] = app_token
    raw["_updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=1)


def params_from_har(har_path: str) -> dict:
    try:
        from Crypto.Cipher import AES as _A
    except ImportError:
        raise SystemExit("从 HAR 解密需要 pycryptodome: pip install pycryptodome")
    har = json.load(open(har_path, encoding="utf-8"))
    cands = []          
    for e in har["log"]["entries"]:
        u = e["request"]["url"]
        if re.search(r"/uam\w*login/", u) and e["request"].get("postData", {}).get("text"):
            txt = e["request"]["postData"]["text"]
            try:
                raw = base64.b64decode(txt)
                c = _A.new(CRYPT["KEY_14"].encode(), _A.MODE_CBC, CRYPT["CRYPT_14_IV"].encode())
                p = c.decrypt(raw)
                o = json.loads(p[:-p[-1]].decode("utf-8", "replace"))
            except Exception:
                continue
            if o.get("xk"):
                cands.append((e.get("startedDateTime", ""), e, o, urllib.parse.urlsplit(u).path))
    if not cands:
        return None
    cands.sort(key=lambda x: x[0], reverse=True)

    def resolve_phone(e):
        try:
            rt = e["response"]["content"].get("text", "")
            rc = _A.new(CRYPT["RESPONSE_KEY_14"].encode(), _A.MODE_CBC, CRYPT["CRYPT_14_IV"].encode())
            rp = rc.decrypt(base64.b64decode(rt))
            ro = json.loads(rp[:-rp[-1]].decode("utf-8", "replace"))
            return (ro.get("rspBody") or {}).get("userName", ""), (ro.get("rspBody") or {}).get("validityTerm", "")
        except Exception:
            return "", ""

    chosen = None
    phone = ""
    for ts, e, o, path in cands:
        ph, vt = resolve_phone(e)
        if ph:
            chosen, phone = (e, o, path), ph
            sys.stderr.write("[HAR] 选用 %s (时间 %s) -> phone=%s validityTerm=%s\n" % (
                path, ts, mask(phone, 7), vt))
            break
    if chosen is None:
        ts, e, o, path = cands[0]
        chosen = (e, o, path)
        sys.stderr.write("[HAR] 选用最新登录请求 %s (时间 %s)\n" % (path, ts))
    e, o, path = chosen

    req_body = {k: v for k, v in (o.get("reqBody") or {}).items()
                if k not in ("cellNum", "verifyCode", "devToken")}
    o["reqBody"] = req_body
    if not phone:
        tel = str(o.get("tel") or "")
        if re.match(r"^1\d{10}$", tel):
            phone = tel
    o.setdefault("phone", phone)
    o.setdefault("province_code", o.get("prov", ""))
    o.setdefault("city_code", o.get("city", ""))
    return o


def app_token_from_har(har_path: str) -> str:
    har = json.load(open(har_path, encoding="utf-8"))
    best = ""           
    for e in har["log"]["entries"]:
        for h in e["request"].get("headers", []):
            if h["name"].lower() == "cookie" and "JSESSIONID=" in h["value"] and "UID=" in h["value"]:
                c = h["value"]
                jsid = (re.search(r"JSESSIONID=([^;,]+)", c) or [None, ""])[1]
                uid = (re.search(r"(?:^|[;,]\s*)UID=([^;,]+)", c) or [None, ""])[1]
                tid = (re.search(r"ticketID=([^;,]+)", c) or [None, "POD9"])[1]
                if jsid and uid:
                    best = ("JSESSIONID=%s; UID=%s; Comment=SessionServer-unity; "
                            "Path=/;HTTPOnly; ticketID=%s; Secure" % (jsid, uid, tid))
    return best

ACCOUNTS_FILE = "cmcc_accounts.json"
APP_TOKEN_FILE = "app_token.json"
ERR_NET = "[网络] "      


def load_accounts(path: str = ACCOUNTS_FILE) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if isinstance(data, list):
        return data
    return data.get("accounts") or []


def _perm_hint(path: str) -> str:
    d = os.path.dirname(os.path.abspath(path))
    return ("无写入权限: %s\n"
            "    服务以低权限用户(cmcc)运行，但文件属主是 root（多半是 scp 上传时改成了 root）。\n"
            "    修复： sudo chown -R cmcc %s && sudo chmod 664 %s/*.json\n"
            "    或一键修： bash /home/CMCC/deploy/check.sh fixperm" % (path, d, d))


def save_accounts(accounts: list, path: str = ACCOUNTS_FILE):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"accounts": accounts, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                      f, ensure_ascii=False, indent=1)
    except PermissionError:
        raise SystemExit(_perm_hint(path))


def upsert_account(accounts: list, acct: dict) -> list:
    phone = str(acct.get("phone") or "")
    for i, a in enumerate(accounts):
        if str(a.get("phone")) == phone:
            merged = dict(a)
            merged.update({k: v for k, v in acct.items() if v not in (None, "")})
            merged["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            accounts[i] = merged
            return accounts
    acct["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    accounts.append(acct)
    return accounts


def write_app_token_file(accounts: list, path: str = APP_TOKEN_FILE, only_fresh=False) -> str:
    lines = []
    for a in accounts:
        tok = (a.get("app_token") or "").strip()
        if not tok:
            continue
        if only_fresh and not a.get("app_token_at"):
            continue
        lines.append("%s#%s" % (a.get("phone", ""), tok))
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
    except PermissionError:
        raise SystemExit(_perm_hint(path))
    return path

def account_from_source(cred: dict, har_path: str = "", cred_path: str = "") -> dict:
    acct = {"phone": cred.get("phone", ""), "province_code": cred.get("province_code", ""),
            "city_code": cred.get("city_code", ""), "xk": cred.get("xk", ""),
            "device": cred.get("device") or {}, "app_token": cred.get("app_token", ""),
            "source": "cred:%s" % cred_path if cred_path else ("har:%s" % har_path if har_path else "")}
    return acct


def refresh_one_account(acct: dict, act_url: str = "", verify=False):
    phone = str(acct.get("phone") or "")
    device = dict(acct.get("device") or {})
    if acct.get("xk"):
        device["xk"] = acct["xk"]
    if not device.get("xk"):
        return "", "", "账号 %s 没有 xk，无法 autoLogin" % phone
    province = acct.get("province_code") or "851"
    city = acct.get("city_code") or "0852"
    req = build_autologin(device, phone)
    status, headers, body = http_req("POST", req["url"], req["headers"], req["body"].encode())
    sc = get_setcookies(headers)
    jsid = (re.search(r"JSESSIONID=([^;,]+)", sc) or [None, ""])[1]
    uid = (re.search(r"(?:^|[;,]\s*)UID=([^;,]+)", sc) or [None, ""])[1]
    ticket = (re.search(r"ticketID=([^;,]+)", sc) or [None, "POD9"])[1]
    if not (jsid and uid):
        desc = ""
        if status == 0:
            desc = ERR_NET + str(body)[:240]
        else:
            try:
                plain = aes_cbc_decrypt(body, CRYPT["RESPONSE_KEY_14"], CRYPT["CRYPT_14_IV"])
                desc = json.loads(plain).get("retDesc", "")
            except Exception:
                desc = str(body)[:200]
        return "", "", desc or ("autoLogin HTTP %s" % status)
    app_token = ("JSESSIONID=%s; UID=%s; Comment=SessionServer-unity; "
                 "Path=/;HTTPOnly; ticketID=%s; Secure" % (jsid, uid, ticket))
    session = ""
    try:
        sess = mint_session(app_token, phone, province, city, act_url or DEFAULT_ACT_URL,
                            quiet=True)
        session = (sess or {}).get("token", "")
    except SystemExit:
        session = ""
    return app_token, session, ""


def main():
    ap = argparse.ArgumentParser(
        description="移动 qwhdsso 会话票据模拟器（凭据来自本地 JSON）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""凭据文件示例 cmcc_cred.json：
{
  "phone": "18788605001", "province_code": "851", "city_code": "0852",
  "app_token": "JSESSIONID=xxx; UID=yyy; ticketID=POD9; Secure",
  "xk": "493aad93....",
  "device": {"ak": "...", "cid": "...", "imei": "...", "reqBody": {...}}
}
有 xk → 自动 autoLogin 铸新 app_token（可长期续期）；只有 app_token → 直接换 30 分钟会话。""")
    ap.add_argument("--cred", default="cmcc_cred.json",
                    help="本地凭据 JSON（默认 cmcc_cred.json），兼容 xk 与 app_token 两种模式")
    ap.add_argument("--use-token", action="store_true",
                    help="强制使用文件里的 app_token（跳过 autoLogin）")
    ap.add_argument("--app-token", help="临时覆盖凭据文件里的 app_token")
    ap.add_argument("--phone", help="覆盖凭据文件里的手机号")
    ap.add_argument("--province", default="", help="覆盖省份编码（如 851）")
    ap.add_argument("--city", default="", help="覆盖地市编码（如 0852）")
    ap.add_argument("--act-url", default="", help="目标活动页 URL（覆盖文件里的 act_url）")
    ap.add_argument("--from-har", help="【可选】把 HAR 转成凭据 JSON（一次性引导用）")
    ap.add_argument("--save-cred", help="--from-har 生成的凭据文件路径（默认覆盖 --cred）")
    ap.add_argument("--update-cred", action="store_true", help="刷新成功后把新 app_token 回写凭据文件")
    ap.add_argument("--no-fallback", action="store_true", help="autoLogin 失败时不回退到文件里的 app_token")
    ap.add_argument("--save-app-token", help="把本次 app_token 另存到文件")
    ap.add_argument("--verify", action="store_true", help="换取会话后调用业务 API 验证")
    ap.add_argument("--loop", type=int, default=1, help="连续铸 N 张会话票据")
    ap.add_argument("--gap", type=float, default=3.0, help="--loop 间隔秒")
    ap.add_argument("--dry-run", action="store_true", help="只打印请求不发送")

    ap.add_argument("--accounts", default=ACCOUNTS_FILE, help="多账号库文件（默认 cmcc_accounts.json）")
    ap.add_argument("--out", default=APP_TOKEN_FILE, help="票据输出文件（默认 app_token.json，一行一个 手机号#token）")
    ap.add_argument("--import-account", action="store_true", help="把当前凭据/HAR 导入账号库")
    ap.add_argument("--list-accounts", action="store_true", help="列出账号库")
    ap.add_argument("--refresh-all", action="store_true", help="一键换票：库内所有账号 autoLogin 铸新票并写 %s" % APP_TOKEN_FILE)
    ap.add_argument("--remove-account", help="从账号库删除某手机号")
    ap.add_argument("--refresh-phone", help="只刷新指定手机号")
    args = ap.parse_args()

    if args.list_accounts:
        accs = load_accounts(args.accounts)
        print("账号库 %s 共 %d 个账号：" % (args.accounts, len(accs)))
        for a in accs:
            print("  %s | xk=%s | token=%s | 更新 %s" % (
                a.get("phone", "?"), mask(a.get("xk", ""), 12),
                mask(a.get("app_token", ""), 22) if a.get("app_token") else "无",
                a.get("updated_at", "-")))
        return

    if args.remove_account:
        accs = load_accounts(args.accounts)
        left = [a for a in accs if str(a.get("phone")) != str(args.remove_account)]
        save_accounts(left, args.accounts)
        write_app_token_file(left, args.out)
        print("已删除账号 %s，剩余 %d 个" % (args.remove_account, len(left)))
        return

    if args.refresh_all or args.refresh_phone:
        accs = load_accounts(args.accounts)
        if not accs:
            raise SystemExit("账号库 %s 为空，先用 --import-account 导入" % args.accounts)
        targets = accs
        if args.refresh_phone:
            targets = [a for a in accs if str(a.get("phone")) == str(args.refresh_phone)]
            if not targets:
                raise SystemExit("账号库里没有 %s" % args.refresh_phone)
        print("一键换票：共 %d 个账号 → %s\n" % (len(targets), args.out))
        ok_cnt = 0
        for i, a in enumerate(targets):
            phone = a.get("phone", "?")
            print("[%d/%d] %s" % (i + 1, len(targets), phone))
            tok, sess, err = refresh_one_account(a, args.act_url, args.verify)
            if tok:
                a["app_token"] = tok
                a["app_token_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                if sess:
                    a["session_token"] = sess
                a["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                ok_cnt += 1
                print("    ✔ 新 app_token %s%s" % (mask(tok, 30), (" | 会话票据 %s" % mask(sess, 18)) if sess else ""))
            else:
                print("    ✘ 失败：%s" % err)
            save_accounts(accs, args.accounts)
        write_app_token_file(accs, args.out)
        print("\n完成：%d/%d 成功，票据已写入 %s" % (ok_cnt, len(targets), args.out))
        return


    if args.from_har:
        cred_path = args.save_cred or args.cred
        params = params_from_har(args.from_har) or {}
        har_token = app_token_from_har(args.from_har)
        out = {}
        if params:
            out["xk"] = params.get("xk", "")
            out["device"] = {k: v for k, v in params.items() if k != "xk"}
            out["phone"] = params.get("phone", "")
            out["province_code"] = params.get("province_code", "")
            out["city_code"] = params.get("city_code", "")
            sys.stderr.write("[HAR] 已解密登录请求体, xk=%s phone=%s\n" % (
                mask(out["xk"], 16), out["phone"]))
        if har_token:
            out["app_token"] = har_token
            sys.stderr.write("[HAR] 已提取 app_token: %s\n" % mask(har_token, 30))
        if not out:
            raise SystemExit("HAR 中既没找到含 xk 的登录请求，也没找到 SessionServer Cookie")
        out["_updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(cred_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        sys.stderr.write("[HAR] 凭据文件已生成: %s\n" % cred_path)
        args.cred = cred_path

    cred = load_cred(args.cred)
    phone = args.phone or cred["phone"]
    province = args.province or cred["province"]
    city = args.city or cred["city"]
    act_url = args.act_url or cred.get("act_url") or DEFAULT_ACT_URL
    app_token = args.app_token or cred["app_token"]
    device = cred["device"]

    use_xk = bool(device.get("xk")) and not args.use_token and not args.app_token
    if args.app_token:
        mode = "token(命令行覆盖)"
    elif use_xk:
        mode = "xk(autoLogin 铸票)"
    elif cred["app_token"]:
        mode = "token(文件内 app_token)"
    else:
        raise SystemExit("凭据文件 %s 里既没有 xk 也没有 app_token，无法工作" % args.cred)

    print("凭据文件: %s" % args.cred)
    print("模式: %s | 手机号: %s | 省/市: %s/%s" % (
        mode, (phone[:3] + "****" + phone[-4:]) if len(phone) >= 7 else (phone or "缺失"),
        province or "缺失", city or "缺失"))
    if use_xk:
        print("  xk: %s（autoLogin 将现场铸造新 app_token）" % mask(device["xk"], 16))
    elif app_token:
        print("  app_token: %s" % mask(app_token, 30))
    if not phone:
        raise SystemExit("缺少手机号：请在凭据文件写 phone，或用 --phone 指定")

    if args.dry_run:
        if use_xk:
            run_autologin(device, phone, dry_run=True)
        mint_session(app_token or "<待 autoLogin 铸造>", phone, province, city, act_url, dry_run=True)
        return

    for i in range(args.loop):
        if i:
            time.sleep(args.gap)
        print("\n" + "=" * 62)
        print("第 %d/%d 轮  %s" % (i + 1, args.loop, time.strftime("%Y-%m-%d %H:%M:%S")))
        print("=" * 62)
        cur_token = args.app_token or cred["app_token"]
        if use_xk:
            try:
                cur_token = run_autologin(device, phone)
                if args.update_cred:
                    save_cred(cred, cur_token)
                    print("    已回写凭据文件: %s" % args.cred)
            except SystemExit as ex:
                if cred["app_token"] and not args.no_fallback:
                    print("\n[!] autoLogin 未成功，自动回退到凭据文件里的 app_token（该票据也可能已过期）：")
                    print("    %s" % str(ex).splitlines()[0])
                    cur_token = cred["app_token"]
                else:
                    raise
        sess = mint_session(cur_token, phone, province, city, act_url)
        if sess and args.verify:
            verify_session(sess)
        if sess:
            print("\n>>> 本轮会话票据: %s  (Max-Age=%s, 30 分钟滑动)" % (mask(sess["token"]), sess["max_age"]))
        if args.save_app_token and cur_token:
            with open(args.save_app_token, "w", encoding="utf-8") as f:
                f.write(cur_token)
            print(">>> app_token 已保存: %s" % args.save_app_token)

        if args.import_account:
            accs = load_accounts(args.accounts)
            acct = {
                "phone": phone, "province_code": province, "city_code": city,
                "xk": device.get("xk", ""),
                "device": {k: v for k, v in device.items() if not k.startswith("_")},
                "app_token": cur_token,
                "app_token_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "session_token": (sess or {}).get("token", ""),
                "source": args.cred,
            }
            accs = upsert_account(accs, acct)
            save_accounts(accs, args.accounts)
            write_app_token_file(accs, args.out)
            print(">>> 账号已入库: %s（库 %s，票据 %s）" % (phone, args.accounts, args.out))

if __name__ == "__main__":
    main()
