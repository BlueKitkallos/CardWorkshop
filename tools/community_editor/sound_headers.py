"""WC2011 sound header reader/writer, shared layout from build_music11.Hed."""
import struct
import sys
HED_MAGIC = 0x230
TEMPLATE_ID = 5

class Hed:
    def __init__(self, data):
        magic, size, self.se_first, self.se_count, bank_off, bank_len = struct.unpack_from('<IIhhII', data, 0)
        if magic != HED_MAGIC or size & 0x3fffffff != len(data) - 0x1c or bank_off != 8 or bank_len % 2:
            sys.exit('ds_data_hed.sdat: not the WC2011 layout')
        self.head = bytearray(data[:0x1c])
        self.pre = bytes(data[0x1c:0x24])
        self.bank_need = list(struct.unpack_from(f'<{bank_len // 2}H', data, 0x24))
        p = 0x24 + bank_len
        word = struct.unpack_from('<I', data, p)[0]
        self.word_hi = word >> 16
        n = (word & 0xffff) // 3
        self.ids = [(struct.unpack_from('<H', data, p + 4 + 3 * i)[0], data[p + 6 + 3 * i]) for i in range(n)]
        rec = p + 4 + (word & 0xffff)
        count = max(r for r, _ in self.ids) + 1
        self.records = [bytearray(data[rec + 10 * i:rec + 10 * i + 10]) for i in range(count)]
        if any(data[rec + 10 * count:]):
            sys.exit('ds_data_hed.sdat: data after the sound records')

    def record(self, sound_id):
        return self.records[self.ids[sound_id][0]]

    def slot(self, sound_id):
        return struct.unpack_from('<H', self.record(sound_id), 4)[0] & 0xfff

    def bank(self, sound_id):
        return self.ids[sound_id][1] | self.record(sound_id)[3] << 8

    def add_sequence(self, slot, bank):
        rec = bytearray(self.record(TEMPLATE_ID))
        rec[3] = bank >> 8
        struct.pack_into('<H', rec, 4, struct.unpack_from('<H', rec, 4)[0] & 0xf000 | slot)
        self.records.append(rec)
        self.ids.append((len(self.records) - 1, bank & 0xff))
        return len(self.ids) - 1

    def save(self):
        body = bytearray(self.pre)
        body += struct.pack(f'<{len(self.bank_need)}H', *self.bank_need)
        table = b''.join(struct.pack('<HB', r, low) for r, low in self.ids)
        table += bytes(len(table) % 2)
        body += struct.pack('<I', self.word_hi << 16 | len(table)) + table
        for r in self.records:
            body += r
        body += bytes(-len(body) % 4)
        head = bytearray(self.head)
        struct.pack_into('<I', head, 4, struct.unpack_from('<I', head, 4)[0] & 0xc0000000 | len(body))
        struct.pack_into('<I', head, 0x10, 2 * len(self.bank_need))
        return bytes(head + body)


FILE_TYPES = (0, 1, 2, 3, 7)


def info_records(d):
    info = struct.unpack_from('<I', d, 0x18)[0]
    recs = {}
    for t in FILE_TYPES:
        off = struct.unpack_from('<I', d, info + 8 + 4 * t)[0]
        n = struct.unpack_from('<I', d, info + off)[0]
        for i in range(n):
            ro = struct.unpack_from('<I', d, info + off + 4 + 4 * i)[0]
            if ro:
                recs[t, i] = info + ro
    return recs


def keep_file_ids(orig, new):
    old_recs, new_recs = info_records(orig), info_records(new)
    fat = struct.unpack_from('<I', new, 0x20)[0]
    count = struct.unpack_from('<I', new, fat + 8)[0]
    old_count = struct.unpack_from('<I', orig, struct.unpack_from('<I', orig, 0x20)[0] + 8)[0]
    remap = {}
    next_id = old_count
    for key in sorted(new_recs):
        nid = struct.unpack_from('<H', new, new_recs[key])[0]
        if key in old_recs:
            want = struct.unpack_from('<H', orig, old_recs[key])[0]
        elif nid in remap:
            want = remap[nid]
        else:
            want = next_id
            next_id += 1
        if remap.setdefault(nid, want) != want:
            sys.exit(f'file id conflict at {key}')
    if sorted(remap.values()) != list(range(count)):
        sys.exit('file ids are not a permutation')
    out = bytearray(new)
    entries = [new[fat + 12 + 16 * i:fat + 28 + 16 * i] for i in range(count)]
    for nid, want in remap.items():
        out[fat + 12 + 16 * want:fat + 28 + 16 * want] = entries[nid]
    for key, off in new_recs.items():
        struct.pack_into('<H', out, off, remap[struct.unpack_from('<H', new, off)[0]])
    return bytes(out)

