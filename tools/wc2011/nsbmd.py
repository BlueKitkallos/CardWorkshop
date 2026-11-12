"""WC2011 3D models: Nintendo NSBMD/NSBCA to glTF and back.

    nsbmd.py list    [--rom ROM] [--pac RPG3D.pac] [--match npc2]
    nsbmd.py info    npc206 [--rom ROM]
    nsbmd.py decode  npc206 [--anims ma01,ma02] [--out build/nsbmd/npc206]
    nsbmd.py encode  model.gltf --base npc206 --out build/nsbmd/kaiba.lznsbmd
    nsbmd.py verify  [npc206 ...] [--all]
    nsbmd.py inject  kaiba.lznsbmd --as npc206 --out build/nsbmd/test.nds

Every command reads the modder's own WC2011 ROM (default: Makefile ROM11).
Format notes: docs/findings/story-mode.md "WC2011 3D characters".
"""
import argparse
import base64
import json
import math
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nttx
import pac

DEFAULT_ROM = "rom/Yu-Gi-Oh! 5D's - World Championship 2011 - Over the Nexus (Europe) (En,Ja,Fr,De,Es,It).nds"
DEFAULT_PAC = 'Data_arc_pac/RPG3D.pac'


def lz11_decompress(data):
    return nttx.lz_decompress(data)


def lz11_compress(data):
    n = len(data)
    out = bytearray([0x11]) + (n.to_bytes(3, 'little') if n < 1 << 24 else b'\0\0\0' + n.to_bytes(4, 'little'))
    heads = {}
    i = 0
    while i < n:
        flag_pos = len(out)
        out.append(0)
        flags = 0
        for bit in range(7, -1, -1):
            if i >= n:
                break
            best_len, best_disp = 0, 0
            if i + 3 <= n:
                cands = heads.get(data[i:i + 3], ())
                limit = min(0x10110, n - i)
                for j in reversed(cands[-64:]):
                    if i - j > 0x1000:
                        break
                    ln = 3
                    while ln < limit and data[j + ln] == data[i + ln]:
                        ln += 1
                    if ln > best_len:
                        best_len, best_disp = ln, i - j
                        if ln == limit:
                            break
            if best_len >= 3:
                flags |= 1 << bit
                disp = best_disp - 1
                if best_len <= 0x10:
                    out += bytes([(best_len - 1) << 4 | disp >> 8, disp & 0xff])
                elif best_len <= 0x110:
                    ln = best_len - 0x11
                    out += bytes([ln >> 4, (ln & 15) << 4 | disp >> 8, disp & 0xff])
                else:
                    ln = best_len - 0x111
                    out += bytes([0x10 | ln >> 12, (ln >> 4) & 0xff, (ln & 15) << 4 | disp >> 8, disp & 0xff])
                step = best_len
            else:
                out.append(data[i])
                step = 1
            for k in range(i, min(i + step, n - 2)):
                heads.setdefault(data[k:k + 3], []).append(k)
            i += step
        out[flag_pos] = flags
    while len(out) % 4:
        out.append(0)
    return bytes(out)


def fx(v, bits=32):
    if v >= 1 << (bits - 1):
        v -= 1 << bits
    return v / 4096.0


def to_fx(f, bits=32):
    v = int(round(f * 4096))
    lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    v = max(lo, min(hi, v))
    return v & ((1 << bits) - 1)


def align(b, n=4):
    return b + b'\0' * (-len(b) % n)


def read_dict(d, p):
    cnt = d[p + 1]
    q = p + struct.unpack_from('<H', d, p + 6)[0]
    esz, dsz = struct.unpack_from('<HH', d, q)
    ents = [bytes(d[q + 4 + esz * i:q + 4 + esz * (i + 1)]) for i in range(cnt)]
    names = [bytes(d[q + dsz + 16 * i:q + dsz + 16 * i + 16]).rstrip(b'\0').decode('latin1') for i in range(cnt)]
    return names, ents


def ptree(names):
    keys = [int.from_bytes(n.encode('latin1').ljust(16, b'\0'), 'little') for n in names]
    B, L, R, K, E = {0: 127}, {0: 0}, {0: 0}, {0: 0}, {0: 0}

    def side(t, k):
        return R if t != 0 and (k >> B[t]) & 1 else L

    for idx, k in enumerate(keys):
        t, p = 0, L[0]
        while B[p] < B[t]:
            t, p = p, side(p, k)[p]
        if K[p] == k and p != 0:
            raise ValueError(f'duplicate name {names[idx]}')
        i = (k ^ K[p]).bit_length() - 1
        t, p = 0, L[0]
        while B[p] < B[t] and B[p] > i:
            t, p = p, side(p, k)[p]
        z = idx + 1
        B[z], K[z], E[z] = i, k, idx
        if (k >> i) & 1:
            R[z], L[z] = z, p
        else:
            L[z], R[z] = z, p
        side(t, k)[t] = z
    num, seq = {0: 0}, []
    stack = [L[0]] if L[0] else []
    while stack:
        nd = stack.pop()
        num[nd] = len(num)
        seq.append(nd)
        for c in (R[nd], L[nd]):
            if B[c] < B[nd] and c not in num:
                stack.append(c)
    out = [(127, num[L[0]] if names else 0, 0, 0)]
    out += [(B[nd], num[L[nd]], num[R[nd]], E[nd]) for nd in seq]
    return out


def write_dict(names, ents, esz):
    n = len(names)
    tree = b''.join(bytes(t) for t in ptree(names))
    ent_ofs = 8 + len(tree)
    body = struct.pack('<HH', esz, 4 + esz * n) + b''.join(ents)
    body += b''.join(nm.encode('latin1').ljust(16, b'\0') for nm in names)
    size = ent_ofs + len(body)
    return struct.pack('<BBHHH', 0, n, size, 8, ent_ofs) + tree + body


def dict_size(n, esz):
    return 8 + 4 * (n + 1) + 4 + esz * n + 16 * n


SBC_LEN = {0x00: 0, 0x01: 0, 0x02: 2, 0x03: 1, 0x04: 1, 0x24: 1, 0x44: 1, 0x05: 1, 0x06: 3, 0x26: 4, 0x46: 4,
           0x66: 5, 0x07: 1, 0x27: 2, 0x47: 2, 0x67: 3, 0x08: 1, 0x28: 2, 0x48: 2, 0x68: 3, 0x0a: 8, 0x0b: 0,
           0x2b: 0, 0x0c: 2, 0x0d: 2, 0x40: 0, 0x80: 0}


def sbc_ops(sbc):
    p, ops = 0, []
    while p < len(sbc):
        op = sbc[p]
        if op == 0x09:
            ln = 2 + 3 * sbc[p + 2]
        else:
            ln = SBC_LEN[op]
        ops.append((op, list(sbc[p + 1:p + 1 + ln])))
        p += 1 + ln
        if op == 0x01:
            break
    return ops


GX_LEN = {0x00: 0, 0x10: 1, 0x11: 0, 0x12: 1, 0x13: 1, 0x14: 1, 0x15: 0, 0x16: 16, 0x17: 12, 0x18: 16, 0x19: 12,
          0x1a: 9, 0x1b: 3, 0x1c: 3, 0x20: 1, 0x21: 1, 0x22: 1, 0x23: 2, 0x24: 1, 0x25: 1, 0x26: 1, 0x27: 1,
          0x28: 1, 0x29: 1, 0x2a: 1, 0x2b: 1, 0x30: 1, 0x31: 1, 0x32: 1, 0x33: 1, 0x34: 32, 0x40: 1, 0x41: 0}


def gx_cmds(dl):
    p, cmds = 0, []
    while p + 4 <= len(dl):
        ops = dl[p:p + 4]
        p += 4
        for op in ops:
            n = GX_LEN[op]
            cmds.append((op, list(struct.unpack_from(f'<{n}I', dl, p))))
            p += 4 * n
    return cmds


def gx_pack(cmds):
    out = bytearray()
    for i in range(0, len(cmds), 4):
        grp = cmds[i:i + 4]
        ops = [c[0] for c in grp] + [0] * (4 - len(grp))
        out += bytes(ops)
        for _, params in grp:
            out += struct.pack(f'<{len(params)}I', *params)
    return bytes(out)


