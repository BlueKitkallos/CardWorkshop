"""WC2011 sound header (ds_data_hed.sdat) and the sound effect room fix shared by the music build and the QoL patch."""
import copy
import struct
import sys

import ndspy.soundArchive as SA
import ndspy.soundBank as B

HED_MAGIC = 0x230
TEMPLATE_ID = 5
NO_STREAM_BUFFER = 0x80000000
SE_ARCHIVE = 1
HED_PATH, SDAT_PATH = 'sound/ds_data_hed.sdat', 'sound/sound_data.sdat'
SOUND_BUFFER, SOUND_BUFFER_SIZE = 0x020bb9c4, 350000
SOUND_HEAP_START = (SOUND_BUFFER + 0xe00 + 31) & ~31
VOW_BYTES = 4
FRAME_HEAP_HEAD, SND_HEAP_GROUP_HEAD, SND_BLOCK_HEAD = 0x40, 0x20, 0x20


def index_size(sdat_data, hed_data):
    up = lambda x, n: (x + n - 1) // n * n
    word = struct.unpack_from('<I', hed_data, 4)[0]
    info_size = struct.unpack_from('<I', sdat_data, 0x1c)[0]
    fat_size = struct.unpack_from('<I', sdat_data, 0x24)[0]
    end = up(up(word & 0x3fffffff, 4) + VOW_BYTES, 32)
    if not word & NO_STREAM_BUFFER:
        end += 0x3000
    return (end + FRAME_HEAP_HEAD + SND_HEAP_GROUP_HEAD + SND_BLOCK_HEAD + up(info_size, 32)
            + SND_BLOCK_HEAD + up(fat_size, 32))


def sound_heap():
    return SOUND_BUFFER + SOUND_BUFFER_SIZE - SOUND_HEAP_START - 0x38


