
import base64
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from curl_cffi import requests as cf_requests
except Exception:  
    cf_requests = None

import crypto_engine  
import builtin_templates as builtin  
import cmcc_crypto  

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, 'static')

UA_APP = 'okhttp/3.14.9 ChinaMobile/12.5.6 (Linux; Android 12; M2011K2C)'
UA_WV = ('Mozilla/5.0 (Linux; Android 12; M2011K2C Build/SKQ1.211006.001; wv) '
         'AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/121.0.0.0 '
         'Mobile Safari/537.36')

STATE = {
    'sid': None,
    'jwt_token': None,
    'app_token': None,          
    'session_token': None,      
    'phone': None,              
    'keys': crypto_engine.KeyMaterial(),
    'history': [],
}
LOCK = threading.Lock()


def log(msg):
    sys.stderr.write('[%s] %s\n' % (time.strftime('%H:%M:%S'), msg))
    sys.stderr.flush()


def _session():
    if cf_requests is None:
        return None
    return cf_requests.Session()


def act_send_code_real(phone):
    phone = (phone or '').strip()
    if not re.match(r'^1\d{10}$', phone):
        return {'ok': False, 'error': '手机号格式不正确（需 11 位，1 开头）'}
    try:
        url, headers, payload, body_json = builtin.build_send_code(phone)
    except Exception as e:
        return {'ok': False, 'error': '内置模板构造失败：%s' % e}
    with LOCK:
        STATE['phone'] = phone
    r = do_post(url, payload, headers)
    plain = None
    try:
        plain = json.loads(cmcc_crypto.decrypt_body(r['content']).decode('utf-8'))
    except Exception:
        plain = None
    ok = bool(plain) and plain.get('retCode') == '000000'
    out = {'ok': ok, 'mode': 'real', 'status': r['status'],
           'retCode': (plain or {}).get('retCode'),
           'retDesc': (plain or {}).get('retDesc'),
           'phone': phone,
           'rsp': plain,
           'note': ('服务端已受理（短信已下发到 %s）' % phone if ok else None)}
    if not ok and not plain:
        out['note'] = '响应解密失败或非 JSON：%s' % r['text'][:120]
    return out


def act_login_real(code, phone, dev_token=None):
    phone = (phone or '').strip()
    if not re.match(r'^1\d{10}$', phone):
        return {'ok': False, 'error': '手机号格式不正确（需 11 位，1 开头）'}
    code = (code or '').strip()
    with LOCK:
        STATE['phone'] = phone
    attempts = []

    try:
        url, headers, payload, _ = builtin.build_three_net(phone, code, dev_token)
    except Exception as e:
        url = headers = payload = None
        log('build_three_net failed: %s' % e)
    if url:
        r = do_post(url, payload, headers)
        try:
            resp = json.loads(cmcc_crypto.decrypt_body(r['content']).decode('utf-8'))
        except Exception:
            resp = {'raw': r['text'][:160]}
        sc = r['headers'].get('set-cookie', '')
        sess_tok = _session_from_set_cookie(sc)
        rc = resp.get('retCode')
        attempts.append({'path': '#233 uamthreenetworklogin',
                         'status': r['status'], 'retCode': rc,
                         'retDesc': resp.get('retDesc'),
                         'rsp': resp.get('rspBody'),
                         'session': sess_tok,
                         'hint': _login_hint(rc)})
        if sess_tok:
            with LOCK:
                STATE['app_token'] = sess_tok
                STATE['session_token'] = sess_tok
            return {'ok': True, 'mode': 'real', 'path': '#233',
                    'attempts': attempts, 'session_token': sess_tok,
                    'body_b64': payload,
                    'retCode': rc, 'retDesc': resp.get('retDesc'),
                    'note': '登录成功，已取得会话票据'}

    for put_code in ('t', 'reqBody.t', 'reqBody.verifyCode', 'reqBody.randCode'):
        try:
            url, headers, payload, _ = builtin.build_login(phone, code, put_code)
        except Exception:
            continue
        r = do_post(url, payload, headers)
        try:
            resp = json.loads(cmcc_crypto.decrypt_body(r['content']).decode('utf-8'))
        except Exception:
            resp = {'raw': r['text'][:160]}
        sc = r['headers'].get('set-cookie', '')
        sess_tok = _session_from_set_cookie(sc)
        attempts.append({'path': '#236 uamstatelogin', 'code_pos': put_code,
                         'status': r['status'], 'retCode': resp.get('retCode'),
                         'retDesc': resp.get('retDesc'), 'session': sess_tok,
                         'hint': _login_hint(resp.get('retCode'))})
        if sess_tok:
            with LOCK:
                STATE['app_token'] = sess_tok
                STATE['session_token'] = sess_tok
            return {'ok': True, 'mode': 'real', 'path': '#236',
                    'attempts': attempts, 'session_token': sess_tok,
                    'body_b64': payload,
                    'retCode': resp.get('retCode'), 'retDesc': resp.get('retDesc'),
                    'note': '登录成功，已取得会话票据'}
        time.sleep(0.4)

    ok = any(a.get('session') for a in attempts)
    return {'ok': ok, 'mode': 'real', 'status': 200, 'attempts': attempts,
            'session_token': None,
            'note': ('未取得会话票据；请查看 attempts 中各字段位置的返回码'
                     if not ok else '')}


