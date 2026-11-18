
import base64
import binascii
import hashlib
import hmac
import json
import os
import random
import struct
import time

_SBOX = None


def _init_sbox():
    global _SBOX
    if _SBOX is not None:
        return _SBOX
    try:
        from gmssl.sm4 import SM4_BOXES_TABLE  
        _SBOX = list(SM4_BOXES_TABLE)
    except Exception:
        _SBOX = [
            0xd6, 0x90, 0xe9, 0xfe, 0xcc, 0xe1, 0x3d, 0xb7, 0x16, 0xb6, 0x14, 0xc2, 0x28, 0xfb, 0x2c, 0x05,
            0x2b, 0x67, 0x9a, 0x76, 0x2a, 0xbe, 0x04, 0xc3, 0xaa, 0x44, 0x13, 0x26, 0x49, 0x86, 0x06, 0x99,
            0x9c, 0x42, 0x50, 0xf4, 0x91, 0xef, 0x98, 0x7a, 0x33, 0x54, 0x0b, 0x43, 0xed, 0xcf, 0xac, 0x62,
            0xe4, 0xb3, 0x1c, 0xc9, 0xc1, 0x08, 0x18, 0x3f, 0xdd, 0x1f, 0x89, 0x01, 0xfa, 0x21, 0x28, 0x87,
            0x17, 0x29, 0x4f, 0x4e, 0x64, 0xaf, 0x8e, 0x51, 0xdb, 0x49, 0x3d, 0xab, 0x0e, 0x8c, 0x8d, 0x74,
            0x1f, 0x4b, 0x0d, 0x9d, 0xc7, 0x5c, 0x41, 0x1f, 0x10, 0x5a, 0xd8, 0x0a, 0xc1, 0x31, 0x88, 0xa5,
            0xcd, 0x7b, 0xbd, 0x2d, 0x74, 0xd0, 0x12, 0xb8, 0xe5, 0xb4, 0xb0, 0x89, 0x69, 0x97, 0x4a, 0x0c,
            0x96, 0x77, 0x7e, 0x65, 0xb9, 0xf1, 0x09, 0xc5, 0x6e, 0xc6, 0x84, 0x18, 0xf0, 0x7d, 0xec, 0x3a,
            0xdc, 0x4d, 0x20, 0x79, 0xee, 0x5f, 0x3e, 0xd7, 0xcb, 0x39, 0x48,
        ]
    return _SBOX


def _rotl(x, n):
    n &= 31
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def _tau(A):
    s = _SBOX if _SBOX is not None else _init_sbox()
    return (s[(A >> 24) & 0xFF] << 24 | s[(A >> 16) & 0xFF] << 16 |
            s[(A >> 8) & 0xFF] << 8 | s[A & 0xFF])


def _T(A):
    t = _tau(A)
    return t ^ _rotl(t, 2) ^ _rotl(t, 10) ^ _rotl(t, 18) ^ _rotl(t, 24)


def _Tp(A):
    t = _tau(A)
    return t ^ _rotl(t, 13) ^ _rotl(t, 23)


FK = [0xa3b1bac6, 0x56aa3350, 0x677d9197, 0xb27022dc]
CK = [
    0x00070e15, 0x1c232a31, 0x383f464d, 0x545b6269,
    0x70777e85, 0x8c939aa1, 0xa8afb6bd, 0xc4cbd2d9,
    0xe0e7eef5, 0xfc030a11, 0x181f262d, 0x343b4249,
    0x50575e65, 0x6c737a81, 0x888f969d, 0xa4abb2b9,
    0xc0c7ced5, 0xdce3eaf1, 0xf8ff060d, 0x141b2229,
    0x30373e45, 0x4c535a61, 0x686f767d, 0x848b9299,
    0xa0a7aeb5, 0xbcc3cad1, 0xd8dfe6ed, 0xf4fb0209,
    0x10171e25, 0x2c333a41, 0x484f565d, 0x646b7279,
]


