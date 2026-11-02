"""Import only WC2010 pack cues into fresh WC2011 audio in memory."""
import copy
import hashlib
import struct
import ndspy.soundArchive as SA
import ndspy.soundBank as SB
import ndspy.soundSequence as S
import ndspy.soundSequenceArchive as SS
import ndspy.soundWaveArchive as SW
from sound_headers import Hed, keep_file_ids

CUES = [('FLIP','CARD_OPEN'), ('RARE','SHINE2'), ('SUPER','FUSION2'), ('ULTRA','LEVELUP')]


def note_defs(instrument):
    if isinstance(instrument, SB.SingleNoteInstrument):
        return [instrument.noteDefinition]
    if isinstance(instrument, SB.RangeInstrument):
        return instrument.noteDefinitions
    if isinstance(instrument, SB.RegionalInstrument):
        return [r.noteDefinition for r in instrument.regions]
    return []


def fat_files(raw):
    fat = struct.unpack_from('<I', raw, 0x20)[0]
    n = struct.unpack_from('<I', raw, fat + 8)[0]
    return [raw[o:o+s] for o,s in (struct.unpack_from('<II',raw,fat+12+i*16) for i in range(n))]


def build(donor, target):
    source = SA.SDAT(donor.getFileByName('sound/sound_data.sdat'))
    original = bytes(target.getFileByName('sound/sound_data.sdat'))
    out = SA.SDAT(original)
    hed = Hed(target.getFileByName('sound/ds_data_hed.sdat'))
    if hed.se_first + hed.se_count != len(hed.ids):
        raise ValueError('Unexpected base game audio layout.')
    arc = source.sequenceArchives[0][1]
    arc.parse()
    wave_archive = SW.SWAR()
    new_wave_id = len(out.waveArchives)
    sound_ids, imported = {}, []
    old_ids, old_records = list(hed.ids), [bytes(r) for r in hed.records]
    for cue, name in CUES:
        q = next(q for n,q in arc.sequences if n == name)
        first = arc.events.index(q.firstEvent)
        events = []
        for event in arc.events[first:]:
            events.append(copy.deepcopy(event))
            if isinstance(event, S.EndTrackSequenceEvent):
                break
        if len(events) != 3 or not isinstance(events[1], S.NoteSequenceEvent):
            raise ValueError(f'Unexpected WC2010 cue: {name}')
        if cue == 'FLIP':
            events.insert(1, S.TrackPrioritySequenceEvent(127))
        bank = copy.deepcopy(source.banks[q.bankID][1])
        mapping, hashes = {}, []
        for instrument in bank.instruments:
            for definition in note_defs(instrument):
                if int(definition.type) != 1:
                    raise ValueError('Pack cue needs a sampled instrument.')
                key = definition.waveArchiveIDID, definition.waveID
                if key not in mapping:
                    wave = source.waveArchives[bank.waveArchiveIDs[key[0]]][1].waves[key[1]]
                    mapping[key] = len(wave_archive.waves)
                    wave_archive.waves.append(copy.deepcopy(wave))
                    hashes.append(hashlib.sha256(wave.save()).hexdigest())
                definition.waveID = mapping[key]
        bank.waveArchiveIDs = [new_wave_id if n is not None else None for n in bank.waveArchiveIDs]
        bank_id = len(out.banks)
        out.banks.append(('BANK_COMMUNITY_PACK_'+cue, bank))
        new_arc = SS.SSAR()
        new_arc.events = events
        new_arc.sequences = [(name, SS.SSARSequence(events[0],bank_id,q.volume,q.channelPressure,q.polyphonicPressure,q.playerID))]
        archive_id = len(out.sequenceArchives)
        out.sequenceArchives.append(('SEQARC_COMMUNITY_PACK_'+cue,new_arc))
        record = bytearray(hed.record(0x1aa))
        record[3] = bank_id >> 8
        struct.pack_into('<H',record,4,archive_id)
        struct.pack_into('<H',record,6,0)
        if cue == 'FLIP':
            record[0] = 0x60
        sound_ids[cue] = len(hed.ids)
        hed.ids.append((len(hed.records),bank_id & 255))
        hed.records.append(record)
        hed.se_count += 1
        wave_bytes = sum(((len(wave_archive.waves[i].data)+43)//32*32)+64 for i in set(mapping.values()))
        hed.bank_need.append((len(bank.save()[0])+wave_bytes+4096+31)//32)
        imported.append({'cue':cue,'source_name':name,'wave_sha256':hashes,'bank':bank_id,
                         'archive':archive_id,'wave_indices':sorted(set(mapping.values()))})
    flip = imported[0]
    record = bytes(hed.record(sound_ids['FLIP']))
    for number in range(1,5):
        alias = copy.deepcopy(out.sequenceArchives[flip['archive']][1])
        for _ in range(number):
            alias.events.insert(-1,S.RestSequenceEvent(0))
        aid = len(out.sequenceArchives)
        out.sequenceArchives.append((f'SEQARC_COMMUNITY_PACK_FLIP{number}',alias))
        rec = bytearray(record)
        struct.pack_into('<H',rec,4,aid)
        sound_ids[f'FLIP{number}'] = len(hed.ids)
        hed.ids.append((len(hed.records),flip['bank'] & 255))
        hed.records.append(rec)
        hed.se_count += 1
    out.waveArchives.append(('WAVE_COMMUNITY_PACK',wave_archive))
    compiled = keep_file_ids(original,out.save())
    old_files, new_files = fat_files(original), fat_files(compiled)
    if new_files[:len(old_files)] != old_files or len(new_files)-len(old_files) != 13:
        raise ValueError('Opening import changed unrelated audio.')
    if hed.ids[:len(old_ids)] != old_ids or [bytes(r) for r in hed.records[:len(old_records)]] != old_records:
        raise ValueError('Opening import changed existing sound IDs.')
    rebuilt = SA.SDAT(compiled)
    for entry in imported:
        hashes = [hashlib.sha256(rebuilt.waveArchives[new_wave_id][1].waves[i].save()).hexdigest()
                  for i in entry['wave_indices']]
        if hashes != entry['wave_sha256']:
            raise ValueError('WC2010 cue verification failed.')
    header = bytearray(hed.save())
    struct.pack_into('<h',header,0xa,hed.se_count)
    macros = '\n'.join(f'#define W11_PACK_{cue} {sid}u' for cue,sid in sound_ids.items())+'\n'
    return {'sound/sound_data.sdat':compiled,'sound/ds_data_hed.sdat':bytes(header)}, macros, imported
