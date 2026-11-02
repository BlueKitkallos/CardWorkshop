"""WC2011 sound header (ds_data_hed.sdat) and the sound effect room fix shared by the music build and the QoL patch."""
import struct
import sys

import ndspy.soundArchive as SA
import ndspy.soundBank as B

HED_MAGIC = 0x230
TEMPLATE_ID = 5
NO_STREAM_BUFFER = 0x80000000
SE_ARCHIVE = 1
HED_PATH, SDAT_PATH = 'sound/ds_data_hed.sdat', 'sound/sound_data.sdat'


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
