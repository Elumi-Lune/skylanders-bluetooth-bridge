import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

"""V4.3 non-hardware regression tests: dry-run, immutable backups, failures."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import queue
import json
import tempfile

import skylanders_sync_guard as safe
import skylanders_virtport_live as live
from skylanders_trap_decoder import crc16


def fake_image(uid=b'\x01\x02\x03\x04', game_byte=7, fid=470, var=12288):
    raw = bytearray(1024)
    raw[:4] = uid
    raw[16:18] = fid.to_bytes(2, 'little')
    raw[28:30] = var.to_bytes(2, 'little')
    raw[30:32] = crc16(raw[:30]).to_bytes(2, 'little')
    raw[100] = game_byte
    return bytes(raw)


class FakeServer:
    def __init__(self, image):
        self.image = image
        self.fail = False
        self.clears = []
        self.uploads = []
    def download(self, slot):
        if self.fail:
            raise ConnectionError('Serveur Cemu indisponible')
        return self.image
    def clear(self, slot):
        self.clears.append(slot)
    def claim(self, slot):
        return None
    def upload(self, slot, image):
        self.uploads.append(image)
    def summon(self, slot):
        return None


def test_safe():
    with TemporaryDirectory() as td:
        base = Path(td)
        with patch.object(safe, 'SAFE_DIR', base/'safe'), \
             patch.object(safe, 'ORIGINAL_DIR', base/'safe'/'orig'), \
             patch.object(safe, 'PLAN_DIR', base/'safe'/'plan'), \
             patch.object(safe, 'STATE_PATH', base/'safe'/'idx.json'):
            src = fake_image()
            updated = fake_image(game_byte=8)
            fingerprint = hashlib.sha256(src[16:32]).hexdigest()
            original_path = safe.register_reference(fingerprint, src, provenance='lecture-directe-BLE')
            assert original_path.read_bytes() == src
            try:
                safe.register_reference(fingerprint, fake_image(uid=b'ZZZZ'), provenance='other')
                raise AssertionError('Collision UID non rejetée')
            except safe.SafetyError:
                pass
            virtual = base/'edited.sky'
            virtual.write_bytes(updated)
            safe.register_virtual(fingerprint, updated, virtual)
            plans = safe.prepare_reports()
            report = json.loads(plans[0].read_text(encoding='utf-8'))
            assert report['result']['changed_blocks'] == [6]
            assert report['result']['writing_is_implemented'] is False
            assert original_path.read_bytes() == src
            # A sector trailer is prohibited even in an offline writing proposal.
            altered = bytearray(updated); altered[48] = 1
            assert safe.compare(src, bytes(altered))['potentially_editable'] is False
            bad = bytearray(updated); bad[0] = 15
            try:
                safe.compare(src, bytes(bad))
                raise AssertionError('CRC mismatch was not rejected')
            except safe.SafetyError:
                pass

            with patch.object(live, 'GAME_DIR', base/'game'), \
                 patch.object(live, 'CACHE_DIR', base/'cache'), \
                 patch.object(live, 'INDEX', base/'cache'/'index.json'):
                server = FakeServer(updated)
                proc = object.__new__(live.NetworkQueue)
                proc.server = server
                proc.output = queue.Queue()
                proc.cache = {}
                proc.live = {}
                proc.pending_removals = {}
                proc.last_snapshot = 0
                source_file = base/'physical.sky'
                source_file.write_bytes(src)
                proc.process('ready', {'slot':0, 'fingerprint':fingerprint,
                                       'path':str(source_file), 'cached':False})
                assert 0 in proc.live
                # Server failure MUST NOT clear slot or lose a pending save.
                server.fail = True
                proc.process('remove', {'slot':0})
                assert 0 in proc.live and not server.clears and 0 in proc.pending_removals
                # Once server returns, the saved image is preserved, not discarded.
                server.fail = False
                proc.process('remove', {'slot':0})
                assert 0 not in proc.live and server.clears == [0]
                assert proc.cache[fingerprint]
                assert len(list((base/'game').glob('*.sky'))) == 1
                assert original_path.read_bytes() == src
                # Retrieval of the same figure now uses the latest cached game version.
                current = Path(proc.cache[fingerprint]['path'])
                proc.process('ready', {'slot':0, 'fingerprint':fingerprint,
                                       'path':str(current), 'cached':True})
                assert server.uploads[-1] == updated
                proc.process('snapshot', {})
                assert len(list((base/'game').glob('*.sky'))) == 1
                proc.process('remove', {'slot':0})
                assert server.clears == [0, 0]

if __name__ == '__main__':
    test_safe()
    live.self_test()
    print('OK : V4.3 SafeSync, restauration virtuelle, refus retrait sans sauvegarde, rapports NFC sans écriture.')