def _bytes_to_words(b):
    return [struct.unpack('>I', b[i:i + 4])[0] for i in range(0, len(b), 4)]


def _words_to_bytes(w):
    return b''.join(struct.pack('>I', x & 0xFFFFFFFF) for x in w)


def sm4_expand_key(key):
    mk = _bytes_to_words(key)
    k = [mk[i] ^ FK[i] for i in range(4)]
    rk = []
    for i in range(32):
        b = _Tp(k[1] ^ k[2] ^ k[3] ^ CK[i])
        k = [k[1], k[2], k[3], (k[0] ^ b) & 0xFFFFFFFF]
        rk.append(k[3])
    return rk


def sm4_crypt_block(rk, block):
    x = _bytes_to_words(block)
    for i in range(32):
        b = _T(x[1] ^ x[2] ^ x[3] ^ rk[i])
        x = [x[1], x[2], x[3], (x[0] ^ b) & 0xFFFFFFFF]
    return _words_to_bytes(reversed(x))


def sm4_encrypt(key, data, mode='ecb', iv=None):
    rk = sm4_expand_key(key)
    if mode == 'cbc':
        prev = iv or b'\x00' * 16
        out = b''
        for i in range(0, len(data), 16):
            blk = bytes(a ^ b for a, b in zip(data[i:i + 16], prev))
            prev = sm4_crypt_block(rk, blk)
            out += prev
        return out
    out = b''
    for i in range(0, len(data), 16):
        out += sm4_crypt_block(rk, data[i:i + 16])
    return out


def sm4_decrypt(key, data, mode='ecb', iv=None):
    rk = sm4_expand_key(key)[::-1]
    if mode == 'cbc':
        prev = iv or b'\x00' * 16
        out = b''
        for i in range(0, len(data), 16):
            cur = data[i:i + 16]
            out += bytes(a ^ b for a, b in zip(sm4_crypt_block(rk, cur), prev))
            prev = cur
        return out
    out = b''
    for i in range(0, len(data), 16):
        out += sm4_crypt_block(rk, data[i:i + 16])
    return out


def _aes(key, data, mode, iv, decrypt):
    from Crypto.Cipher import AES
    if mode == 'cbc':
        c = AES.new(key, AES.MODE_CBC, iv=iv or b'\x00' * 16)
    else:
        c = AES.new(key, AES.MODE_ECB)
    return c.decrypt(data) if decrypt else c.encrypt(data)


def encrypt(key, data, algo='sm4', mode='cbc', iv=None):
    if algo == 'sm4':
        return sm4_encrypt(key, data, mode, iv)
    return _aes(key, data, mode, iv, False)


def decrypt(key, data, algo='sm4', mode='cbc', iv=None):
    if algo == 'sm4':
        return sm4_decrypt(key, data, mode, iv)
    return _aes(key, data, mode, iv, True)


def pkcs7_pad(b, bs=16):
    n = bs - (len(b) % bs)
    return b + bytes([n]) * n


def pkcs7_unpad(b, bs=16):
    if not b:
        return b
    n = b[-1]
    if 1 <= n <= bs and len(b) >= n and b[-n:] == bytes([n]) * n:
        return b[:-n]
    return b


def try_parse(b):
    for cand in (b, pkcs7_unpad(b)):
        try:
            s = cand.decode('utf-8')
        except Exception:
            continue
        s2 = s.strip()
        if s2.startswith('{') or s2.startswith('['):
            try:
                return json.loads(s2)
            except Exception:
                pass
        if s2 and all(32 <= ord(c) < 127 or c in '\r\n\t' for c in s2):
            return s2
    return None


def _parse_bin(v, expect=None):
    if v is None:
        return None
    if isinstance(v, bytes):
        return v
    s = str(v).strip()
    if not s:
        return None
    if len(s) % 2 == 0 and re_hex(s):
        try:
            b = bytes.fromhex(s)
            if expect is None or len(b) == expect:
                return b
        except Exception:
            pass
    try:
        b = base64.b64decode(s, validate=True)
        if expect is None or len(b) == expect:
            return b
    except Exception:
        pass
    return s.encode('utf-8')