class Hed:
    def __init__(self, data):
        magic, size, self.se_first, self.se_count, bank_off, bank_len = struct.unpack_from('<IIhhII', data, 0)
        if magic != HED_MAGIC or size & 0x3fffffff != len(data) - 0x1c or bank_off < 8 or bank_off % 4:
            sys.exit('ds_data_hed.sdat: not the WC2011 layout')
        if bank_len % 4:
            sys.exit(f'ds_data_hed.sdat: bank table of {bank_len} bytes; the game reads the word after it with an '
                     f'aligned ldr, so it must be a multiple of 4 or the SE index base turns into a bank heap entry')
        self.head = bytearray(data[:0x1c])
        self.pre = bytes(data[0x1c:0x1c + bank_off])
        self.bank_need = list(struct.unpack_from(f'<{bank_len // 2}H', data, 0x1c + bank_off))
        p = 0x1c + bank_off + bank_len
        word = struct.unpack_from('<I', data, p)[0]
        self.word_hi = word >> 16
        if word & 1:
            sys.exit(f'ds_data_hed.sdat: sound id table of {word & 0xffff} bytes; it must be even (records are read '
                     f'with halfword loads)')
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

    def set_bank(self, bank_id, need):
        if len(self.bank_need) < bank_id or any(self.bank_need[bank_id + 1:]):
            sys.exit(f'ds_data_hed.sdat: {len(self.bank_need)} bank heap entries, cannot add bank {bank_id}')
        self.bank_need[bank_id:] = [need]

    def sync_wave_counts(self, sdat):
        # The two records preceding the bank heap table are (FAT id, wave
        # count), not opaque padding. The game sizes its SWAR directory from
        # these counts and rejects a different count in the actual SWAR.
        pre = bytearray(self.pre)
        for i in range(len(pre) // 4):
            count = len(sdat.waveArchives[i][1].waves)
            if count > 0xffff:
                raise ValueError(f'wave archive {i}: too many waves for the WC2011 header')
            struct.pack_into('<H', pre, i * 4 + 2, count)
        self.pre = bytes(pre)

    def add_archive(self, file_id, count):
        self.pre += struct.pack('<HH', file_id, count)

    def validate_wave_counts(self, sdat):
        for i in range(len(self.pre) // 4):
            declared = struct.unpack_from('<H', self.pre, i * 4 + 2)[0]
            actual = len(sdat.waveArchives[i][1].waves)
            if declared != actual:
                raise ValueError(f'wave archive {i}: HED declares {declared} waves, SWAR has {actual}; '
                                 'the game rejects this archive')

    def add_sequence(self, slot, bank):
        rec = bytearray(self.record(TEMPLATE_ID))
        rec[3] = bank >> 8
        struct.pack_into('<H', rec, 4, struct.unpack_from('<H', rec, 4)[0] & 0xf000 | slot)
        self.records.append(rec)
        self.ids.append((len(self.records) - 1, bank & 0xff))
        return len(self.ids) - 1

    def save(self):
        body = bytearray(self.pre)
        need = self.bank_need + [0] * (len(self.bank_need) % 2)
        body += struct.pack(f'<{len(need)}H', *need)
        table = b''.join(struct.pack('<HB', r, low) for r, low in self.ids)
        table += bytes(len(table) % 2)
        body += struct.pack('<I', self.word_hi << 16 | len(table)) + table
        for r in self.records:
            body += r
        body += bytes(-len(body) % 4)
        head = bytearray(self.head)
        struct.pack_into('<I', head, 4, struct.unpack_from('<I', head, 4)[0] & 0x40000000 | NO_STREAM_BUFFER | len(body))
        struct.pack_into('<I', head, 0x0c, len(self.pre))
        struct.pack_into('<I', head, 0x10, 2 * len(need))
        Hed(bytes(head + body))
        return bytes(head + body)


def sbnk_size(bank):
    data = bank.save()
    return len(data[0] if isinstance(data, tuple) else data)


def wave_ids(bank):
    return {n.waveID for ins in bank.instruments if ins for n in note_defs(ins) if int(n.type) == 1}


def note_defs(ins):
    if isinstance(ins, B.SingleNoteInstrument):
        return [ins.noteDefinition]
    if isinstance(ins, B.RangeInstrument):
        return list(ins.noteDefinitions)
    if isinstance(ins, B.RegionalInstrument):
        return [r.noteDefinition for r in ins.regions]
    return []


U8_ARGS = set(range(0xc0, 0xd7))
S16_ARGS = {0xe0, 0xe1, 0xe3}


def varlen(data, pc):
    value = 0
    while True:
        byte = data[pc]
        pc += 1
        value = value << 7 | byte & 0x7f
        if byte < 0x80:
            return value, pc


def sseq_events(seq):
    data = seq.save()
    data = data[0] if isinstance(data, tuple) else data
    return data[struct.unpack_from('<I', data, 0x18)[0]:]


def reached_notes(seq):
    data = sseq_events(seq)
    reached, seen = set(), set()
    todo = [(0, 0, 0, (), ())]
    while todo:
        state = todo.pop()
        if state in seen:
            continue
        seen.add(state)
        pc, prog, transpose, stack, loops = state
        if len(stack) > 16 or len(loops) > 16:
            raise ValueError(f'offset {pc:#x}: calls or loops nested deeper than 16')
        if pc >= len(data):
            raise ValueError(f'offset {pc:#x}: past the end of the sequence')
        cmd = data[pc]
        if cmd < 0x80:
            reached.add((prog, min(max(cmd + transpose, 0), 127)))
            todo.append((varlen(data, pc + 2)[1], prog, transpose, stack, loops))
        elif cmd == 0x80:
            todo.append((varlen(data, pc + 1)[1], prog, transpose, stack, loops))
        elif cmd == 0x81:
            value, nxt = varlen(data, pc + 1)
            todo.append((nxt, value, transpose, stack, loops))
        elif cmd == 0x93:
            todo += [(pc + 5, prog, transpose, stack, loops), (int.from_bytes(data[pc + 2:pc + 5], 'little'), 0, 0, (), ())]
        elif cmd == 0x94:
            todo.append((int.from_bytes(data[pc + 1:pc + 4], 'little'), prog, transpose, stack, loops))
        elif cmd == 0x95:
            todo.append((int.from_bytes(data[pc + 1:pc + 4], 'little'), prog, transpose, stack + (pc + 4,), loops))
        elif 0xb0 <= cmd <= 0xbd:
            todo.append((pc + 4, prog, transpose, stack, loops))
        elif cmd == 0xc3:
            todo.append((pc + 2, prog, data[pc + 1] - 256 if data[pc + 1] >= 128 else data[pc + 1], stack, loops))
        elif cmd == 0xd4:
            todo.append((pc + 2, prog, transpose, stack, loops + (pc + 2,)))
        elif cmd in U8_ARGS:
            todo.append((pc + 2, prog, transpose, stack, loops))
        elif cmd in S16_ARGS or cmd == 0xfe:
            todo.append((pc + 3, prog, transpose, stack, loops))
        elif cmd == 0xfc:
            if loops:
                todo += [(loops[-1], prog, transpose, stack, loops), (pc + 1, prog, transpose, stack, loops[:-1])]
            else:
                todo.append((pc + 1, prog, transpose, stack, loops))
        elif cmd == 0xfd:
            if stack:
                todo.append((stack[-1], prog, transpose, stack[:-1], loops))
        elif cmd != 0xff:
            raise ValueError(f'offset {pc:#x}: command {cmd:#04x} (random, variable or unknown)')
    return reached


def note_index(ins, key):
    if isinstance(ins, B.SingleNoteInstrument):
        return 0
    if isinstance(ins, B.RangeInstrument):
        i = key - ins.firstPitch
        return i if 0 <= i < len(ins.noteDefinitions) else None
    if isinstance(ins, B.RegionalInstrument):
        return next((i for i, r in enumerate(ins.regions) if key <= r.lastPitch), None)
    return None


def trim_bank(bank, reached):
    out = copy.deepcopy(bank)
    used = {}
    for prog, key in reached:
        ins = out.instruments[prog] if prog < len(out.instruments) else None
        i = note_index(ins, key) if ins else None
        if i is not None:
            used.setdefault(prog, set()).add(i)
    for prog, ins in enumerate(out.instruments):
        if prog not in used:
            out.instruments[prog] = None
            continue
        lo, hi = min(used[prog]), max(used[prog])
        keep = note_defs(ins)[lo]
        if isinstance(ins, B.RangeInstrument):
            ins.noteDefinitions = [nd if i in used[prog] else copy.deepcopy(keep)
                                   for i, nd in enumerate(ins.noteDefinitions) if lo <= i <= hi]
            ins.firstPitch += lo
        elif isinstance(ins, B.RegionalInstrument):
            ins.regions = ins.regions[:hi + 1]
            for i, r in enumerate(ins.regions):
                if i not in used[prog]:
                    r.noteDefinition = copy.deepcopy(keep)
    while out.instruments and out.instruments[-1] is None:
        out.instruments.pop()
    return out


def heap_block(size):
    return (size + 0x5f) // 32 * 32 + 32


def se_heap_need(sdat, bank):
    waves = sdat.waveArchives[SE_ARCHIVE][1].waves
    return (32 + heap_block(sbnk_size(bank)) + sum(heap_block(len(waves[i].data) + 0xc) for i in wave_ids(bank)) + 31) // 32


def trim_se_needs(sdat, hed):
    for b, (name, bank) in enumerate(sdat.banks):
        if (name and bank and not name.startswith('BANK_BGM') and b < len(hed.bank_need) and wave_ids(bank)
                and {bank.waveArchiveIDs[n.waveArchiveIDID] for ins in bank.instruments if ins
                     for n in note_defs(ins) if int(n.type) == 1} == {SE_ARCHIVE}):
            hed.bank_need[b] = se_heap_need(sdat, bank)


def check_no_streams(sdat):
    if sdat.streams:
        sys.exit(f'{len(sdat.streams)} streams in sound_data.sdat: the archive is built without the stream buffer '
                 f'(NO_STREAM_BUFFER in ds_data_hed.sdat), so they would not play')


def fix_se_room(rom):
    sdat = SA.SDAT(rom.getFileByName(SDAT_PATH))
    check_no_streams(sdat)
    hed = Hed(rom.getFileByName(HED_PATH))
    trim_se_needs(sdat, hed)
    rom.setFileByName(HED_PATH, hed.save())