def _login_hint(ret_code):
    return {
        '213010': '验证码不正确 —— 构造已完全正确，填入短信里的真实验证码即可',
        '213007': '验证码已连错 5 次，需重新下发短信',
        '223028': 'devToken 已失效或缺失（该接口要求本机号码认证）：'
                  '请从 APP 抓包 #233 请求体中的 devToken 填入「devToken」框',
        '214100': '触发运营商风控：devToken 与当前设备/号码不匹配，请换用本机抓包的 devToken',
        '220210': '该号码在 uamstatelogin 被拒（账号状态：非停机用户），'
                  '属业务规则而非构造问题；请改用 #233 路径或换一个号码',
        '310000': '服务端校验未通过（号码无用户档案 / 环境异常），请确认是真实可登录的移动号码',
        '310001': '缺少必要参数（验证码为空？）',
        '214257': '短信下发过于频繁，请约 1 分钟后再试',
    }.get(str(ret_code), '')


def _session_from_set_cookie(sc):
    if not sc:
        return None
    m = re.search(r'JSESSIONID=([^;]+)', sc)
    if not m:
        return None
    uid = re.search(r'UID=([^;]+)', sc)
    ticket = re.search(r'ticketID=([^;]+)', sc)
    return ('JSESSIONID=%s; UID=%s; Comment=SessionServer-unity; '
            'Path=/;HTTPOnly; ticketID=%s; Secure'
            % (m.group(1), uid.group(1) if uid else '',
               ticket.group(1) if ticket else 'POD9'))


def act_send_code(phone, keys):
    return act_send_code_real(phone)


def act_login(code, keys, phone=None, dev_token=None):
    if phone:
        dyn = act_login_real(code, phone, dev_token)
        if dyn is not None:
            return dyn
    return {'ok': False, 'error': '缺少手机号，无法执行加密通道登录'}


def act_three_network(phone, code, dev_token=None):
    if not phone or not code:
        return {'ok': False, 'error': '三网登录需提供手机号与验证码（devToken 可选）'}
    return act_login_real(code, phone, dev_token)


def act_fetch_sid():
    url, hdrs, ck = builtin.sso_page_meta()
    if not url:
        return {'ok': False, 'error': '内置未包含 SSO 页面模板'}
    r = do_get(url, dict(hdrs), cookies=ck)
    m = re.search(r"loginPath\s*=\s*'/appTokenLogin\?sid=([A-Za-z0-9]+)'", r['text'])
    sid = m.group(1) if m else None
    if sid:
        with LOCK:
            STATE['sid'] = sid
    return {'ok': bool(sid), 'sid': sid,
            'note': ('已获取服务端实时 sid；appTokenLogin 还需有效 token（APP 原生 SDK 产出）'
                     if sid else '页面中未解析到 sid')}