def re_hex(s):
    try:
        bytes.fromhex(s)
        return True
    except Exception:
        return False


class KeyMaterial(object):

    def __init__(self):
        self.algo = 'sm4'        
        self.mode = 'cbc'        
        self.key = None          
        self.iv = None           
        self.sign_secret = None  
        self.sign_template = None
        self.xs_secret = None
        self._send_skeleton = None   
        self._login_skeleton = None  

    def update_from(self, d):
        self.algo = (d.get('algo') or self.algo).lower()
        if self.algo not in ('sm4', 'aes'):
            self.algo = 'sm4'
        self.mode = (d.get('mode') or self.mode).lower()
        if self.mode not in ('cbc', 'ecb'):
            self.mode = 'cbc'
        if 'key' in d:
            exp = {'sm4': 16, 'aes': None}[self.algo]
            self.key = _parse_bin(d.get('key'), exp)
        if 'iv' in d:
            self.iv = _parse_bin(d.get('iv'), 16) if d.get('iv') else None
        if 'sign_secret' in d:
            self.sign_secret = d.get('sign_secret') or None
        if 'xs_secret' in d:
            self.xs_secret = d.get('xs_secret') or None
        if 'sign_template' in d:
            self.sign_template = d.get('sign_template') or None
        return self

    @property
    def complete(self):
        return bool(self.key) and len(self.key) in (16, 24, 32)

    def can_encrypt(self):
        return self.complete

    def can_decrypt(self):
        return self.complete

    def describe(self):
        return {
            'algo': self.algo, 'mode': self.mode,
            'key_set': bool(self.key),
            'key_len': len(self.key) if self.key else 0,
            'key_b64': base64.b64encode(self.key).decode() if self.key else None,
            'iv_set': bool(self.iv),
            'iv_b64': base64.b64encode(self.iv).decode() if self.iv else None,
            'sign_secret_set': bool(self.sign_secret),
            'complete': self.complete,
        }

    def decrypt_body(self, raw):
        if not self.complete:
            return None
        try:
            out = decrypt(self.key, raw, self.algo, self.mode, self.iv)
        except Exception as e:
            return {'error': '解密失败: %s' % e}
        val = try_parse(out)
        if val is None:
            return {'hex': out.hex()[:400], 'len': len(out),
                    'note': '解出内容非 JSON/文本（可能密钥或模式不匹配）'}
        return val

    def encrypt_body(self, obj):
        if not self.complete:
            return None
        if isinstance(obj, bytes):
            raw = obj
            if len(raw) % 16:
                raw = pkcs7_pad(raw, 16)
        elif isinstance(obj, (dict, list)):
            raw = json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            raw = pkcs7_pad(raw, 16)
        else:
            raw = pkcs7_pad(str(obj).encode('utf-8'), 16)
        return base64.b64encode(encrypt(self.key, raw, self.algo, self.mode, self.iv)).decode()

    def rebuild_send_code(self, tpl, phone, crib=None):
        obj = self._guess_plain(tpl, phone, self._send_skeleton, crib)
        if obj is None:
            return None
        return self.encrypt_body(obj)

    def rebuild_login(self, tpl, code, phone=None, crib=None):
        obj = self._guess_plain(tpl, code, self._login_skeleton, crib)
        if obj is None:
            return None
        return self.encrypt_body(obj)

    def _guess_plain(self, tpl, value, skeleton, crib=None):
        if skeleton is None:
            return None
        if isinstance(skeleton, dict):
            obj = dict(skeleton)
            placed = False
            for f in tpl['fields']:
                if f in obj:
                    obj[f] = value
                    placed = True
                    break
            if not placed:
                obj[tpl['fields'][0]] = value
            return obj
        if isinstance(skeleton, bytes):
            if crib:
                return self._replace_in_binary_anchored(skeleton, value, tpl['fields'], crib)
            return self._replace_in_binary(skeleton, value, tpl['fields'])
        return self._replace_in_text(str(skeleton), value, tpl['fields'])

    @staticmethod
    def _replace_in_binary_anchored(buf, value, fields, crib):
        import re as _re
        anchor = None
        for name, ob, nb in KeyMaterial._crib_variants(crib, None):
            p = buf.find(ob)
            if p >= 0:
                anchor = p
                break
        if anchor is None:
            return KeyMaterial._replace_in_binary(buf, value, fields)

        best = None
        phone_span = None
        for name, ob, nb in KeyMaterial._crib_variants(crib, None):
            p = buf.find(ob)
            if p >= 0:
                phone_span = (p, p + len(ob))
                break

        def overlaps_phone(s, e):
            if not phone_span:
                return False
            return not (e <= phone_span[0] or s >= phone_span[1])

        for lp in (1, 2):
            for m in _re.finditer(rb'\d{4,8}', buf):
                ln = len(m.group(0))
                if lp >= len(buf) - m.start():
                    continue
                prefix = buf[m.start() - lp:m.start()]
                try:
                    declared = int.from_bytes(prefix, 'big')
                except Exception:
                    continue
                if declared != ln:
                    continue
                nxt = buf[m.end():m.end() + 1]
                if nxt and 48 <= nxt[0] <= 57:
                    continue
                score = abs(m.start() - anchor)
                if not overlaps_phone(m.start(), m.end()):
                    if best is None or score < best[0]:
                        best = (score, m.start(), m.end())
                break

        if best is None:
            for m in _re.finditer(rb'(?<!\d)(\d{4,8})(?!\d)', buf):
                ln = len(m.group(0))
                if overlaps_phone(m.start(), m.end()):
                    continue
                score = abs(m.start() - anchor)
                if best is None or score < best[0]:
                    best = (score, m.start(), m.end())

        if best is None:
            return None
        _, s, e = best
        old = buf[s:e]
        new = value.encode('ascii', 'ignore')[:e - s].ljust(e - s, b'0')
        return buf[:s] + new + buf[e:]

    @staticmethod
    def _replace_in_text(text, value, fields):
        import re as _re
        for f in fields:
            pat = _re.compile(r'("%s"\s*:\s*")([^"]*)(")' % _re.escape(f), _re.I)
            if pat.search(text):
                return pat.sub(lambda m: m.group(1) + value + m.group(3), text, count=1)
        for f in fields:
            pat = _re.compile(r'("%s"\s*:\s*")(\d{4,11})(")' % _re.escape(f), _re.I)
            if pat.search(text):
                return pat.sub(lambda m: m.group(1) + value + m.group(3), text, count=1)
        return None

    @staticmethod
    def _replace_in_binary(buf, value, fields, crib=None):
        import re as _re

        for f in fields:
            for enc in (f.encode('utf-8'), f.encode('utf-16-le')):
                idx = buf.find(enc)
                if idx < 0:
                    continue
                for probe in (buf[idx + len(enc):idx + len(enc) + 4],
                              buf[idx + len(enc) + 1:idx + len(enc) + 5],
                              buf[idx + len(enc) + 2:idx + len(enc) + 6]):
                    m = _re.search(rb'\d{4,11}', probe)
                    if m:
                        start = idx + len(enc) + probe.index(m.group(0))
                        return buf[:start] + value.encode('ascii')[:len(m.group(0))].ljust(
                            len(m.group(0)), b'0') + buf[start + len(m.group(0)):]

        if crib:
            for enc_name, old_bytes, new_bytes in KeyMaterial._crib_variants(crib, value):
                if not new_bytes:
                    continue
                p = buf.find(old_bytes)
                if p < 0:
                    continue
                return buf[:p] + new_bytes + buf[p + len(old_bytes):]

        m = _re.search(rb'\d{11}', buf)
        if m:
            return buf[:m.start()] + value.encode('ascii')[:11].ljust(11, b'0') + buf[m.end():]
        m = _re.search(rb'\d{4,8}', buf)
        if m:
            return buf[:m.start()] + value.encode('ascii')[:len(m.group(0))].ljust(
                len(m.group(0)), b'0') + buf[m.end():]
        return None

    @staticmethod
    def _crib_variants(old, new):
        out = []

        def add(name, ob, nb):
            if not ob:
                return
            if nb is None:
                out.append((name, ob, None))
            elif len(ob) == len(nb):
                out.append((name, ob, nb))

        add('ascii', old.encode('ascii', 'ignore'),
            new.encode('ascii', 'ignore') if new is not None else None)
        try:
            add('utf16le', old.encode('utf-16-le'),
                new.encode('utf-16-le') if new is not None else None)
        except Exception:
            pass
        def bcd(s):
            b = bytearray()
            for i in range(0, len(s), 2):
                b.append((int(s[i]) << 4) | (int(s[i + 1]) if i + 1 < len(s) else 0xF))
            return bytes(b)
        if old.isdigit() and (new is None or new.isdigit()):
            add('bcd', bcd(old), bcd(new) if new is not None else None)
            for n in (4, 5, 8):
                try:
                    ov = int(old)
                    if ov < (1 << (8 * n)):
                        if new is None:
                            add('int%dbe' % n, ov.to_bytes(n, 'big'), None)
                            add('int%dle' % n, ov.to_bytes(n, 'little'), None)
                        else:
                            nv = int(new)
                            if nv < (1 << (8 * n)):
                                add('int%dbe' % n, ov.to_bytes(n, 'big'), nv.to_bytes(n, 'big'))
                                add('int%dle' % n, ov.to_bytes(n, 'little'), nv.to_bytes(n, 'little'))
                except Exception:
                    pass
        return out

    def set_skeleton(self, obj):
        self._skeleton = obj

    def learn_skeleton(self, send_cipher=None, login_cipher=None):
        res = {'send': None, 'login': None, 'ok': False}
        if not self.complete:
            return res
        for tag, ct in (('send', send_cipher), ('login', login_cipher)):
            if not ct:
                continue
            try:
                raw = decrypt(self.key, ct, self.algo, self.mode, self.iv)
            except Exception:
                continue
            plain = try_parse(raw)
            if plain is None:
                plain = try_parse(pkcs7_unpad(raw))
            if isinstance(plain, (dict, list)):
                res[tag] = plain
            elif isinstance(plain, str):
                res[tag] = plain
            else:
                res[tag] = raw
        self._send_skeleton = res['send']
        self._login_skeleton = res['login']
        res['ok'] = bool(res['send'] is not None or res['login'] is not None)
        return res

    def sign_headers(self, store, path, body_b64, base_headers):
        h = dict(base_headers)
        ts = str(int(time.time() * 1000))
        nonce = ''.join(random.choice('0123456789') for _ in range(8))
        h['x-time'] = ts
        h['x-nonce'] = nonce
        if self.sign_template:
            ctx = {
                'path': path, 'body': body_b64, 'body_md5': hashlib.md5(body_b64.encode()).hexdigest(),
                'time': ts, 'nonce': nonce, 'secret': self.sign_secret or '',
                'xs': self.xs_secret or '',
            }
            try:
                h['x-sign'] = self.sign_template.format(**ctx).strip()
            except Exception:
                pass
        elif self.sign_secret:
            for cand in (
                '%s%s%s%s' % (self.sign_secret, path, body_b64, ts),
                '%s%s%s%s' % (ts, self.sign_secret, path, body_b64),
                '%s%s%s' % (self.sign_secret, path, body_b64),
            ):
                h['x-sign'] = hashlib.md5(cand.encode('utf-8')).hexdigest()
                break
        if self.xs_secret:
            h['xs'] = hashlib.md5(('%s%s%s' % (self.xs_secret, ts, nonce)).encode('utf-8')).hexdigest()
        return h