def s16(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >= 1 << (bits - 1) else v


def decode_dl(dl):
    prims, cur, vtx = [], None, [0, 0, 0]
    state = {'mtx': None, 'uv': None, 'nrm': None, 'col': None}
    scale = (1.0, 1.0, 1.0)
    for op, p in gx_cmds(dl):
        if op == 0x14:
            state['mtx'] = p[0] & 31
            scale = (1.0, 1.0, 1.0)
        elif op == 0x1b:
            scale = tuple(fx(v) * k for v, k in zip(p, scale))
        elif op == 0x40:
            cur = {'type': p[0] & 3, 'verts': []}
            prims.append(cur)
        elif op == 0x41:
            cur = None
        elif op == 0x22:
            state['uv'] = (s16(p[0], 16) / 16.0, s16(p[0] >> 16, 16) / 16.0)
        elif op == 0x21:
            state['nrm'] = tuple(s16(p[0] >> s, 10) / 512.0 for s in (0, 10, 20))
        elif op == 0x20:
            state['col'] = tuple(((p[0] >> s) & 31) / 31.0 for s in (0, 5, 10))
        elif op in (0x23, 0x24, 0x25, 0x26, 0x27, 0x28):
            if op == 0x23:
                vtx = [s16(p[0], 16), s16(p[0] >> 16, 16), s16(p[1], 16)]
            elif op == 0x24:
                vtx = [s16(p[0] >> s, 10) << 6 for s in (0, 10, 20)]
            elif op == 0x25:
                vtx = [s16(p[0], 16), s16(p[0] >> 16, 16), vtx[2]]
            elif op == 0x26:
                vtx = [s16(p[0], 16), vtx[1], s16(p[0] >> 16, 16)]
            elif op == 0x27:
                vtx = [vtx[0], s16(p[0], 16), s16(p[0] >> 16, 16)]
            else:
                vtx = [vtx[k] + s16(p[0] >> s, 10) for k, s in enumerate((0, 10, 20))]
            cur['verts'].append({'pos': tuple(v / 4096.0 * k for v, k in zip(vtx, scale)), 'raw': tuple(vtx), **state})
        elif op in (0x00, 0x29, 0x2a, 0x2b, 0x30, 0x31, 0x32, 0x33, 0x34):
            pass
        else:
            raise ValueError(f'GX command {op:#x} not handled')
    return prims


def triangles(prim):
    v, t = prim['verts'], prim['type']
    if t == 0:
        return [(v[i], v[i + 1], v[i + 2]) for i in range(0, len(v) - 2, 3)]
    if t == 1:
        out = []
        for i in range(0, len(v) - 3, 4):
            out += [(v[i], v[i + 1], v[i + 2]), (v[i], v[i + 2], v[i + 3])]
        return out
    if t == 2:
        return [(v[i], v[i + 1], v[i + 2]) if i % 2 == 0 else (v[i + 1], v[i], v[i + 2]) for i in range(len(v) - 2)]
    out = []
    for i in range(0, len(v) - 3, 2):
        out += [(v[i], v[i + 1], v[i + 3]), (v[i], v[i + 3], v[i + 2])]
    return out


TEX_BPP = {1: 8, 2: 2, 3: 4, 4: 8, 5: 2, 6: 8, 7: 16}
FORMAT_NAMES = {1: 'a3i5', 2: 'pal4', 3: 'pal16', 4: 'pal256', 5: 'tex4x4', 6: 'a5i3', 7: 'direct'}


def tex_dims(param):
    return 8 << ((param >> 20) & 7), 8 << ((param >> 23) & 7)


def parse_node(raw):
    flag, m00 = struct.unpack_from('<Hh', raw, 0)
    p = 4
    t = r = s = None
    if not flag & 1:
        t = [fx(v) for v in struct.unpack_from('<3I', raw, p)]
        p += 12
    if not flag & 2:
        if flag & 8:
            a, b = (fx(v, 16) for v in struct.unpack_from('<2H', raw, p))
            p += 4
            r = pivot(((flag >> 4) & 15), ((flag >> 8) & 15), a, b)
        else:
            m = [m00 / 4096.0] + [fx(v, 16) for v in struct.unpack_from('<8H', raw, p)]
            p += 16
            r = np.array(m).reshape(3, 3)
    if not flag & 4:
        s = [fx(v) for v in struct.unpack_from('<3I', raw, p)]
        p += 24
    return t, r, s, p


def node_size(raw):
    return parse_node(raw)[3]


def pivot(sel, neg, a, b):
    o = -1.0 if neg & 1 else 1.0
    c = -b if neg & 2 else b
    d = -a if neg & 4 else a
    m = {0: [o, 0, 0, 0, a, b, 0, c, d], 1: [0, o, 0, a, 0, b, c, 0, d], 2: [0, 0, o, a, b, 0, c, d, 0],
         3: [0, a, b, o, 0, 0, 0, c, d], 4: [a, 0, b, 0, o, 0, c, 0, d], 5: [a, b, 0, 0, 0, o, c, d, 0],
         6: [0, a, b, 0, c, d, o, 0, 0], 7: [a, 0, b, c, 0, d, 0, o, 0], 8: [a, b, 0, c, d, 0, 0, 0, o]}[sel]
    return np.array(m, float).reshape(3, 3)


def basis(v):
    inp = [v[4], v[0], v[1], v[2], v[3]]
    out = [0] * 6
    for i in range(5):
        out[i] = inp[i] >> 3
        out[5] = (out[5] << 3) | (inp[i] & 7)
    f = [s16(x, 13) / 4096.0 for x in out]
    a = np.array([f[1], f[2], f[3]])
    b = np.array([f[4], f[0], f[5]])
    return np.vstack([a, b, np.cross(a, b)])


def node_matrix(t, r, s):
    m = np.eye(4)
    if s is not None:
        m = np.diag([s[0], s[1], s[2], 1.0])
    if r is not None:
        rr = np.eye(4)
        rr[:3, :3] = r.T
        m = rr @ m
    if t is not None:
        tt = np.eye(4)
        tt[:3, 3] = t
        m = tt @ m
    return m


def parse_bmd(data):
    d = data
    if d[:4] != b'BMD0':
        raise ValueError('not an NSBMD (BMD0) file')
    nsec = struct.unpack_from('<H', d, 14)[0]
    secs = struct.unpack_from(f'<{nsec}I', d, 16)
    ir = {'version': struct.unpack_from('<H', d, 6)[0], 'models': [], 'tex': None}
    for so in secs:
        tag = d[so:so + 4]
        if tag == b'MDL0':
            names, ents = read_dict(d, so + 8)
            for nm, e in zip(names, ents):
                ir['models'].append(parse_model(d, so + struct.unpack('<I', e)[0], nm))
        elif tag == b'TEX0':
            ir['tex'] = parse_tex(d, so)
        else:
            raise ValueError(f'section {tag!r} not handled')
    return ir


def parse_model(d, mo, name):
    size, osbc, omat, oshp, oevp = struct.unpack_from('<5I', d, mo)
    m = {'name': name, 'info': bytes(d[mo + 0x14:mo + 0x40])}
    nn, ne = read_dict(d, mo + 0x40)
    offs = [mo + 0x40 + struct.unpack('<I', e)[0] for e in ne]
    m['nodes'] = []
    for i, (nm, o) in enumerate(zip(nn, offs)):
        ln = node_size(bytes(d[o:o + 0x40]))
        m['nodes'].append({'name': nm, 'raw': bytes(d[o:o + ln])})
    m['sbc'] = bytes(d[mo + osbc:mo + omat])
    mb = mo + omat
    otex, opal = struct.unpack_from('<HH', d, mb)
    mn, me = read_dict(d, mb + 4)
    m['materials'] = []
    for nm, e in zip(mn, me):
        o = mb + struct.unpack('<I', e)[0]
        sz = struct.unpack_from('<H', d, o + 2)[0]
        m['materials'].append({'name': nm, 'raw': bytes(d[o:o + sz])})
    for key, off in (('tex_bind', otex), ('pal_bind', opal)):
        bn, be = read_dict(d, mb + off)
        m[key] = []
        for nm, e in zip(bn, be):
            lo, cnt, flag = struct.unpack('<HBB', e)
            m[key].append({'name': nm, 'mats': list(d[mb + lo:mb + lo + cnt]), 'flag': flag})
    sb = mo + oshp
    sn, se = read_dict(d, sb)
    m['shapes'] = []
    for nm, e in zip(sn, se):
        o = sb + struct.unpack('<I', e)[0]
        tag, sz, flag, odl, sdl = struct.unpack_from('<HHIII', d, o)
        m['shapes'].append({'name': nm, 'tag': tag, 'flag': flag, 'dl': bytes(d[o + odl:o + odl + sdl])})
    m['evp'] = bytes(d[mo + oevp:mo + size])
    return m


def parse_tex(d, so):
    h = struct.unpack_from('<IHHHHI IHHHHII IHHHHI', d, so + 8)
    (_, tsz, tdict, tflag, _, tofs, _, csz, cdict, cflag, _, cofs, ciofs, _, psz, pflag, pdict, _, pofs) = h
    tn, te = read_dict(d, so + tdict)
    pn, pe = read_dict(d, so + pdict)
    tex = {'flags': (tflag, cflag, pflag), 'textures': [], 'palettes': []}
    for nm, e in zip(tn, te):
        param, extra = struct.unpack('<II', e)
        fmt = (param >> 26) & 7
        w, hh = tex_dims(param)
        ln = w * hh * TEX_BPP[fmt] // 8
        off = (param & 0xffff) << 3
        t = {'name': nm, 'param': param & ~0xffff, 'extra': extra}
        if fmt == 5:
            t['data'] = bytes(d[so + cofs + off:so + cofs + off + ln])
            t['idx'] = bytes(d[so + ciofs + off // 2:so + ciofs + off // 2 + ln // 2])
        else:
            t['data'] = bytes(d[so + tofs + off:so + tofs + off + ln])
        tex['textures'].append(t)
    pal_end = psz << 3
    starts = []
    for nm, e in zip(pn, pe):
        o, flag = struct.unpack('<HH', e)
        starts.append((o << 3, nm, flag))
    ordered = sorted({s for s, _, _ in starts})
    for s, nm, flag in starts:
        nxt = next((x for x in ordered if x > s), pal_end)
        tex['palettes'].append({'name': nm, 'flag': flag, 'data': bytes(d[so + pofs + s:so + pofs + nxt])})
    return tex


def build_model(m):
    n = len(m['nodes'])
    node_dict_sz = dict_size(n, 4)
    ndata, offs, o = b'', [], node_dict_sz
    for nd in m['nodes']:
        offs.append(o)
        ndata += nd['raw']
        o += len(nd['raw'])
    nodes = write_dict([x['name'] for x in m['nodes']], [struct.pack('<I', x) for x in offs], 4) + ndata
    sbc = align(m['sbc'])
    mats = m['materials']
    nm = len(mats)
    mdict_sz = dict_size(nm, 4)
    tb, pb = m['tex_bind'], m['pal_bind']
    otex = 4 + mdict_sz
    opal = otex + dict_size(len(tb), 4)
    olist = opal + dict_size(len(pb), 4)
    lists, tents, pents = b'', [], []
    for binds, ents in ((tb, tents), (pb, pents)):
        for b in binds:
            ents.append(struct.pack('<HBB', olist + len(lists), len(b['mats']), b['flag']))
            lists += bytes(b['mats'])
    omdata = olist + len(align(lists))
    mofs, o = [], omdata
    for x in mats:
        mofs.append(o)
        o += len(x['raw'])
    matblk = struct.pack('<HH', otex, opal)
    matblk += write_dict([x['name'] for x in mats], [struct.pack('<I', x) for x in mofs], 4)
    matblk += write_dict([b['name'] for b in tb], tents, 4)
    matblk += write_dict([b['name'] for b in pb], pents, 4)
    matblk += align(lists) + b''.join(x['raw'] for x in mats)
    shapes = m['shapes']
    ns = len(shapes)
    sdict_sz = dict_size(ns, 4)
    hdrs, dls = b'', b''
    dl_base = sdict_sz + 16 * ns
    for i, s in enumerate(shapes):
        ho = sdict_sz + 16 * i
        hdrs += struct.pack('<HHIII', s['tag'], 16, s['flag'], dl_base + len(dls) - ho, len(s['dl']))
        dls += align(s['dl'])
    shpblk = write_dict([s['name'] for s in shapes], [struct.pack('<I', sdict_sz + 16 * i) for i in range(ns)], 4)
    shpblk += hdrs + dls
    osbc = 0x40 + len(nodes)
    omat = osbc + len(sbc)
    oshp = omat + len(matblk)
    oevp = oshp + len(shpblk)
    size = oevp + len(m['evp'])
    return struct.pack('<5I', size, osbc, omat, oshp, oevp) + m['info'] + nodes + sbc + matblk + shpblk + m['evp']


def build_tex(tex):
    texs, pals = tex['textures'], tex['palettes']
    plain, comp, cidx, tents = b'', b'', b'', []
    for t in texs:
        fmt = (t['param'] >> 26) & 7
        if fmt == 5:
            off = len(comp)
            comp += t['data']
            cidx += t['idx']
        else:
            off = len(plain)
            plain += t['data']
        tents.append((t, off))
    tdict = write_dict([t['name'] for t in texs], [struct.pack('<II', t['param'] | (off >> 3), t['extra'])
                                                    for t, off in tents], 8)
    pdata, pents, seen = b'', [], {}
    for p in pals:
        if p['data'] not in seen:
            seen[p['data']] = len(pdata)
            pdata += align(p['data'], 16)
        o = seen[p['data']]
        pents.append(struct.pack('<HH', o >> 3, p['flag']))
    pdict = write_dict([p['name'] for p in pals], pents, 4)
    otd = 0x3c
    opd = otd + len(tdict)
    otex = opd + len(pdict)
    ocomp = otex + len(plain)
    ocidx = ocomp + len(comp)
    opal = ocidx + len(cidx)
    tf, cf, pf = tex['flags']
    hdr = struct.pack('<IHHHHI IHHHHII IHHHHI', 0, len(plain) >> 3, otd, tf, 0, otex,
                      0, len(comp) >> 3, otd, cf, 0, ocomp, ocidx,
                      0, len(pdata) >> 3, pf, opd, 0, opal)
    body = hdr + tdict + pdict + plain + comp + cidx + pdata
    return b'TEX0' + struct.pack('<I', 8 + len(body)) + body


def build_bmd(ir):
    models = [build_model(m) for m in ir['models']]
    mdict_sz = dict_size(len(models), 4)
    offs, o = [], 8 + mdict_sz
    for mb in models:
        offs.append(o)
        o += len(mb)
    mdl = write_dict([m['name'] for m in ir['models']], [struct.pack('<I', x) for x in offs], 4) + b''.join(models)
    mdl = b'MDL0' + struct.pack('<I', 8 + len(mdl)) + mdl
    secs = [mdl] + ([build_tex(ir['tex'])] if ir['tex'] else [])
    hdr_len = 16 + 4 * len(secs)
    offs, o = [], hdr_len
    for s in secs:
        offs.append(o)
        o += len(s)
    return (b'BMD0' + struct.pack('<HHIHH', 0xfeff, ir['version'], o, 16, len(secs)) +
            struct.pack(f'<{len(secs)}I', *offs) + b''.join(secs))


def parse_bca(data):
    d = data
    if d[:4] != b'BCA0':
        raise ValueError('not an NSBCA (BCA0) file')
    so = struct.unpack_from('<I', d, 16)[0]
    names, ents = read_dict(d, so + 8)
    return [parse_anim(d, so + struct.unpack('<I', e)[0], nm) for nm, e in zip(names, ents)]


def parse_anim(d, ao, name):
    if d[ao:ao + 4] != b'J\0AC':
        raise ValueError('not a joint animation')
    nframes, nnodes, _, orot3, orot5 = struct.unpack_from('<HHIII', d, ao + 4)
    tags = struct.unpack_from(f'<{nnodes}H', d, ao + 0x14)

    def curve(p, kind):
        info, off = struct.unpack_from('<II', d, p)
        r = info >> 30
        last = (info >> 16) & 0x1fff
        half = info >> 29 & 1
        n = nframes if r == 0 else (last >> r) + (nframes - last)
        if kind == 'r':
            vals = [rot(v) for v in struct.unpack_from(f'<{n}H', d, ao + off)]
        elif kind == 't':
            vals = [fx(v, 16) for v in struct.unpack_from(f'<{n}H', d, ao + off)] if half else \
                   [fx(v) for v in struct.unpack_from(f'<{n}I', d, ao + off)]
        else:
            vals = [fx(v, 16) for v in struct.unpack_from(f'<{2 * n}H', d, ao + off)[::2]] if half else \
                   [fx(v) for v in struct.unpack_from(f'<{2 * n}I', d, ao + off)[::2]]
        return {'step': r, 'last': last, 'vals': vals}

    def rot(v):
        if v & 0x8000:
            sn, a, b = struct.unpack_from('<HHH', d, ao + orot3 + 6 * (v & 0x7fff))
            return pivot(sn & 15, (sn >> 4) & 15, fx(a, 16), fx(b, 16))
        return basis(struct.unpack_from('<5H', d, ao + orot5 + 10 * (v & 0x7fff)))

    nodes = []
    for tg in tags:
        p = ao + tg
        flag = struct.unpack_from('<I', d, p)[0]
        p += 4
        nd = {'id': flag >> 24, 't': None, 'r': None, 's': None, 'flag': flag}
        if flag & 1:
            nodes.append(nd)
            continue
        if not flag & 6:
            nd['t'] = []
            for k in range(3):
                if flag & (8 << k):
                    nd['t'].append(fx(struct.unpack_from('<I', d, p)[0]))
                    p += 4
                else:
                    nd['t'].append(curve(p, 't'))
                    p += 8
        elif flag & 2:
            nd['t'] = [0.0, 0.0, 0.0]
        if not flag & 0xc0:
            if flag & 0x100:
                nd['r'] = rot(struct.unpack_from('<H', d, p)[0])
                p += 4
            else:
                nd['r'] = curve(p, 'r')
                p += 8
        elif flag & 0x40:
            nd['r'] = np.eye(3)
        if not flag & 0x600:
            nd['s'] = []
            for k in range(3):
                if flag & (0x800 << k):
                    nd['s'].append(fx(struct.unpack_from('<I', d, p)[0]))
                    p += 8
                else:
                    nd['s'].append(curve(p, 's'))
                    p += 8
        elif flag & 0x200:
            nd['s'] = [1.0, 1.0, 1.0]
        nodes.append(nd)
    return {'name': name, 'frames': nframes, 'nodes': nodes}


def mat_anims(data, magic, section, stamp, parse):
    d = data
    if d[:4] != magic:
        raise ValueError(f'not a {magic.decode()} file')
    so = struct.unpack_from('<I', d, 16)[0]
    if d[so:so + 4] != section:
        raise ValueError(f'{magic.decode()}: no {section.decode()} section')
    names, ents = read_dict(d, so + 8)
    out = []
    for nm, e in zip(names, ents):
        ao = so + struct.unpack('<I', e)[0]
        if d[ao:ao + 4] != stamp:
            raise ValueError(f'{nm}: not a material animation')
        nframes = struct.unpack_from('<H', d, ao + 4)[0]
        mn, me = read_dict(d, ao + 8)
        out.append({'name': nm, 'frames': nframes, 'mats': {m: parse(d, ao, nframes, x) for m, x in zip(mn, me)}})
    return out


def mat_curve(last, step, vals):
    return {'step': step, 'last': last, 'vals': vals} if len(vals) > 1 else vals[0]


def parse_bma(data):
    def rgb(v):
        return np.array([round((v >> k & 31) / 31, 4) for k in (0, 5, 10)])

    def chan(d, ao, nframes, info, color):
        last, step = (info >> 16) & 0x1fff, info >> 30
        if info & 0x20000000:
            return rgb(info & 0xffff) if color else (info & 31) / 31
        n = nframes if step == 0 else (last >> step) + (nframes - last)
        off = ao + (info & 0xffff)
        vals = [rgb(v) for v in struct.unpack_from(f'<{n}H', d, off)] if color else \
            [(v & 31) / 31 for v in d[off:off + n]]
        return mat_curve(last, step, vals)

    def mat(d, ao, nframes, e):
        infos = struct.unpack('<5I', e)
        return {k: chan(d, ao, nframes, i, k != 'alpha')
                for k, i in zip(('diffuse', 'ambient', 'specular', 'emission', 'alpha'), infos)}
    return mat_anims(data, b'BMA0', b'MAT0', b'M\0AM', mat)


def parse_bta(data):
    def chan(d, ao, nframes, raw, rot):
        last, flags, val = struct.unpack('<HxBI', raw)
        step = flags >> 6
        if flags & 0x20:
            vals = [val]
        else:
            n = nframes if step == 0 else (last >> step) + (nframes - last)
            vals = list(struct.unpack_from(f'<{n}H' if flags & 0x10 and not rot else f'<{n}I', d, ao + val))
        if rot:
            vals = [math.atan2(fx(v & 0xffff, 16), fx(v >> 16, 16)) for v in vals]
        else:
            vals = [fx(v, 16) if flags & 0x10 and not flags & 0x20 else fx(v) for v in vals]
        return mat_curve(last, step, vals)

    def mat(d, ao, nframes, e):
        return {k: chan(d, ao, nframes, e[8 * i:8 * i + 8], k == 'rot')
                for i, k in enumerate(('sS', 'sT', 'rot', 'tS', 'tT'))}
    return mat_anims(data, b'BTA0', b'SRT0', b'M\0AT', mat)


def sample(c, f):
    if not isinstance(c, dict):
        return c
    v, r = c['vals'], c['step']
    if r == 0:
        return v[min(f, len(v) - 1)]
    s = 1 << r
    if f >= c['last']:
        return v[min(len(v) - 1, (c['last'] >> r) + f - c['last'])]
    i, fr = f >> r, (f & (s - 1)) / s
    if fr == 0 or i + 1 >= len(v):
        return v[min(i, len(v) - 1)]
    return v[i] * (1 - fr) + v[i + 1] * fr


def c555(c):
    return np.array([c & 31, (c >> 5) & 31, (c >> 10) & 31], np.int32)


def expand(rgb5):
    rgb5 = np.asarray(rgb5, np.int32)
    return (rgb5 << 3) | (rgb5 >> 2)


def block_colors(pal, addr, mode):
    c = [c555(pal[addr + k]) if addr + k < len(pal) else np.zeros(3, np.int32) for k in range(4)]
    if mode == 0:
        return [(c[0], 255), (c[1], 255), (c[2], 255), (c[0], 0)]
    if mode == 1:
        return [(c[0], 255), (c[1], 255), ((c[0] + c[1]) // 2, 255), (c[0], 0)]
    if mode == 2:
        return [(c[k], 255) for k in range(4)]
    return [(c[0], 255), (c[1], 255), ((c[0] * 5 + c[1] * 3) // 8, 255), ((c[0] * 3 + c[1] * 5) // 8, 255)]


def decode_texture(t, pal_data):
    fmt = (t['param'] >> 26) & 7
    w, h = tex_dims(t['param'])
    pal = list(struct.unpack(f'<{len(pal_data) // 2}H', pal_data[:len(pal_data) // 2 * 2])) if pal_data else []
    c0t = (t['param'] >> 29) & 1
    out = np.zeros((h, w, 4), np.uint8)
    data = t['data']
    if fmt == 5:
        words = struct.unpack(f'<{w * h // 16}I', data)
        idx = struct.unpack(f'<{w * h // 16}H', t['idx'])
        for b in range(w * h // 16):
            bx, by = (b % (w // 4)) * 4, (b // (w // 4)) * 4
            cols = block_colors(pal, (idx[b] & 0x3fff) << 1, idx[b] >> 14)
            for k in range(16):
                rgb, a = cols[(words[b] >> (2 * k)) & 3]
                out[by + k // 4, bx + k % 4] = (*expand(rgb), a)
        return out
    if fmt == 7:
        v = np.frombuffer(data, '<u2').reshape(h, w).astype(np.int32)
        out[..., 0], out[..., 1], out[..., 2] = expand(v & 31), expand((v >> 5) & 31), expand((v >> 10) & 31)
        out[..., 3] = np.where(v >> 15, 255, 0)
        return out
    raw = np.frombuffer(data, np.uint8).astype(np.int32)
    if fmt in (2, 3):
        bits = TEX_BPP[fmt]
        per = 8 // bits
        ix = np.stack([(raw >> (bits * k)) & ((1 << bits) - 1) for k in range(per)], 1).reshape(-1)
        alpha = np.where((ix == 0) & bool(c0t), 0, 255)
    elif fmt == 4:
        ix = raw.astype(np.int32)
        alpha = np.where((ix == 0) & bool(c0t), 0, 255)
    elif fmt == 1:
        ix, a = raw & 31, raw >> 5
        alpha = ((a << 2) | (a >> 1)) * 255 // 31
    else:
        ix, a = raw & 7, raw >> 3
        alpha = a * 255 // 31
    palarr = np.array([c555(c) for c in pal] or [np.zeros(3, np.int32)])
    rgb = expand(palarr[np.minimum(ix, len(palarr) - 1)])
    out[..., :3] = rgb.reshape(h, w, 3)
    out[..., 3] = np.asarray(alpha).reshape(h, w)
    return out


def to5(rgb8):
    return np.clip((np.asarray(rgb8, np.int32) * 31 + 127) // 255, 0, 31)


def pack555(c5):
    return int(c5[0]) | int(c5[1]) << 5 | int(c5[2]) << 10


def encode_tex4x4(img):
    h, w = img.shape[:2]
    pal, where = [], {}
    words, idxs = [], []

    def place(seq):
        key = tuple(seq)
        if key in where:
            return where[key]
        n = len(seq)
        for o in range(0, max(0, len(pal) - n + 1), 2):
            if tuple(pal[o:o + n]) == key:
                where[key] = o
                return o
        if len(pal) % 2:
            pal.append(0)
        o = len(pal)
        pal.extend(seq)
        where[key] = o
        return o

    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            blk = img[by:by + 4, bx:bx + 4].reshape(16, 4).astype(np.int32)
            opaque = blk[:, 3] >= 128
            px5 = to5(blk[:, :3])
            words_k, mode, seq = choose_block(px5, opaque)
            o = place([pack555(c) for c in seq])
            words.append(sum(k << (2 * i) for i, k in enumerate(words_k)))
            idxs.append(mode << 14 | (o >> 1))
    if len(pal) % 2:
        pal.append(0)
    data = struct.pack(f'<{len(words)}I', *words)
    idx = struct.pack(f'<{len(idxs)}H', *idxs)
    return data, idx, struct.pack(f'<{len(pal)}H', *pal)


def choose_block(px5, opaque):
    cols = sorted({tuple(c) for c, o in zip(px5.tolist(), opaque) if o})
    has_t = not opaque.all()
    if not cols:
        return [3] * 16, 0, [np.zeros(3, np.int32)] * 2

    def assign(table, allow_t):
        ks, err = [], 0
        for c, o in zip(px5, opaque):
            if not o:
                ks.append(3)
                continue
            d = [int(((c - t) ** 2).sum()) for t in table]
            k = int(np.argmin(d))
            ks.append(k)
            err += d[k]
        return ks, err

    best = None
    arr = [np.array(c) for c in cols]
    pairs = [(a, b) for a in range(len(arr)) for b in range(len(arr))] if len(arr) <= 6 else []
    if len(arr) > 6:
        m = np.array(cols, float)
        mean = m.mean(0)
        u = np.linalg.svd(m - mean)[2][0]
        proj = (m - mean) @ u
        lo, hi = np.array(cols[int(np.argmin(proj))]), np.array(cols[int(np.argmax(proj))])
        arr = arr + [lo, hi]
        pairs = [(len(arr) - 2, len(arr) - 1), (len(arr) - 1, len(arr) - 2)]
    for a, b in pairs:
        c0, c1 = arr[a], arr[b]
        if has_t:
            t1 = [c0, c1, (c0 + c1) // 2]
            ks, err = assign(t1, True)
            cand = (err, 1, ks, [c0, c1])
        else:
            t3 = [c0, c1, (c0 * 5 + c1 * 3) // 8, (c0 * 3 + c1 * 5) // 8]
            ks, err = assign(t3, False)
            cand = (err, 3, ks, [c0, c1])
        if best is None or cand[0] < best[0]:
            best = cand
        if best[0] == 0:
            break
    if best is None or best[0] > 0:
        n = 3 if has_t else 4
        if len(cols) <= n:
            table = [np.array(c) for c in cols]
        else:
            table = kmeans([np.array(c) for c, o in zip(px5.tolist(), opaque) if o], n)
        while len(table) < n:
            table.append(table[-1])
        ks, err = assign(table, has_t)
        cand = (err, 0 if has_t else 2, ks, table)
        if best is None or err < best[0]:
            best = cand
    err, mode, ks, table = best
    return ks, mode, table


def kmeans(points, k, iters=8):
    pts = np.array(points, float)
    cent = [pts[0]]
    for _ in range(1, k):
        d = np.min([((pts - c) ** 2).sum(1) for c in cent], 0)
        cent.append(pts[int(np.argmax(d))])
    cent = np.array(cent)
    for _ in range(iters):
        lab = np.argmin(((pts[:, None] - cent[None]) ** 2).sum(2), 1)
        for j in range(k):
            if (lab == j).any():
                cent[j] = pts[lab == j].mean(0)
    return [np.clip(np.round(c), 0, 31).astype(np.int32) for c in cent]


def encode_paletted(img, fmt, ncol, c0t):
    h, w = img.shape[:2]
    px = img.reshape(-1, 4).astype(np.int32)
    opaque = px[:, 3] >= 128
    c5 = to5(px[:, :3])
    uniq = sorted({tuple(c) for c, o in zip(c5.tolist(), opaque) if o})
    base = 1 if c0t else 0
    room = ncol - base
    table = [np.array(c) for c in uniq] if len(uniq) <= room else kmeans([np.array(c) for c, o in zip(c5.tolist(), opaque) if o], room)
    tarr = np.array(table)
    ix = np.argmin(((c5[:, None] - tarr[None]) ** 2).sum(2), 1) + base
    if c0t:
        ix = np.where(opaque, ix, 0)
    pal = ([0] if c0t else []) + [pack555(c) for c in table]
    pal += [0] * (-len(pal) % 4)
    bits = TEX_BPP[fmt]
    per = 8 // bits
    ix = ix.reshape(-1, per)
    data = bytes(int(sum(int(v) << (bits * k) for k, v in enumerate(row))) for row in ix)
    return data, struct.pack(f'<{len(pal)}H', *pal)


def encode_translucent(img, fmt):
    ncol, abits = (32, 3) if fmt == 1 else (8, 5)
    px = img.reshape(-1, 4).astype(np.int32)
    c5 = to5(px[:, :3])
    seen = px[:, 3] > 0
    uniq = sorted({tuple(c) for c, o in zip(c5.tolist(), seen) if o}) or [(0, 0, 0)]
    table = [np.array(c) for c in uniq] if len(uniq) <= ncol else kmeans([np.array(c) for c, o in zip(c5.tolist(), seen) if o], ncol)
    tarr = np.array(table)
    ix = np.argmin(((c5[:, None] - tarr[None]) ** 2).sum(2), 1)
    if fmt == 1:
        a = np.array([min(range(8), key=lambda k: abs(((k << 2) | (k >> 1)) * 255 // 31 - al)) for al in px[:, 3]])
    else:
        a = np.array([min(range(32), key=lambda k: abs(k * 255 // 31 - al)) for al in px[:, 3]])
    data = (ix | a << (8 - abits)).astype(np.uint8).tobytes()
    pal = [pack555(c) for c in table]
    pal += [0] * (-len(pal) % 4)
    return data, struct.pack(f'<{len(pal)}H', *pal)


def encode_texture(img, like):
    fmt = (like['param'] >> 26) & 7
    h, w = img.shape[:2]
    lw, lh = (w.bit_length() - 4), (h.bit_length() - 4)
    if 8 << lw != w or 8 << lh != h:
        raise ValueError(f"{like['name']}: {w}x{h} is not a power of two from 8 to 1024")
    param = (like['param'] & ~(0x3f << 20)) | lw << 20 | lh << 23
    extra = (like['extra'] & ~0x3fffff) | w | (h << 11)
    if fmt == 5:
        data, idx, pal = encode_tex4x4(img)
        return {'name': like['name'], 'param': param, 'extra': extra, 'data': data, 'idx': idx}, pal
    if fmt in (2, 3, 4):
        data, pal = encode_paletted(img, fmt, {2: 4, 3: 16, 4: 256}[fmt], (param >> 29) & 1)
    elif fmt in (1, 6):
        data, pal = encode_translucent(img, fmt)
    else:
        px = img.reshape(-1, 4).astype(np.int32)
        c5 = to5(px[:, :3])
        v = c5[:, 0] | c5[:, 1] << 5 | c5[:, 2] << 10 | np.where(px[:, 3] >= 128, 0x8000, 0)
        data, pal = v.astype('<u2').tobytes(), b''
    return {'name': like['name'], 'param': param, 'extra': extra, 'data': data}, pal


def rest_local(m):
    out = []
    for nd in m['nodes']:
        t, r, s, _ = parse_node(nd['raw'])
        out.append(node_matrix(t, r, s))
    return out


def run_sbc(m, local=None):
    local = local or rest_local(m)
    n = len(m['nodes'])
    world, parent = [np.eye(4)] * n, [None] * n
    stack, slot_node, slot_scaled = {}, {}, {}
    body_slots = None
    cur, cur_node, scaled = np.eye(4), None, False
    mat, draws = None, []
    for op, p in sbc_ops(m['sbc']):
        base = op & 0x1f
        if op == 0x0b:
            scaled = True
        elif op == 0x2b:
            scaled = False
        elif base == 0x03:
            cur, cur_node, scaled = stack[p[0]], slot_node[p[0]], slot_scaled[p[0]]
        elif base == 0x06:
            node, par = p[0], p[1]
            if op in (0x46, 0x66):
                src = p[3] if op == 0x46 else p[4]
                cur, scaled = stack[src], slot_scaled[src]
            cur = cur @ local[node]
            cur_node = node
            world[node] = cur
            parent[node] = par if node != par else None
            if op in (0x26, 0x66):
                stack[p[3]], slot_node[p[3]], slot_scaled[p[3]] = cur, node, scaled
        elif base == 0x04:
            mat = p[0]
        elif base == 0x05:
            draws.append({'shape': p[0], 'mat': mat, 'node': cur_node, 'scaled': scaled})
            if p[0] == 0 and body_slots is None:
                body_slots = dict(slot_node)
        elif base == 0x09:
            raise ValueError('envelope (0x09) skinning not supported yet')
    # Only the body shape restores slots. A slot stored again after it (npc33's hip slot, later neck_spine) means its node at that draw.
    return {'world': world, 'parent': parent, 'slot_node': {**slot_node, **(body_slots or {})}, 'slot_scaled': slot_scaled, 'draws': draws,
            'pos_scale': struct.unpack_from('<i', m['info'], 8)[0] / 4096}


def vertex_scale(scene, draw, v):
    if v['mtx'] is not None and v['mtx'] in scene['slot_scaled']:
        return scene['pos_scale'] if scene['slot_scaled'][v['mtx']] else 1.0
    return scene['pos_scale'] if draw['scaled'] else 1.0


def model_mesh(m, scene=None):
    scene = scene or run_sbc(m)
    world, slot_node = scene['world'], scene['slot_node']
    meshes = []
    for dr in scene['draws']:
        shp = m['shapes'][dr['shape']]
        tris = []
        for prim in decode_dl(shp['dl']):
            for tri in triangles(prim):
                vs = []
                for v in tri:
                    node = slot_node[v['mtx']] if v['mtx'] is not None else dr['node']
                    w = world[node]
                    pos = (w @ np.array([*v['pos'], 1.0]))[:3]
                    nrm = None
                    if v['nrm'] is not None:
                        nrm = w[:3, :3] @ np.array(v['nrm'])
                        ln = np.linalg.norm(nrm)
                        nrm = nrm / ln if ln else nrm
                    vs.append({'pos': pos, 'nrm': nrm, 'uv': v['uv'], 'col': v['col'], 'node': node})
                tris.append(vs)
        meshes.append({'shape': dr['shape'], 'mat': dr['mat'], 'node': dr['node'], 'tris': tris})
    return meshes


def mat_texture(m, mi):
    tex = next((b['name'] for b in m['tex_bind'] if mi in b['mats']), None)
    pal = next((b['name'] for b in m['pal_bind'] if mi in b['mats']), None)
    return tex, pal


def mat_fields(raw):
    tag, sz, difamb, speemi, polyattr, pmask, teximg, tmask, pbase, flag, ow, oh = struct.unpack_from('<HHIIIIIIHHHH', raw)
    return {'difamb': difamb, 'polyattr': polyattr, 'teximg': teximg, 'flag': flag, 'w': ow, 'h': oh}


def mat_to_quat(r):
    m = r
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    q = np.array(q)
    return (q / np.linalg.norm(q)).tolist()


def decompose(mtx):
    t = mtx[:3, 3]
    a = mtx[:3, :3]
    s = np.linalg.norm(a, axis=0)
    r = a / np.where(s == 0, 1, s)
    if np.linalg.det(r) < 0:
        s[0] = -s[0]
        r[:, 0] = -r[:, 0]
    return t.tolist(), mat_to_quat(r), s.tolist()


def anim_locals(m, anim, frame):
    rest = [parse_node(nd['raw'])[:3] for nd in m['nodes']]
    out = []
    for i, (rt, rr, rs) in enumerate(rest):
        an = anim['nodes'][i] if i < len(anim['nodes']) else None
        if an is None or an['flag'] & 1:
            out.append(node_matrix(None, None, None) if an is not None else node_matrix(rt, rr, rs))
            continue
        t = [sample(c, frame) for c in an['t']] if an['t'] is not None else rt
        r = an['r'] if an['r'] is None or isinstance(an['r'], np.ndarray) else sample(an['r'], frame)
        if an['r'] is None:
            r = rr
        s = [sample(c, frame) for c in an['s']] if an['s'] is not None else rs
        out.append(node_matrix(t, r, s))
    return out


class GltfWriter:
    def __init__(self):
        self.bin = bytearray()
        self.g = {'asset': {'version': '2.0', 'generator': 'tools/wc2011/nsbmd.py'}, 'buffers': [], 'bufferViews': [],
                  'accessors': [], 'nodes': [], 'meshes': [], 'materials': [], 'textures': [], 'images': [],
                  'samplers': [], 'skins': [], 'animations': [], 'scenes': [{'nodes': []}], 'scene': 0}

    def acc(self, arr, ctype, typ, target=None, minmax=False):
        arr = np.ascontiguousarray(arr)
        while len(self.bin) % 4:
            self.bin.append(0)
        bv = {'buffer': 0, 'byteOffset': len(self.bin), 'byteLength': arr.nbytes}
        if target:
            bv['target'] = target
        self.bin += arr.tobytes()
        self.g['bufferViews'].append(bv)
        a = {'bufferView': len(self.g['bufferViews']) - 1, 'componentType': ctype, 'count': len(arr), 'type': typ}
        if minmax:
            a['min'] = arr.min(0).tolist() if arr.ndim > 1 else [float(arr.min())]
            a['max'] = arr.max(0).tolist() if arr.ndim > 1 else [float(arr.max())]
        self.g['accessors'].append(a)
        return len(self.g['accessors']) - 1

    def save(self, path):
        name = os.path.splitext(os.path.basename(path))[0] + '.bin'
        self.g['buffers'] = [{'uri': name, 'byteLength': len(self.bin)}]
        g = {k: v for k, v in self.g.items() if v != []}
        open(os.path.join(os.path.dirname(path), name), 'wb').write(self.bin)
        json.dump(g, open(path, 'w'), indent=1)


def export_gltf(ir, path, anims=()):
    from PIL import Image
    m = ir['models'][0]
    out_dir = os.path.dirname(path)
    os.makedirs(out_dir, exist_ok=True)
    scene = run_sbc(m)
    world = scene['world']
    gw = GltfWriter()
    g = gw.g
    for i, nd in enumerate(m['nodes']):
        t, r, s, _ = parse_node(nd['raw'])
        tt, q, ss = decompose(node_matrix(t, r, s))
        g['nodes'].append({'name': nd['name'], 'translation': tt, 'rotation': q, 'scale': ss})
    for i, par in enumerate(scene['parent']):
        if par is not None:
            g['nodes'][par].setdefault('children', []).append(i)
    roots = [i for i, par in enumerate(scene['parent']) if par is None]
    ibm = np.array([np.linalg.pinv(world[i]).T for i in range(len(m['nodes']))], np.float32)
    g['skins'].append({'joints': list(range(len(m['nodes']))), 'inverseBindMatrices': gw.acc(ibm, 5126, 'MAT4'),
                       'skeleton': roots[0], 'name': m['name']})
    pals = {p['name']: p['data'] for p in ir['tex']['palettes']} if ir['tex'] else {}
    texs = {t['name']: t for t in ir['tex']['textures']} if ir['tex'] else {}
    wrap = {0: 33071, 1: 10497, 3: 33648}
    for mi, mat in enumerate(m['materials']):
        f = mat_fields(mat['raw'])
        tn, pn = mat_texture(m, mi)
        gm = {'name': mat['name'], 'doubleSided': (f['polyattr'] >> 6 & 3) == 3,
              'pbrMetallicRoughness': {'metallicFactor': 0.0, 'roughnessFactor': 1.0},
              'extras': {'nsbmd_lights': f['polyattr'] & 15,
                         'xluDepth': bool(f['polyattr'] & (1 << 11))}}
        alpha = (f['polyattr'] >> 16) & 31
        if 0 < alpha < 31:
            gm['pbrMetallicRoughness']['baseColorFactor'] = [1, 1, 1, alpha / 31]
            gm['alphaMode'] = 'BLEND'
        if not f['polyattr'] & 15:
            gm['extensions'] = {'KHR_materials_unlit': {}}
            g.setdefault('extensionsUsed', ['KHR_materials_unlit'])
        if tn in texs:
            img = decode_texture(texs[tn], pals.get(pn, b''))
            fn = f'{tn}.png'
            Image.fromarray(img).save(os.path.join(out_dir, fn))
            if (img[..., 3] < 255).any() and gm.get('alphaMode') != 'BLEND':
                gm['alphaMode'] = 'MASK'
            ws = wrap[(f['teximg'] >> 16) & 1 | ((f['teximg'] >> 18) & 1) << 1]
            wt = wrap[(f['teximg'] >> 17) & 1 | ((f['teximg'] >> 19) & 1) << 1]
            g['samplers'].append({'magFilter': 9728, 'minFilter': 9728, 'wrapS': ws, 'wrapT': wt})
            g['images'].append({'uri': fn, 'name': tn})
            g['textures'].append({'source': len(g['images']) - 1, 'sampler': len(g['samplers']) - 1, 'name': tn})
            gm['pbrMetallicRoughness']['baseColorTexture'] = {'index': len(g['textures']) - 1}
        g['materials'].append(gm)
    mesh_nodes = []
    for mesh in model_mesh(m, scene):
        shp = m['shapes'][mesh['shape']]
        f = mat_fields(m['materials'][mesh['mat']]['raw'])
        tw, th = max(f['w'], 1), max(f['h'], 1)
        flat = [v for tri in mesh['tris'] for v in tri]
        if not flat:
            continue
        attrs = {'POSITION': gw.acc(np.array([v['pos'] for v in flat], np.float32), 5126, 'VEC3', 34962, True)}
        if flat[0]['nrm'] is not None:
            attrs['NORMAL'] = gw.acc(np.array([v['nrm'] for v in flat], np.float32), 5126, 'VEC3', 34962)
        if flat[0]['uv'] is not None:
            attrs['TEXCOORD_0'] = gw.acc(np.array([(v['uv'][0] / tw, v['uv'][1] / th) for v in flat], np.float32),
                                         5126, 'VEC2', 34962)
        if flat[0]['col'] is not None:
            attrs['COLOR_0'] = gw.acc(np.array([v['col'] for v in flat], np.float32), 5126, 'VEC3', 34962)
        attrs['JOINTS_0'] = gw.acc(np.array([(v['node'], 0, 0, 0) for v in flat], np.uint16), 5123, 'VEC4', 34962)
        attrs['WEIGHTS_0'] = gw.acc(np.array([(1, 0, 0, 0)] * len(flat), np.float32), 5126, 'VEC4', 34962)
        g['meshes'].append({'name': shp['name'], 'primitives': [{'attributes': attrs, 'material': mesh['mat']}],
                            'extras': {'nsbmd_shape_flag': shp['flag'], 'nsbmd_node': m['nodes'][mesh['node']]['name']}})
        g['nodes'].append({'name': shp['name'], 'mesh': len(g['meshes']) - 1, 'skin': 0})
        mesh_nodes.append(len(g['nodes']) - 1)
    g['scenes'][0]['nodes'] = roots + mesh_nodes
    for anim in anims:
        add_animation(gw, m, anim)
    gw.save(path)


def add_animation(gw, m, anim):
    g = gw.g
    n = anim['frames']
    times = gw.acc(np.arange(n, dtype=np.float32) / 30.0, 5126, 'SCALAR', minmax=True)
    per = [anim_locals(m, anim, f) for f in range(n)]
    channels, samplers = [], []
    for i in range(len(m['nodes'])):
        dec = [decompose(per[f][i]) for f in range(n)]
        for k, (path, typ) in enumerate((('translation', 'VEC3'), ('rotation', 'VEC4'), ('scale', 'VEC3'))):
            vals = np.array([d[k] for d in dec], np.float32)
            if k == 1:
                for j in range(1, len(vals)):
                    if np.dot(vals[j], vals[j - 1]) < 0:
                        vals[j] = -vals[j]
            samplers.append({'input': times, 'output': gw.acc(vals, 5126, typ), 'interpolation': 'LINEAR'})
            channels.append({'sampler': len(samplers) - 1, 'target': {'node': i, 'path': path}})
    g['animations'].append({'name': anim['name'], 'channels': channels, 'samplers': samplers})


GL_TYPES = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
GL_COUNT = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


class Gltf:
    def __init__(self, path):
        self.dir = os.path.dirname(os.path.abspath(path))
        raw = open(path, 'rb').read()
        self.blobs = []
        if raw[:4] == b'glTF':
            p = 12
            chunks = []
            while p < len(raw):
                ln, typ = struct.unpack_from('<II', raw, p)
                chunks.append((typ, raw[p + 8:p + 8 + ln]))
                p += 8 + ln
            self.g = json.loads(chunks[0][1])
            glb_bin = next((c for t, c in chunks if t == 0x004E4942), b'')
        else:
            self.g = json.loads(raw)
            glb_bin = b''
        for b in self.g.get('buffers', []):
            uri = b.get('uri')
            if uri is None:
                self.blobs.append(glb_bin)
            elif uri.startswith('data:'):
                self.blobs.append(base64.b64decode(uri.split(',', 1)[1]))
            else:
                self.blobs.append(open(os.path.join(self.dir, uri), 'rb').read())

    def view(self, i):
        bv = self.g['bufferViews'][i]
        b = self.blobs[bv['buffer']]
        o = bv.get('byteOffset', 0)
        return b[o:o + bv['byteLength']], bv.get('byteStride')

    def acc(self, i):
        a = self.g['accessors'][i]
        dt = np.dtype(GL_TYPES[a['componentType']])
        n = GL_COUNT[a['type']]
        data, stride = self.view(a['bufferView'])
        o = a.get('byteOffset', 0)
        if stride and stride != dt.itemsize * n:
            arr = np.array([np.frombuffer(data, dt, n, o + k * stride) for k in range(a['count'])])
        else:
            arr = np.frombuffer(data, dt, a['count'] * n, o).reshape(a['count'], n)
        if a.get('normalized') and dt != np.float32:
            arr = arr.astype(np.float64) / np.iinfo(dt).max
        return arr.astype(np.float64) if dt == np.float32 or a.get('normalized') else arr

    def image(self, tex_index):
        from PIL import Image
        import io
        img = self.g['images'][self.g['textures'][tex_index]['source']]
        if 'uri' in img:
            if img['uri'].startswith('data:'):
                return Image.open(io.BytesIO(base64.b64decode(img['uri'].split(',', 1)[1])))
            from urllib.parse import unquote
            return Image.open(os.path.join(self.dir, unquote(img['uri'])))
        data, _ = self.view(img['bufferView'])
        return Image.open(io.BytesIO(data))


def gl_triangles(gl, prim):
    attrs = prim['attributes']
    pos = gl.acc(attrs['POSITION'])
    n = len(pos)
    idx = gl.acc(prim['indices']).reshape(-1) if 'indices' in prim else np.arange(n)
    mode = prim.get('mode', 4)
    if mode == 4:
        tris = idx.reshape(-1, 3)
    elif mode == 5:
        tris = np.array([(idx[i], idx[i + 1], idx[i + 2]) if i % 2 == 0 else (idx[i + 1], idx[i], idx[i + 2])
                         for i in range(len(idx) - 2)])
    else:
        raise ValueError(f'primitive mode {mode} not supported (triangles only)')
    get = lambda k: gl.acc(attrs[k]) if k in attrs else None
    return tris, pos, get('NORMAL'), get('TEXCOORD_0'), get('COLOR_0'), get('JOINTS_0'), get('WEIGHTS_0')


def strips(tris):
    edges = {}
    for t, tri in enumerate(tris):
        for k in range(3):
            edges.setdefault((tri[k], tri[(k + 1) % 3]), []).append(t)
    used = [False] * len(tris)

    def nbrs(t):
        a, b, c = tris[t]
        return [u for e in ((b, a), (c, b), (a, c)) for u in edges.get(e, ()) if not used[u]]

    def extend(seq, taken):
        while True:
            a, b = (seq[-1], seq[-2]) if len(seq) % 2 else (seq[-2], seq[-1])
            nt = next((u for u in edges.get((a, b), ()) if not used[u]), None)
            if nt is None:
                return
            third = [v for v in tris[nt] if v not in (a, b)]
            if len(third) != 1:
                return
            used[nt] = True
            taken.append(nt)
            seq.append(third[0])

    out = []
    while True:
        free = [t for t in range(len(tris)) if not used[t]]
        if not free:
            return out
        t0 = min(free, key=lambda t: len(nbrs(t)))
        best = None
        for rot in range(3):
            tri = list(tris[t0][rot:] + tris[t0][:rot])
            used[t0] = True
            fwd, taken = list(tri), [t0]
            extend(fwd, taken)
            for t in taken:
                used[t] = False
            if best is None or len(taken) > len(best[1]):
                best = (fwd, taken)
        for t in best[1]:
            used[t] = True
        out.append(best[0])


def occlusion_order(units, size=(256, 192), fov=30.0, tol=0.15, rounds=8):
    tris = np.array([t for u in units for t in u], float)
    owner = np.repeat(np.arange(len(units)), [len(u) for u in units])
    lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    at, h = (lo + hi) / 2, max(hi - lo)
    W, H = size
    s = H / 2 / math.tan(math.radians(fov / 2))
    n = len(units)
    occ = np.zeros((n, n))
    for az in range(-180, 180, 30):
        for el in (15, 35, 55):
            a, e = math.radians(az), math.radians(el)
            eye = at + 2.4 * h * np.array([math.sin(a) * math.cos(e), math.sin(e), math.cos(a) * math.cos(e)])
            f = (at - eye) / np.linalg.norm(at - eye)
            r = np.cross(f, [0, 1, 0])
            r /= np.linalg.norm(r)
            p = (tris - eye) @ np.array([r, np.cross(r, f), -f]).T
            z = -p[..., 2]
            x, y = W / 2 + p[..., 0] / z * s, H / 2 - p[..., 1] / z * s
            near, depth = np.full((H, W), -1), np.full((H, W), np.inf)
            hits = []
            for i in range(len(tris)):
                (x0, x1, x2), (y0, y1, y2) = x[i], y[i]
                area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
                if area >= 0:
                    continue
                xa, xb = max(0, int(min(x[i]))), min(W - 1, int(max(x[i])) + 1)
                ya, yb = max(0, int(min(y[i]))), min(H - 1, int(max(y[i])) + 1)
                if xa > xb or ya > yb:
                    continue
                X, Y = np.meshgrid(np.arange(xa, xb + 1) + .5, np.arange(ya, yb + 1) + .5)
                w0 = ((x1 - X) * (y2 - Y) - (x2 - X) * (y1 - Y)) / area
                w1 = ((x2 - X) * (y0 - Y) - (x0 - X) * (y2 - Y)) / area
                inside = (w0 >= 0) & (w1 >= 0) & (w0 + w1 <= 1)
                if not inside.any():
                    continue
                d = (w0 * z[i, 0] + w1 * z[i, 1] + (1 - w0 - w1) * z[i, 2])[inside]
                py, px = np.nonzero(inside)
                py, px = py + ya, px + xa
                hits.append((owner[i], py, px, d))
                win = d < depth[py, px]
                depth[py[win], px[win]] = d[win]
                near[py[win], px[win]] = owner[i]
            weight = 3.0 if abs(az) <= 90 else 1.0
            for u, py, px, d in hits:
                behind = d > depth[py, px] + tol
                np.add.at(occ, (near[py[behind], px[behind]], u), weight)
    np.fill_diagonal(occ, 0)
    c = np.array([tris[owner == k].reshape(-1, 3).mean(0) for k in range(n)])
    order = list(np.argsort(-np.hypot(c[:, 0] - at[0], c[:, 2] - at[2])))

    def cost(o):
        pos = np.empty(n, int)
        pos[o] = np.arange(n)
        return occ[pos[:, None] > pos[None, :]].sum()

    best = cost(order)
    for _ in range(rounds):
        for v in list(order):
            order.remove(v)
            rest = np.array(order, int)
            gain = np.concatenate([[0], np.cumsum(occ[v, rest])]) + np.concatenate([np.cumsum(occ[rest, v][::-1])[::-1], [0]])
            order.insert(int(np.argmin(gain)), v)
        now = cost(order)
        if now >= best:
            break
        best = now
    return order, best, occ.sum()


def emit_shape(verts_list, use_restore, use_nrm, use_uv, use_col, slot_of, world, quads=False, scale=1):
    cmds = []
    scale_cmd = (0x1b, [to_fx(scale)] * 3)
    if scale != 1 and not use_restore:
        cmds.append(scale_cmd)
    keyed, tris = {}, []
    for tri in verts_list:
        ids = []
        for v in tri:
            k = (v['node'], v['raw'], v.get('uvq'), v.get('nq'), v.get('cq'))
            if k not in keyed:
                keyed[k] = len(keyed)
            ids.append(keyed[k])
        if len(set(ids)) == 3:
            tris.append(tuple(ids))
    verts = [None] * len(keyed)
    for k, i in keyed.items():
        verts[i] = k
    cur_slot, last = None, None
    runs = []
    if quads:
        qs, tris = quad_pairs(tris, verts, world)
        for seq in quad_strips(qs):
            if len(seq) > 4:
                runs.append((3, seq))
            else:
                a, b, d, c = seq
                tris += [(a, b, c), (a, c, d)]
    runs += [(2 if len(seq) > 3 else 0, seq) for seq in strips(tris)]
    for kind, seq in runs:
        if kind == 2 and len(seq) == 4 and is_planar_quad([verts[i] for i in seq], world):
            kind, seq = 1, [seq[1], seq[3], seq[2], seq[0]]
        cmds.append((0x40, [kind]))
        last = None
        for vi in seq:
            node, raw, uvq, nq, cq = verts[vi]
            if use_restore and slot_of[node] != cur_slot:
                cur_slot = slot_of[node]
                cmds.append((0x14, [cur_slot]))
                if scale != 1:
                    cmds.append(scale_cmd)
            if use_uv:
                cmds.append((0x22, [uvq]))
            if use_nrm:
                cmds.append((0x21, [nq]))
            if use_col:
                cmds.append((0x20, [cq]))
            cmds.append(vtx_cmd(raw, last))
            last = raw
        cmds.append((0x41, []))
    return gx_pack(cmds)


def quad_pairs(tris, verts, world):
    edge = {}
    for t, tri in enumerate(tris):
        for k in range(3):
            edge[(tri[k], tri[(k + 1) % 3])] = t
    cands = []
    for t, tri in enumerate(tris):
        for k in range(3):
            a, b, c = tri[k], tri[(k + 1) % 3], tri[(k + 2) % 3]
            u = edge.get((b, a))
            if u is None or u <= t:
                continue
            d = next(v for v in tris[u] if v not in (a, b))
            quad = [c, a, d, b]
            if is_planar_quad([verts[i] for i in quad], world, strict=True):
                cands.append((t, u, quad))
    used, quads = set(), []
    for t, u, quad in cands:
        if t in used or u in used:
            continue
        used |= {t, u}
        quads.append(quad)
    rest = [tri for t, tri in enumerate(tris) if t not in used]
    return quads, rest


def quad_strips(quads):
    by_edge = {}
    for q, quad in enumerate(quads):
        for k in range(4):
            by_edge[(quad[k], quad[(k + 1) % 4])] = (q, k)
    used = [False] * len(quads)
    out = []
    for q0 in range(len(quads)):
        if used[q0]:
            continue
        best = None
        for k0 in range(4):
            cur = quads[q0][k0:] + quads[q0][:k0]
            seq, taken = [cur[0], cur[1], cur[3], cur[2]], [q0]
            used[q0] = True
            while True:
                nxt = by_edge.get((cur[3], cur[2]))
                if nxt is None or used[nxt[0]]:
                    break
                q, k = nxt
                cur = [quads[q][(k + j) % 4] for j in range(4)]
                seq += [cur[3], cur[2]]
                used[q] = True
                taken.append(q)
            for t in taken:
                used[t] = False
            if best is None or len(taken) > len(best[1]):
                best = (seq, taken)
        for t in best[1]:
            used[t] = True
        out.append(best[0])
    return out


def is_planar_quad(vs, world, strict=False):
    # Rest-pose coplanarity does not survive animation across a joint. The DS
    # renders a quad as one polygon, so keep those faces as triangles.
    if len({v[0] for v in vs}) > 1:
        return False
    p = [(world[v[0]] @ np.array([*v[1], 4096.0]))[:3] for v in vs]
    n = np.cross(p[1] - p[0], p[2] - p[0])
    ln = np.linalg.norm(n)
    if not ln:
        return False
    if strict:
        d1, d2 = p[0] - p[3], p[1] - p[2]
        if np.dot(np.cross(p[1] - p[0], p[3] - p[0]), np.cross(p[3] - p[2], p[0] - p[2])) <= 0:
            return False
        return abs(np.dot(p[3] - p[0], n / ln)) < 0.01 * max(np.linalg.norm(d1), np.linalg.norm(d2))
    return abs(np.dot(p[3] - p[0], n / ln)) < 8


def vtx_cmd(raw, last):
    x, y, z = raw
    if last is not None:
        d = [a - b for a, b in zip(raw, last)]
        if all(-512 <= v <= 511 for v in d):
            return 0x28, [(d[0] & 0x3ff) | (d[1] & 0x3ff) << 10 | (d[2] & 0x3ff) << 20]
        if z == last[2]:
            return 0x25, [(x & 0xffff) | (y & 0xffff) << 16]
        if y == last[1]:
            return 0x26, [(x & 0xffff) | (z & 0xffff) << 16]
        if x == last[0]:
            return 0x27, [(y & 0xffff) | (z & 0xffff) << 16]
    if x % 64 == 0 and y % 64 == 0 and z % 64 == 0:
        return 0x24, [((x >> 6) & 0x3ff) | ((y >> 6) & 0x3ff) << 10 | ((z >> 6) & 0x3ff) << 20]
    return 0x23, [(x & 0xffff) | (y & 0xffff) << 16, z & 0xffff]


def pack_col(c):
    return sum(min(31, max(0, int(round(c[k] * 31)))) << (5 * k) for k in range(3))


def recolour_dl(dl, fn):
    cmds = gx_cmds(dl)
    out = []
    for op, p in cmds:
        if op == 0x20:
            c = tuple(((p[0] >> s) & 31) / 31.0 for s in (0, 5, 10))
            p = [pack_col(fn(c))]
        out.append((op, p))
    return gx_pack(out)


def recolour(ir, fn, materials=None):
    m = ir['models'][0]
    for dr in run_sbc(m)['draws']:
        if materials is not None and m['materials'][dr['mat']]['name'] not in materials:
            continue
        shp = m['shapes'][dr['shape']]
        shp['dl'] = recolour_dl(shp['dl'], fn)
    return ir


def move_vertices_dl(dl, fn):
    out, vtx = [], [0, 0, 0]
    for op, p in gx_cmds(dl):
        if op in (0x23, 0x24, 0x25, 0x26, 0x27, 0x28):
            if op == 0x23:
                vtx = [s16(p[0], 16), s16(p[0] >> 16, 16), s16(p[1], 16)]
            elif op == 0x24:
                vtx = [s16(p[0] >> s, 10) << 6 for s in (0, 10, 20)]
            elif op == 0x25:
                vtx = [s16(p[0], 16), s16(p[0] >> 16, 16), vtx[2]]
            elif op == 0x26:
                vtx = [s16(p[0], 16), vtx[1], s16(p[0] >> 16, 16)]
            elif op == 0x27:
                vtx = [vtx[0], s16(p[0], 16), s16(p[0] >> 16, 16)]
            else:
                vtx = [vtx[k] + s16(p[0] >> s, 10) for k, s in enumerate((0, 10, 20))]
            x, y, z = (q16(c) for c in fn(tuple(v / 4096.0 for v in vtx)))
            out.append((0x23, [(x & 0xffff) | (y & 0xffff) << 16, z & 0xffff]))
        elif op == 0x1b:
            raise ValueError('move_vertices_dl: scaled vertex lists are not handled')
        else:
            out.append((op, p))
    return gx_pack(out)


def move_vertices(ir, fn, materials=None):
    m = ir['models'][0]
    for dr in run_sbc(m)['draws']:
        if materials is not None and m['materials'][dr['mat']]['name'] not in materials:
            continue
        shp = m['shapes'][dr['shape']]
        shp['dl'] = move_vertices_dl(shp['dl'], fn)
    return ir


def prim_cmds(ptype, verts, scale=1.0):
    cmds = [(0x40, [ptype])]
    for v in verts:
        if v.get('nrm') is not None:
            cmds.append((0x21, [sum((norm10(c) & 0x3ff) << (10 * k) for k, c in enumerate(v['nrm']))]))
        if v.get('col') is not None:
            cmds.append((0x20, [pack_col(v['col'])]))
        if v.get('uv') is not None:
            s_, t_ = v['uv']
            cmds.append((0x22, [(int(round(s_ * 16)) & 0xffff) | (int(round(t_ * 16)) & 0xffff) << 16]))
        x, y, z = (q16(c / scale) for c in v['pos'])
        cmds.append((0x23, [(x & 0xffff) | (y & 0xffff) << 16, z & 0xffff]))
    cmds.append((0x41, []))
    return cmds


def append_prims(shape, prims, scale=1.0):
    cmds = [c for c in gx_cmds(shape['dl']) if c[0] != 0x00]
    for ptype, verts in prims:
        cmds += prim_cmds(ptype, verts, scale)
    shape['dl'] = gx_pack(cmds)


def set_prims(shape, prims, scale=1.0):
    cmds = []
    for ptype, verts in prims:
        cmds += prim_cmds(ptype, verts, scale)
    shape['dl'] = gx_pack(cmds) if cmds else bytes(4)


def q16(v):
    return max(-32768, min(32767, int(round(v * 4096))))


def norm10(v):
    return max(-512, min(511, int(round(v * 512))))


def base_name(name):
    return name.split('.')[0] if '.' in name and name.rsplit('.', 1)[1].isdigit() else name


def encode_gltf(path, base_ir, rename=None, quads=False):
    import copy
    ir = copy.deepcopy(base_ir)
    m = ir['models'][0]
    gl = Gltf(path)
    g = gl.g
    scene = run_sbc(m)
    world = scene['world']
    names = [nd['name'] for nd in m['nodes']]
    node_idx = {n: i for i, n in enumerate(names)}
    slot_of = {}
    for s, n in scene['slot_node'].items():
        slot_of.setdefault(n, s)
    parents = scene['parent']
    shape_idx = {s['name']: i for i, s in enumerate(m['shapes'])}
    draw_of = {d['shape']: d for d in scene['draws']}
    mat_idx = {x['name']: i for i, x in enumerate(m['materials'])}
    warnings = []
    for si, sk in enumerate(g.get('skins', [])):
        ibm = gl.acc(sk['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1) if 'inverseBindMatrices' in sk else None
        for k, j in enumerate(sk['joints']):
            nm = base_name(g['nodes'][j].get('name', ''))
            if nm in node_idx and ibm is not None:
                dev = np.abs(np.linalg.pinv(ibm[k])[:3, 3] - world[node_idx[nm]][:3, 3]).max()
                if dev > 0.01:
                    warnings.append(f'joint {nm} rest position moved by {dev:.3f}; the stock skeleton and motions are kept')
    per_shape = {i: [] for i in range(len(m['shapes']))}
    images = {}
    for gn in g['nodes']:
        if 'mesh' not in gn:
            continue
        mesh = g['meshes'][gn['mesh']]
        sname = base_name(mesh.get('name', gn.get('name', '')))
        if sname not in shape_idx:
            sname = base_name(gn.get('name', ''))
        if sname not in shape_idx:
            raise ValueError(f"mesh {mesh.get('name')!r} matches no shape of the base model {sorted(shape_idx)}")
        si = shape_idx[sname]
        joints_map = None
        if 'skin' in gn:
            joints_map = [node_idx.get(base_name(g['nodes'][j].get('name', ''))) for j in g['skins'][gn['skin']]['joints']]
        for prim in mesh['primitives']:
            tris, pos, nrm, uv, col, jo, we = gl_triangles(gl, prim)
            gm = g['materials'][prim['material']] if 'material' in prim else None
            if gm is not None and base_name(gm.get('name', '')) in mat_idx:
                mi = mat_idx[base_name(gm['name'])]
                tex = gm.get('pbrMetallicRoughness', {}).get('baseColorTexture')
                if tex is not None:
                    images[mi] = tex['index']
            if pos.shape[0] and jo is None and 'skin' not in gn:
                nodemtx = gltf_world(g, gn)
                pos = (nodemtx @ np.c_[pos, np.ones(len(pos))].T).T[:, :3]
            per_shape[si].append((tris, pos, nrm, uv, col, jo, we, joints_map))
    tex_by_name = {t['name']: k for k, t in enumerate(ir['tex']['textures'])} if ir['tex'] else {}
    pal_by_name = {p['name']: k for k, p in enumerate(ir['tex']['palettes'])} if ir['tex'] else {}
    for mi, ti in images.items():
        tn, pn = mat_texture(m, mi)
        if tn not in tex_by_name:
            continue
        img = np.array(gl.image(ti).convert('RGBA'))
        old = ir['tex']['textures'][tex_by_name[tn]]
        nt, pal = encode_texture(img, old)
        ir['tex']['textures'][tex_by_name[tn]] = nt
        if pn in pal_by_name:
            ir['tex']['palettes'][pal_by_name[pn]]['data'] = pal
        w, h = tex_dims(nt['param'])
        for k in range(len(m['materials'])):
            if mat_texture(m, k)[0] == tn:
                raw = bytearray(m['materials'][k]['raw'])
                struct.pack_into('<HH', raw, 0x20, w, h)
                m['materials'][k]['raw'] = bytes(raw)
    for si, shp in enumerate(m['shapes']):
        if si not in draw_of:
            continue
        dr = draw_of[si]
        if abs(np.linalg.det(world[dr['node']][:3, :3])) < 1e-9:
            warnings.append(f"{shp['name']}: its node has scale 0 in the rest pose; the stock display list is kept")
            continue
        flag = shp['flag']
        use_nrm, use_col, use_uv, use_restore = flag & 1, flag & 2, flag & 4, flag & 8
        f = mat_fields(m['materials'][dr['mat']]['raw'])
        tw, th = f['w'], f['h']
        vlist = []
        for tris, pos, nrm, uv, col, jo, we, jmap in per_shape[si]:
            if use_uv and uv is None:
                raise ValueError(f"{shp['name']}: needs UVs (TEXCOORD_0)")
            for tri in tris:
                tv = []
                for vi in tri:
                    node = dr['node']
                    if use_restore and jo is not None and jmap is not None:
                        j = jmap[int(jo[vi][int(np.argmax(we[vi]))])]
                        if j is None:
                            raise ValueError(f"{shp['name']}: a vertex is weighted to a joint the base skeleton lacks")
                        while j not in slot_of:
                            j = parents[j]
                        node = j
                    inv = np.linalg.inv(world[node])
                    lp = inv @ np.array([*pos[vi], 1.0])
                    v = {'node': node, 'local': lp[:3]}
                    if use_uv:
                        s_, t_ = uv[vi][0] * tw, uv[vi][1] * th
                        v['uvq'] = (int(round(s_ * 16)) & 0xffff) | (int(round(t_ * 16)) & 0xffff) << 16
                    if use_nrm:
                        nv = nrm[vi] if nrm is not None else face_normal(pos, tri)
                        ln = world[node][:3, :3].T @ nv
                        ln = ln / (np.linalg.norm(ln) or 1)
                        v['n'] = ln
                    if use_col:
                        c = col[vi] if col is not None else (1, 1, 1)
                        v['cq'] = sum(min(31, int(round(c[k] * 31))) << (5 * k) for k in range(3))
                    tv.append(v)
                vlist.append(tv)
        if not vlist:
            continue
        if use_nrm:
            weld_normals(vlist)
        reach = max(np.abs(v['local']).max() for tri in vlist for v in tri)
        scale = 1
        while reach / scale >= 32767 / 4096:
            scale *= 2
        for tri in vlist:
            for v in tri:
                v['raw'] = tuple(q16(c / scale) for c in v['local'])
        shp['dl'] = emit_shape(vlist, use_restore, use_nrm, use_uv, use_col, slot_of, world, quads, scale)
    update_info(m)
    if rename:
        apply_rename(ir, m['name'], rename)
    return ir, warnings


def weld_normals(vlist, min_dot=math.cos(math.radians(50))):
    groups = {}
    for tri in vlist:
        for v in tri:
            groups.setdefault((v['node'], tuple(int(round(c * 4096)) for c in v['local'])), []).append(v)
    for vs in groups.values():
        for v in vs:
            acc = np.sum([w['n'] for w in vs if np.dot(w['n'], v['n']) >= min_dot] or [v['n']], 0)
            ln = np.linalg.norm(acc)
            v['nq_vec'] = acc / ln if ln else np.array([0.0, 1.0, 0.0])
        for v in vs:
            v['nq'] = sum((norm10(c) & 0x3ff) << (10 * k) for k, c in enumerate(v['nq_vec']))


def face_normal(pos, tri):
    a, b, c = (np.array(pos[i]) for i in tri)
    n = np.cross(b - a, c - a)
    return n / (np.linalg.norm(n) or 1)


def gltf_world(g, target):
    parent = {}
    for i, n in enumerate(g['nodes']):
        for c in n.get('children', []):
            parent[c] = i
    idx = g['nodes'].index(target)
    mtx = np.eye(4)
    while idx is not None:
        n = g['nodes'][idx]
        if 'matrix' in n:
            local = np.array(n['matrix']).reshape(4, 4).T
        else:
            x, y, z, w = n.get('rotation', [0, 0, 0, 1])
            r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                          [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                          [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
            local = np.eye(4)
            local[:3, :3] = r * np.array(n.get('scale', [1, 1, 1]))
            local[:3, 3] = n.get('translation', [0, 0, 0])
        mtx = local @ mtx
        idx = parent.get(idx)
    return mtx


def fog_model(path):
    ir = parse_bmd(load_model(path))
    for mt in ir['models'][0]['materials']:
        if struct.unpack_from('<I', mt['raw'], 20)[0]:
            raw = bytearray(mt['raw'])
            struct.pack_into('<I', raw, 12, struct.unpack_from('<I', raw, 12)[0] | 1 << 15)
            mt['raw'] = bytes(raw)
    with open(path, 'wb') as f:
        f.write(lz11_compress(build_bmd(ir)))


def update_info(m):
    info = list(struct.unpack('<BBBBBBBBIIHHHH6hII', m['info']))
    nv = tri = quad = 0
    for s in m['shapes']:
        for p in decode_dl(s['dl']):
            nv += len(p['verts'])
            k = len(triangles(p))
            if p['type'] in (0, 2):
                tri += k
            else:
                quad += k // 2
    pts = np.array([v['pos'] for me in model_mesh(m) for t in me['tris'] for v in t])
    lo, hi = pts.min(0), pts.max(0)
    scale = info[20] / 4096.0 or 1.0
    while max(np.abs(lo).max(), (hi - lo).max()) / scale >= 7.99:
        scale *= 2
    info[10:14] = [nv, tri + quad, tri, quad]
    info[14:20] = [q16(v / scale) for v in (*lo, *(hi - lo))]
    info[20], info[21] = int(scale * 4096), int(4096 / scale)
    m['info'] = struct.pack('<BBBBBBBBIIHHHH6hII', *info)


def apply_rename(ir, old, new):
    def rn(s):
        return s.replace(old, new) if old in s else s
    for m in ir['models']:
        m['name'] = rn(m['name'])
        for x in m['nodes'] + m['materials'] + m['shapes'] + m['tex_bind'] + m['pal_bind']:
            x['name'] = rn(x['name'])
    if ir['tex']:
        for x in ir['tex']['textures'] + ir['tex']['palettes']:
            x['name'] = rn(x['name'])
    for x in [n['name'] for m in ir['models'] for n in m['nodes']]:
        if len(x) > 16:
            raise ValueError(f'name {x!r} is longer than 16 characters')


def open_rom(path):
    import ndspy.rom
    return ndspy.rom.NintendoDSRom.fromFile(path)


def pac_files(rom, pac_path):
    return pac.files(rom.getFileByName(pac_path))


def load_model(src, rom=None, pac_path=DEFAULT_PAC, ext='lznsbmd'):
    if os.path.exists(src):
        data = open(src, 'rb').read()
    else:
        files = pac_files(rom, pac_path)
        key = src if src in files else f'{src}.{ext}'
        if key not in files:
            raise SystemExit(f'{src}: not a file and not in {pac_path}')
        data = files[key]
    return lz11_decompress(data) if data[0] in (0x10, 0x11) else data


def stats(ir):
    m = ir['models'][0]
    nv = tri = quad = 0
    for s in m['shapes']:
        for p in decode_dl(s['dl']):
            nv += len(p['verts'])
            k = len(triangles(p))
            if p['type'] in (0, 2):
                tri += k
            else:
                quad += k // 2
    tex = ir['tex'] or {'textures': [], 'palettes': []}
    tbytes = sum(len(t['data']) + len(t.get('idx', b'')) for t in tex['textures'])
    pbytes = sum(len(p['data']) for p in tex['palettes'])
    return {'nodes': len(m['nodes']), 'shapes': len(m['shapes']), 'materials': len(m['materials']),
            'vertices': nv, 'polygons': tri + quad, 'triangles': tri, 'quads': quad,
            'texel_bytes': tbytes, 'palette_bytes': pbytes, 'dl_bytes': sum(len(s['dl']) for s in m['shapes']),
            'textures': [f"{t['name']} {tex_dims(t['param'])[0]}x{tex_dims(t['param'])[1]} "
                         f"{FORMAT_NAMES[(t['param'] >> 26) & 7]}" for t in tex['textures']]}


def tri_array(tris):
    out = []
    tris = [t for t in tris if len({tuple(np.round(v['pos'], 5)) for v in t}) == 3]
    for t in tris:
        rows = [list(v['pos']) + list(v['uv'] or (0, 0)) for v in t]
        out.append([rows[k:] + rows[:k] for k in range(3)])
    return np.array(out, float).reshape(len(tris), 3, 15) if tris else np.zeros((0, 3, 15))


def same_triangles(ta, tb, pos_tol=4 / 4096, uv_tol=0.07):
    a, b = tri_array(ta), tri_array(tb)
    if len(a) != len(b):
        return False
    scale = np.array(([1 / pos_tol] * 3 + [1 / uv_tol] * 2) * 3)
    a0 = a[:, 0] * scale
    used = np.zeros(len(b), bool)
    for row in a0:
        d = np.abs(b * scale - row).max(2).min(1)
        d[used] = np.inf
        k = int(np.argmin(d))
        if d[k] > 1:
            return False
        used[k] = True
    return True


def compare(a, b):
    ma, mb = a['models'][0], b['models'][0]
    out = []
    out.append(('node tree and rest pose', [n['raw'] for n in ma['nodes']] == [n['raw'] for n in mb['nodes']] and
                [n['name'] for n in ma['nodes']] == [n['name'] for n in mb['nodes']]))
    out.append(('render commands (SBC)', ma['sbc'] == mb['sbc']))
    out.append(('materials', [x['raw'] for x in ma['materials']] == [x['raw'] for x in mb['materials']]))
    ea, eb = model_mesh(ma), model_mesh(mb)
    same = len(ea) == len(eb) and all(same_triangles(x['tris'], y['tris']) for x, y in zip(ea, eb))
    out.append(('triangles (position within 4/4096, texel within 1/16)', same))
    ia, ib = texture_images(a), texture_images(b)
    out.append(('texture pixels (transparent texels: alpha only)', len(ia) == len(ib) and all(
        x.shape == y.shape and (x[..., 3] == y[..., 3]).all() and (x[x[..., 3] > 0] == y[y[..., 3] > 0]).all()
        for x, y in zip(ia, ib))))
    return out


def texture_images(ir):
    if not ir['tex']:
        return []
    m = ir['models'][0]
    texs = {t['name']: t for t in ir['tex']['textures']}
    pals = {p['name']: p['data'] for p in ir['tex']['palettes']}
    out = []
    for mi in range(len(m['materials'])):
        tn, pn = mat_texture(m, mi)
        if tn in texs:
            out.append(decode_texture(texs[tn], pals.get(pn, b'')))
    return out


def anim_files(files, spec):
    out = []
    for item in spec.split(','):
        item = item.strip()
        if len(item) == 1:
            import re
            out += sorted(k for k in files if re.fullmatch(f'm{item}\\d\\d[ab]?\\.lznsbca', k))
        else:
            out.append(item if item.endswith('.lznsbca') else item + '.lznsbca')
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--rom', default=DEFAULT_ROM, help='your WC2011 ROM (default: %(default)s)')
    ap.add_argument('--pac', default=DEFAULT_PAC, help='archive inside the ROM (default: %(default)s)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('list', help='models and animations in the archive')
    p.add_argument('--match', default='')
    p = sub.add_parser('info', help='counts of a model: nodes, polygons, vertices, texture bytes')
    p.add_argument('model', nargs='+', help='name in the archive (npc206) or a .nsbmd/.lznsbmd file')
    p = sub.add_parser('decode', help='model (+ animations) to glTF for Blender')
    p.add_argument('model')
    p.add_argument('--anims', default='', help='animation files, or one letter for a motion set: c = mc01, mc02, ...')
    p.add_argument('--out', help='output folder (default build/nsbmd/<model>)')
    p = sub.add_parser('encode', help='glTF (Blender export) to .lznsbmd, keeping the base skeleton and materials')
    p.add_argument('gltf')
    p.add_argument('--base', required=True, help='stock model whose skeleton, render commands and materials are kept')
    p.add_argument('--out', required=True)
    p.add_argument('--rename', help='replace the base name in every resource name (npc206 -> npc251)')
    p.add_argument('--quads', action='store_true', help='send planar triangle pairs as quad strips (fewer polygons)')
    p = sub.add_parser('verify', help='round-trip checks against the stock files')
    p.add_argument('model', nargs='*', default=['npc206'])
    p.add_argument('--all', action='store_true', help='glTF round trip of every model in the archive (a few minutes)')
    p = sub.add_parser('inject', help='copy the ROM with archive files replaced')
    p.add_argument('pairs', nargs='+', help='NAME=FILE, e.g. npc206=build/kaiba3d/npc_kaiba.lznsbmd')
    p.add_argument('--out', required=True)
    a = ap.parse_args()
    rom = open_rom(a.rom)
    if a.cmd == 'list':
        for k in sorted(pac_files(rom, a.pac)):
            if a.match in k:
                print(k)
    elif a.cmd == 'info':
        for src in a.model:
            print(src, json.dumps(stats(parse_bmd(load_model(src, rom, a.pac))), indent=1))
    elif a.cmd == 'decode':
        ir = parse_bmd(load_model(a.model, rom, a.pac))
        files = pac_files(rom, a.pac)
        anims = []
        for f in anim_files(files, a.anims) if a.anims else []:
            for an in parse_bca(lz11_decompress(files[f])):
                if len(an['nodes']) != len(ir['models'][0]['nodes']):
                    print(f'skip {f}: {len(an["nodes"])} nodes, model has {len(ir["models"][0]["nodes"])}')
                    continue
                an['name'] = f.split('.')[0]
                anims.append(an)
        name = os.path.splitext(os.path.basename(a.model))[0]
        out = a.out or os.path.join('build', 'nsbmd', name)
        path = os.path.join(out, f'{name}.gltf')
        export_gltf(ir, path, anims)
        print('wrote', path, f'({len(anims)} animations)')
    elif a.cmd == 'encode':
        base = parse_bmd(load_model(a.base, rom, a.pac))
        ir, warns = encode_gltf(a.gltf, base, a.rename, a.quads)
        for w in warns:
            print('warning:', w)
        data = build_bmd(ir)
        os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
        open(a.out, 'wb').write(lz11_compress(data) if a.out.endswith('.lznsbmd') else data)
        s, b = stats(ir), stats(base)
        for k in ('polygons', 'vertices', 'nodes', 'texel_bytes', 'palette_bytes', 'dl_bytes'):
            print(f'{k:14s} {s[k]:6d}  (base {b[k]})')
        print('wrote', a.out)
    elif a.cmd == 'verify':
        files = pac_files(rom, a.pac)
        bad = 0
        models = [k for k in files if k.endswith('.lznsbmd')]
        for k in models:
            raw = lz11_decompress(files[k])
            if build_bmd(parse_bmd(raw)) != raw:
                bad += 1
                print('repack differs:', k)
        print(f'byte-identical repack: {len(models) - bad}/{len(models)} models in {a.pac}')
        names = [k[:-len('.lznsbmd')] for k in sorted(models)] if a.all else a.model
        failed = 0
        for name in names:
            ir = parse_bmd(load_model(name, rom, a.pac))
            tmp = os.path.join('build', 'nsbmd', 'verify', name)
            export_gltf(ir, os.path.join(tmp, f'{name}.gltf'))
            ir2, _ = encode_gltf(os.path.join(tmp, f'{name}.gltf'), ir)
            back = parse_bmd(lz11_decompress(lz11_compress(build_bmd(ir2))))
            res = compare(ir, back)
            failed += not all(ok for _, ok in res)
            if not a.all:
                for what, ok in res:
                    print(f'{name}: glTF round trip, {what}: {"same" if ok else "DIFFERENT"}')
                s, b = stats(back), stats(ir)
                print(f"{name}: display lists {s['dl_bytes']} bytes (stock {b['dl_bytes']}), vertices {s['vertices']} "
                      f"({b['vertices']}), polygons {s['polygons']} ({b['polygons']})")
            elif not all(ok for _, ok in res):
                print(name, 'DIFFERENT:', ', '.join(w for w, ok in res if not ok))
        if a.all:
            print(f'glTF round trip: {len(names) - failed}/{len(names)} models the same')
    elif a.cmd == 'inject':
        files = pac_files(rom, a.pac)
        for pair in a.pairs:
            name, f = pair.split('=', 1)
            key = name if name in files else f'{name}.lznsbmd'
            if key not in files:
                raise SystemExit(f'{name}: not in {a.pac}')
            data = open(f, 'rb').read()
            files[key] = data if data[0] == 0x11 else lz11_compress(data)
        rom.setFileByName(a.pac, pac.build(files))
        os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
        rom.saveToFile(a.out)
        print('wrote', a.out)


if __name__ == '__main__':
    main()