def act_h5_token(sid=None, jwt_token=None, session_token=None, full_body=None):
    url_base, hdrs, ck = builtin.h5_token_meta()
    if not url_base:
        return {'ok': False, 'error': '内置未包含 appTokenLogin 模板'}

    payload = builtin.h5_token_payload(session_token, jwt_token, STATE.get('phone'))

    if full_body:
        try:
            pasted = json.loads(full_body)
            if isinstance(pasted, dict):
                payload.update(pasted)
        except Exception:
            return {'ok': False, 'error': '粘贴的 body 不是合法 JSON'}

    if session_token:
        payload['token'] = session_token
    if jwt_token:
        payload['jwtToken'] = jwt_token
    elif 'jwtToken' not in payload:
        payload['jwtToken'] = None

    sid = sid or STATE.get('sid')
    if not sid:
        auto = act_fetch_sid()
        sid = auto.get('sid')
    if not sid:
        return {'ok': False, 'error': '缺少 sid 且无法从 /qwhdsso/login 获取'}

    if not payload.get('token'):
        return {'ok': False, 'error': '缺少 token（会话串 JSESSIONID=...; UID=...）'}
    if jwt_token:
        payload['jwtToken'] = jwt_token
    elif 'jwtToken' not in payload:
        payload['jwtToken'] = None

    url = url_base + '?sid=' + urllib.parse.quote(sid)
    r = do_post(url, json.dumps(payload), dict(hdrs), cookies=ck)
    try:
        data = json.loads(r['text'])
    except Exception:
        data = {'raw': r['text'][:300]}
    jwt = None
    if isinstance(data.get('data'), dict):
        jwt = data['data'].get('jwt')
    with LOCK:
        if jwt:
            STATE['app_token'] = jwt
            STATE['jwt_token'] = payload.get('jwtToken')
    return {'ok': data.get('code') == 'SUCCESS', 'status': r['status'],
            'code': data.get('code'), 'msg': data.get('msg'),
            'jwt': jwt,
            'jwt_len': len(jwt) if jwt else 0,
            'sid_used': sid,
            'sent_body': payload,
            'url': (data.get('data') or {}).get('url') if isinstance(data.get('data'), dict) else None}


def act_user_info():
    url, hdrs, ck = builtin.user_info_meta()
    if not url:
        return {'ok': False, 'error': '内置未包含 user/info 模板'}
    r = do_post(url, json.dumps(builtin.user_info_payload()), dict(hdrs), cookies=ck)
    try:
        data = json.loads(r['text'])
    except Exception:
        data = {'raw': r['text'][:300]}
    return {'ok': data.get('code') == 'SUCCESS', 'status': r['status'], 'data': data.get('data')}


def do_post(url, body, headers, cookies=None):
    h = {k: v for k, v in headers.items()
         if k.lower() not in ('host', 'connection', 'content-length', 'accept-encoding')}
    h.setdefault('User-Agent', UA_APP)
    if cf_requests is None:
        return {'status': 0, 'text': 'curl_cffi 未安装，无法发起实网请求', 'headers': {}, 'content': b''}
    try:
        s = _session()
        if cookies:
            for k, v in cookies.items():
                s.cookies.set(k, v)
        r = s.post(url, data=body.encode() if isinstance(body, str) else body,
                   headers=h, impersonate='chrome124', timeout=25)
        return {'status': r.status_code, 'text': r.text,
                'headers': {k.lower(): v for k, v in r.headers.items()},
                'content': r.content}
    except Exception as e:
        return {'status': 0, 'text': '%s: %s' % (type(e).__name__, e),
                'headers': {}, 'content': b''}


