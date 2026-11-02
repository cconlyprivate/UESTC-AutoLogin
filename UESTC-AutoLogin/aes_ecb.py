#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""纯标准库实现的 AES-128-ECB（只做加密 + PKCS7 填充）。

为什么不用 pycryptodome：项目 .venv 里只有 requests，开机自启时多一个依赖就多一处故障点。
S-box 用 GF(2^8) 求逆 + 仿射变换现场生成，避免手抄表出错；正确性由内置测试向量保证。
"""

__all__ = ["aes128_ecb_encrypt", "aes_ecb_encrypt_b64", "selftest"]


def _build_sbox():
    # GF(2^8) 上的乘法逆元 + 仿射变换
    def mul(a, b):
        p = 0
        for _ in range(8):
            if b & 1:
                p ^= a
            hi = a & 0x80
            a = (a << 1) & 0xFF
            if hi:
                a ^= 0x1B
            b >>= 1
        return p

    inv = [0] * 256
    for i in range(1, 256):
        for j in range(1, 256):
            if mul(i, j) == 1:
                inv[i] = j
                break

    sbox = [0] * 256
    for i in range(256):
        x = inv[i]
        s = x
        for shift in range(1, 5):
            s ^= ((x << shift) | (x >> (8 - shift))) & 0xFF
        sbox[i] = s ^ 0x63
    return sbox


SBOX = _build_sbox()
RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _xtime(a):
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def _expand_key(key):
    assert len(key) == 16, "AES-128 需要 16 字节密钥"
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    for i in range(4, 44):
        temp = list(w[i - 1])
        if i % 4 == 0:
            temp = temp[1:] + temp[:1]                      # RotWord
            temp = [SBOX[b] for b in temp]                  # SubWord
            temp[0] ^= RCON[i // 4 - 1]
        w.append([w[i - 4][j] ^ temp[j] for j in range(4)])
    return [sum(w[4 * r:4 * r + 4], []) for r in range(11)]  # 11 个轮密钥，各 16 字节


def _encrypt_block(block, round_keys):
    s = [block[i] ^ round_keys[0][i] for i in range(16)]
    for rnd in range(1, 11):
        s = [SBOX[b] for b in s]                            # SubBytes
        # ShiftRows（state 按列存储：s[c*4 + r]）
        t = s[:]
        for r in range(1, 4):
            for c in range(4):
                s[c * 4 + r] = t[((c + r) % 4) * 4 + r]
        if rnd != 10:                                        # MixColumns
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                s[c * 4 + 0] = _xtime(a[0]) ^ (_xtime(a[1]) ^ a[1]) ^ a[2] ^ a[3]
                s[c * 4 + 1] = a[0] ^ _xtime(a[1]) ^ (_xtime(a[2]) ^ a[2]) ^ a[3]
                s[c * 4 + 2] = a[0] ^ a[1] ^ _xtime(a[2]) ^ (_xtime(a[3]) ^ a[3])
                s[c * 4 + 3] = (_xtime(a[0]) ^ a[0]) ^ a[1] ^ a[2] ^ _xtime(a[3])
        s = [s[i] ^ round_keys[rnd][i] for i in range(16)]   # AddRoundKey
    return bytes(s)


def aes128_ecb_encrypt(data, key):
    """PKCS7 填充后 ECB 加密，返回 bytes。"""
    if isinstance(data, str):
        data = data.encode("utf-8")
    pad = 16 - (len(data) % 16)
    data = data + bytes([pad]) * pad
    rk = _expand_key(key)
    return b"".join(_encrypt_block(data[i:i + 16], rk) for i in range(0, len(data), 16))


def aes_ecb_encrypt_b64(key_b64, plaintext):
    """portal 用的形式：密钥是 base64 字符串，输出 base64 字符串。"""
    import base64
    key = base64.b64decode(key_b64)
    return base64.b64encode(aes128_ecb_encrypt(plaintext, key)).decode("ascii")


def selftest():
    # FIPS-197 C.1
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    pt = bytes.fromhex("00112233445566778899aabbccddeeff")
    ct = aes128_ecb_encrypt(pt, key)
    # 加了 PKCS7 填充，16 字节明文会变成 2 个块；只比对第一块
    assert ct[:16].hex() == "69c4e0d86a7b0430d8cdb78070b4c55a", ct.hex()
    # 示例：croypto + 明文 -> password 字段
    got = aes_ecb_encrypt_b64("YnHmFS0kCcjy4oAtEtyxvg==", "Example123")
    assert got == "bWc/UncPbjnsN/lO2pbISg==", got
    got2 = aes_ecb_encrypt_b64("YnHmFS0kCcjy4oAtEtyxvg==", "{}")
    assert got2 == "INLPiRxercprTC47UZDX9Q==", got2
    return True


if __name__ == "__main__":
    print("selftest:", selftest())
