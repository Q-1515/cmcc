import base64
import hashlib
import json
import os
import random
import re
import time

from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA

_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)

JS_CANDIDATES = [
    os.environ.get('CMCC_JS'),
    os.path.join(_PARENT, 'vendor', 'cmcc_renew.js'),
    os.path.join(_HERE, 'cmcc_renew.js'),
    os.path.join(_HERE, 'vendor', 'cmcc_renew.js'),
    r'C:\Users\JY\Downloads\MyCookieCenter-main\scripts\cmcc\cmcc_renew.js',
]
JS_PATH = next((p for p in JS_CANDIDATES if p and os.path.isfile(p)), None)

DEFAULT_CRYPT = {
    'REQUEST_CRYPT_1': 'foorettD7vcBawt3',
    'RESPONSE_CRYPT_1': 'UVic06tpXgMNiApm',
    'REQUEST_CRYPT_2': 'bAIgvwAuA4tbDr9d',
    'REQUEST_CRYPT_12': 'V0dSUFZtS1NWRnJa',
    'KEY_14': 'tVkdaRWRY0ZkV1Vr',
    'REQUEST_CRYPT_12_IV': 'UkdWMVpWTVVWaGVq',
    'CRYPT_14_IV': 'VjFSQ1ZtVkQxRTlQ',
    'RESPONSE_CRYPT_2': 'GS7VelkJl5IT1uwQ',
    'RESPONSE_KEY_14': 'RYV0hCV1lV25KYVJ',
    'SIGN_SALT': '_Leadeon/SecurityOrganization',
    'RSA_N_HEX': ('968E9ACF9E59B4E2E1BB24266EE39043788A45F788ECDC5C971F4964C3267C'
                  'F20AFD3B7F029B68A9A9B65D77D0306B8319DF0C174F3DD82EF3894A6C38E2'
                  '3634F6095A81901AD7E6650911C0910F12C7DE50A6FCEE3AE3563CC5985C46A'
                  '965DB2AF49E94F69B62F67FF3D5C0F79782572375E5F8B44AA43C0CA6D48E8'
                  'A969BEB'),
}
TOKEN_IV = '9791027341711819'
RSA_E = 0x10001


def _load_crypt():
    d = dict(DEFAULT_CRYPT)
    try:
        if not JS_PATH:
            raise IOError('使用内置默认常量')
        with open(JS_PATH, encoding='utf-8', errors='replace') as f:
            src = f.read()
        m = re.search(r'const\s+CRYPT\s*=\s*\{(.*?)\}', src, re.S)
        if m:
            for k, v in re.findall(r'(\w+)\s*:\s*"([^"]*)"', m.group(1)):
                d[k] = v
        m2 = re.search(r'RSA_N_HEX\s*:\s*"([0-9a-fA-F]+)"', src)
        if m2:
            d['RSA_N_HEX'] = m2.group(1)
        m3 = re.search(r'var\s+plain\s*=\s*"([^"]*)"\s*\+\s*phone\s*\+\s*ts', src)
        if m3:
            d['CELL_PREFIX'] = m3.group(1)
    except Exception:
        pass
    d.setdefault('RSA_N_HEX', '')
    d.setdefault('CELL_PREFIX', 'leaddon')
    return d


CRYPT = _load_crypt()

_PUB = None


def _pub():
    global _PUB
    if _PUB is None:
        n_hex = (CRYPT.get('RSA_N_HEX') or '').strip()
        if not n_hex:
            raise ValueError(
                '缺少 RSA 公钥（RSA_N_HEX'
                '内置默认值也不可用。请确认 web/cmcc_crypto.py 是完整版本。')
        n = int(n_hex, 16)
        _PUB = RSA.construct((n, RSA_E))
    return _PUB


def _k(s):
    return s.encode('utf-8')[:16]


def encrypt(text, key_str, iv_str):
    pt = text.encode('utf-8') if isinstance(text, str) else text
    pad = 16 - (len(pt) % 16)
    pt += bytes([pad]) * pad
    return base64.b64encode(
        AES.new(_k(key_str), AES.MODE_CBC, _k(iv_str)).encrypt(pt)).decode()