def do_get(url, headers, cookies=None):
    h = {k: v for k, v in headers.items()
         if k.lower() not in ('host', 'connection', 'content-length', 'accept-encoding')}
    h.setdefault('User-Agent', UA_WV)
    if cf_requests is None:
        return {'status': 0, 'text': 'curl_cffi 未安装', 'headers': {}, 'content': b''}
    try:
        s = _session()
        if cookies:
            for k, v in cookies.items():
                s.cookies.set(k, v)
        r = s.get(url, headers=h, impersonate='chrome124', timeout=25, allow_redirects=False)
        return {'status': r.status_code, 'text': r.text,
                'headers': {k.lower(): v for k, v in r.headers.items()},
                'content': r.content}
    except Exception as e:
        return {'status': 0, 'text': '%s: %s' % (type(e).__name__, e),
                'headers': {}, 'content': b''}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, indent=2))

    def _static(self, name):
        p = os.path.join(STATIC, name)
        if not os.path.isfile(p):
            self._send(404, 'not found', 'text/plain; charset=utf-8')
            return
        ctype = 'text/html; charset=utf-8'
        if name.endswith('.js'):
            ctype = 'application/javascript; charset=utf-8'
        elif name.endswith('.css'):
            ctype = 'text/css; charset=utf-8'
        with open(p, 'rb') as f:
            self._send(200, f.read(), ctype)

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if p in ('/', '/index.html'):
            return self._static('index.html')
        if p.startswith('/static/'):
            return self._static(os.path.basename(p))
        self._send(404, 'not found', 'text/plain; charset=utf-8')

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n).decode('utf-8', 'ignore') if n else '{}'
        try:
            data = json.loads(raw or '{}')
        except Exception:
            data = {}

        keys = STATE['keys']

        if p == '/api/keys':
            keys.update_from(data)
            return self._json({'ok': True, 'keys': keys.describe(),
                               'note': '动态密钥注入已保留；但内置加密通道已可直接使用，无需注入。'})

        if p == '/api/reset-keys':
            with LOCK:
                STATE['keys'] = crypto_engine.KeyMaterial()
            return self._json({'ok': True, 'keys': STATE['keys'].describe()})

        if p == '/api/send-code':
            r = act_send_code(data.get('phone', ''), keys)
            with LOCK:
                STATE['history'].append(('send-code', r))
            return self._json(r)

        if p == '/api/login':
            r = act_login(data.get('code', ''), keys, data.get('phone'),
                          data.get('dev_token'))
            with LOCK:
                STATE['history'].append(('login', r))
            return self._json(r)

        if p == '/api/three-network':
            r = act_three_network(data.get('phone'), data.get('code'),
                                  data.get('dev_token'))
            with LOCK:
                STATE['history'].append(('three-network', r))
            return self._json(r)

        if p == '/api/fetch-sid':
            r = act_fetch_sid()
            with LOCK:
                STATE['history'].append(('fetch-sid', r))
            return self._json(r)

        if p == '/api/h5-token':
            r = act_h5_token(data.get('sid'), data.get('jwtToken'),
                             data.get('session_token'), data.get('body'))
            with LOCK:
                STATE['history'].append(('h5-token', r))
            return self._json(r)

        if p == '/api/user-info':
            r = act_user_info()
            return self._json(r)

        if p == '/api/decrypt':
            ct = data.get('cipher_b64') or ''
            if not ct:
                return self._json({'ok': False, 'error': '缺少 cipher_b64'})
            try:
                raw = base64.b64decode(ct)
            except Exception:
                raw = ct.encode('utf-8', 'ignore')
            return self._json({'ok': True, 'plain': keys.decrypt_body(raw)})

        if p == '/api/self-test':
            return self._json(self_test())

        self._send(404, 'not found', 'text/plain; charset=utf-8')


def self_test():
    sumr = builtin.summary()
    return {'ok': True, 'stage': 'builtin', 'xk_set': sumr['xk_set'],
            'endpoints': list(sumr['endpoints'].keys()),
            'note': '已使用内置报文模板，加密通道直接可用，无需注入密钥。'}


def main():
    port = int(os.environ.get('CMCC_PORT', '8848'))
    srv = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    log('builtin templates loaded, listening on http://127.0.0.1:%d' % port)
    srv.serve_forever()


if __name__ == '__main__':
    main()