def decrypt(b64, key_str, iv_str):
    d = AES.new(_k(key_str), AES.MODE_CBC, _k(iv_str)).decrypt(base64.b64decode(b64))
    n = d[-1]
    if 1 <= n <= 16 and d[-n:] == bytes([n]) * n:
        d = d[:-n]
    return d


def encrypt_body(body_json):
    return encrypt(body_json, CRYPT['KEY_14'], CRYPT['CRYPT_14_IV'])


def decrypt_body(b64):
    return decrypt(b64, CRYPT['RESPONSE_KEY_14'], CRYPT['CRYPT_14_IV'])


def decrypt_request_body(b64):
    return decrypt(b64, CRYPT['KEY_14'], CRYPT['CRYPT_14_IV'])


def encrypt_token(plain):
    return encrypt(plain, CRYPT['REQUEST_CRYPT_2'], TOKEN_IV)


def decrypt_token(b64):
    return decrypt(b64, CRYPT['REQUEST_CRYPT_2'], TOKEN_IV)


def calc_xs(url, body_json):
    return hashlib.md5(
        (url + '_' + body_json + CRYPT['SIGN_SALT']).encode('utf-8')).hexdigest()


def calc_xsign(x_token, x_time, x_nonce, tail='null'):
    return hashlib.md5(
        ('%s_%s_%s_%s' % (x_token, x_time, x_nonce, tail)).encode('utf-8')).hexdigest()


def make_token(xk, path, x_time, x_nonce):
    return encrypt_token('%s_%s_%s_%s' % (xk, path, x_time, x_nonce))


def cn_timestamp(sec=None):
    return time.strftime('%Y%m%d%H%M%S', time.gmtime(
        (sec if sec is not None else time.time()) + 8 * 3600))


def rsa_encrypt(text):
    k = (PUB_N_BYTES := ((_pub().n.bit_length() + 7) // 8))
    msg = text.encode('utf-8') if isinstance(text, str) else text
    if len(msg) > k - 11:
        raise ValueError('message too long for RSA')
    em = bytearray([0x00, 0x02])
    for _ in range(k - 3 - len(msg)):
        em.append(random.randrange(1, 256))
    em.append(0x00)
    em += msg
    c = pow(int.from_bytes(bytes(em), 'big'), RSA_E, _pub().n)
    return base64.b64encode(c.to_bytes(k, 'big')).decode()


def cell_num(phone, ts=None, prefix=None, code=None):
    ts = ts or cn_timestamp()
    pre = CRYPT.get('CELL_PREFIX', 'leaddon') if prefix is None else prefix
    if code:
        plain = pre + str(code) + str(phone) + ts
    else:
        plain = pre + str(phone) + ts
    return rsa_encrypt(plain), plain


def build_signed(url, body_obj, xk, tail='null', x_time=None, x_nonce=None):
    body_json = json_dumps(body_obj)
    path = re.sub(r'^https?://[^/]+', '', url)
    x_time = x_time or str(int(time.time() * 1000))
    x_nonce = x_nonce or str(random.randrange(10000000, 99999999))
    token = make_token(xk, path, x_time, x_nonce)
    xs = calc_xs(url, body_json)
    xsign = calc_xsign(token, x_time, x_nonce, tail)
    headers = {
        'Content-Type': 'application/json; charset=utf-8',
        'x-qen': '14',
        'x-time': x_time,
        'x-nonce': x_nonce,
        'xs': xs,
        'x-token': token,
        'x-sign': xsign,
        'User-Agent': ('okhttp/3.14.9 ChinaMobile/12.5.6 '
                       '(Linux; Android 12; M2011K2C)'),
        'Accept-Encoding': 'gzip',
        'Connection': 'Keep-Alive',
        'Accept': '*/*',
    }
    return headers, encrypt_body(body_json), body_json


def json_dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
