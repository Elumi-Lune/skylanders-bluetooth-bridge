#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Skylanders Bluetooth Bridge V3 — import read-only vers Cemu.

Ce module exporte un dump MIFARE Classic 1K COMPLET de 64 x 16 octets
au format .sky utilisable par le portail virtuel Cemu.
La V3 ne branche PAS encore les messages BLE en direct à Cemu et ne
possède aucune commande NFC W (écriture sur la figurine).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import queue
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from skylanders_bridge_v1_2 import worker_entry
from skylanders_bridge_v2 import SkylandersSuite, self_test as v2_self_test
from skylanders_extras import ResearchPortalWorker, TrapDump, TRAP_WAIT_SECONDS, TRAP_STABLE_FRAMES, TRAP_STATUS_STALE_SECONDS
from skylanders_trap_decoder import crc16

ROOT = Path(__file__).resolve().parent
EXPORT_DIR = ROOT / 'cemu_exports'


def identity_from_data(image: bytes) -> tuple[int, int]:
    if len(image) != 1024:
        raise ValueError('Un fichier .sky doit contenir exactement 1024 octets (64 blocs de 16 octets).')
    return int.from_bytes(image[16:18], 'little'), int.from_bytes(image[28:30], 'little')


def verified_image(blocks: dict[int, bytes], expected: tuple[int, int] | None = None) -> bytes:
    """Reject incomplete/mislabelled dumps; never invent missing sectors or zeros."""
    if set(blocks) != set(range(64)):
        missing = sorted(set(range(64)) - set(blocks))
        raise ValueError(f'Export interdit : blocs manquants {missing} (64/64 requis).')
    if any(not isinstance(blocks[i], bytes) or len(blocks[i]) != 16 for i in range(64)):
        raise ValueError('Blocs NFC invalides : 16 octets requis pour chaque bloc.')
    image = b''.join(blocks[i] for i in range(64))
    got = identity_from_data(image)
    if expected is not None and got != tuple(expected):
        raise ValueError(f'Objet différent : identifiant lu {got}, attendu {expected}.')
    crc_stored = int.from_bytes(image[30:32], 'little')
    crc_actual = crc16(image[:30])
    if crc_actual != crc_stored:
        raise ValueError(f'CRC en-tête incorrect ({crc_stored:04x} ≠ {crc_actual:04x}). Export annulé.')
    return image


def load_old_dump(path: Path) -> tuple[bytes, tuple[int, int]]:
    """Convert only a full, verified original V2.x report, not an arbitrary draft."""
    report = json.loads(path.read_text(encoding='utf-8'))
    if report.get('format') != 'skylanders-bridge-trap-readonly-v1':
        raise ValueError('Ce fichier doit être un rapport trap_*.json V2.2/V2.3, pas un brouillon NFC.')
    records = report.get('blocks')
    if not isinstance(records, dict) or set(records) != {str(i) for i in range(64)}:
        raise ValueError('Sauvegarde incomplète : 64 blocs requis.')
    blocks = {i: bytes.fromhex(records[str(i)]) for i in range(64)}
    ident = report.get('identity', {})
    expected = (int(ident['character_id']), int(ident['variant_id']))
    image = verified_image(blocks, expected)
    if report.get('sha256') and report['sha256'].lower() != hashlib.sha256(image).hexdigest():
        raise ValueError('SHA-256 différent du rapport original : export annulé.')
    return image, expected


def safe_name(s: str) -> str:
    s = re.sub(r'[^A-Za-z0-9._ -]+', '_', s.strip())[:60]
    return s.strip(' ._') or 'Skylander'


def save_sky(image: bytes, ident: tuple[int, int], name: str,
             source: str, export_dir: Path | None = None) -> Path:
    export_dir = EXPORT_DIR if export_dir is None else export_dir
    if identity_from_data(image) != ident:
        raise ValueError('Identité incompatible avec le fichier source')
    verified_image({i: image[i*16:(i+1)*16] for i in range(64)}, ident)
    export_dir.mkdir(parents=True, exist_ok=True)
    stem = (f'{safe_name(name)}_ID{ident[0]}_V{ident[1]}_'
            f'{datetime.now().strftime("%Y%m%d_%H%M%S_%f")}')
    target = export_dir / (stem + '.sky')
    # exclusive creation: never overwrite another existing save
    with target.open('xb') as fout:
        fout.write(image)
    metadata = {
        'format': 'skylanders-ble-cemu-export-v3', 'file': target.name,
        'sha256': hashlib.sha256(image).hexdigest(), 'bytes': len(image),
        'character_id': ident[0], 'variant_id': ident[1],
        'source': source, 'read_only_from_physical_tag': True,
        'game_changes_not_written_back_to_physical_tag': True,
        'created_at': datetime.now().isoformat(timespec='seconds'),
    }
    target.with_suffix('.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
    return target


class CemuExportWorker(ResearchPortalWorker):
    """Reuses V2.3 Q packet queue, presence tracking and read-only safeguards."""
    def __init__(self, events, stop, allow_reads, allow_trap_reads,
                 reread_requests, catalogue, dump_requests, cemu_requests):
        super().__init__(events, stop, allow_reads, allow_trap_reads,
                         reread_requests, catalogue, dump_requests)
        self.cemu_requests: queue.Queue = cemu_requests
        self.cemu_waiting: float | None = None
        self.cemu_active = False
        self.cemu_name = 'Skylander'

    def any_slot_stable(self, now: float, slot: int) -> bool:
        obj = self.slots.get(slot)
        return bool(obj and obj.result is not None and obj.missing_since is None
                    and self.slot_present_frames.get(slot, 0) >= TRAP_STABLE_FRAMES
                    and now - self.last_slot_present.get(slot, -1e9) <= TRAP_STATUS_STALE_SECONDS)

    def trap_is_stable(self, now: float, slot: int) -> bool:
        # V2.3 filters trap IDs. When exporting a figure, allow its NFC-verified slot.
        if self.cemu_active:
            return self.any_slot_stable(now, slot)
        return super().trap_is_stable(now, slot)

    def finish_dump(self, reason: str = '') -> None:
        if not self.cemu_active:
            super().finish_dump(reason)
            return
        op = self.dump
        self.dump = None
        self.cemu_active = False
        if op is None:
            return
        report = {
            'format': 'skylanders-ble-cemu-readonly-report-v3',
            'identity': list(op.identity), 'slot': op.slot,
            'completed': len(op.completed), 'requested': 64,
            'errors': op.errors, 'reason': reason or 'Fin de lecture',
            'timestamp': datetime.now().isoformat(timespec='seconds'),
        }
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        audit = EXPORT_DIR / ('last_read_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
        if len(op.completed) != 64:
            report['status'] = 'INCOMPLETE_NO_SKY'
            audit.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
            self.emit('cemu_done', text=f'Lecture incomplète {len(op.completed)}/64. Aucun .sky créé. {reason}', path='')
            return
        try:
            image = verified_image(op.completed, op.identity)
            target = save_sky(image, op.identity, self.cemu_name, 'bluetooth-portal-read-only')
        except Exception as exc:
            report['status'] = 'VALIDATION_FAILED_NO_SKY'
            report['error'] = str(exc)
            audit.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
            self.emit('cemu_done', text=f'Export refusé : {exc}', path='')
            return
        report['status'] = 'EXPORTED'
        report['sky_path'] = str(target)
        audit.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        self.emit('cemu_done', text=f'Export .sky réussi (1024 octets) : {target}', path=str(target))

    async def tick(self, client: Any, write_char: Any) -> None:
        now = time.monotonic()
        if self.cemu_waiting is None and not self.dump and not self.waiting_for_trap:
            try:
                if self.cemu_requests.get_nowait() == 'export_one':
                    self.cemu_waiting = now
                    self.emit('cemu_progress', text='Recherche d’un objet NFC identifié et stable (un seul à la fois)…')
            except queue.Empty:
                pass
        if self.cemu_waiting is not None and self.dump is None and self.pending is None:
            objects = [(slot, obj) for slot, obj in sorted(self.slots.items())
                       if obj.result is not None and obj.missing_since is None]
            stable = [(slot, obj) for slot, obj in objects if self.any_slot_stable(now, slot)]
            if len(objects) == 1 and len(stable) == 1:
                slot, obj = stable[0]
                self.cemu_waiting = None
                self.cemu_active = True
                self.cemu_name = obj.result.label
                identity = (obj.result.character_id, obj.result.variant_id)
                # Read block 1 first, verify same identity, then capture all other blocks.
                order = (1,) + tuple(i for i in range(64) if i != 1)
                self.dump = TrapDump(requested=order, slot=slot, identity=identity)
                self.emit('cemu_progress', text=f'Objet {self.cemu_name} (emplacement {slot}) : lecture NFC de 64 blocs…')
            elif now - self.cemu_waiting >= TRAP_WAIT_SECONDS:
                self.cemu_waiting = None
                self.emit('cemu_done', text=('Aucun objet UNIQUE identifié et stable. '
                                              'Laisse un seul objet sur le portail ; active la lecture NFC, puis repose-le.'), path='')
        await super().tick(client, write_char)


class CemuSuite(SkylandersSuite):
    def __init__(self, root):
        import tkinter as tk
        self.cemu_requests = queue.Queue()
        self.cemu_window = None
        self.cemu_text = None
        super().__init__(root)
        root.title('Skylanders Bluetooth Bridge V3 — Export Cemu expérimental')
        menu = root['menu']
        # Tk stores menu as Tcl path; use native Menu instance instead of rebuilding V2 menus.
        bridge = tk.Menu(root, tearoff=False)
        bridge.add_command(label='Exporter l’objet présent vers Cemu (.sky)…', command=self.open_cemu)
        menu_obj = root.nametowidget(menu)
        menu_obj.add_cascade(label='Bridge Cemu V3', menu=bridge)
        self.append('V3 : export Cemu .sky (lecture NFC seule). Aucun pilotage automatique de Cemu.')

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.cancel_demo()
        self.clear_objects()
        self.portal_connected = False
        self.stop = threading.Event()
        self.allow_reads.set() if self.read_var.get() else self.allow_reads.clear()
        self.allow_trap_reads.set() if self.trap_var.get() else self.allow_trap_reads.clear()
        self.reread_requests = queue.Queue()
        self.dump_requests = queue.Queue()
        self.cemu_requests = queue.Queue()
        self.running = True
        self.demo_mode = False
        self.update_buttons()
        self.connection_label.set('Recherche…')
        self.status_dot.configure(fg=self.ORANGE)
        self.hint.set('Connexion BLE. Menu Bridge Cemu V3 pour exporter un .sky.')
        worker = CemuExportWorker(self.events, self.stop, self.allow_reads,
                                  self.allow_trap_reads, self.reread_requests,
                                  self.catalogue, self.dump_requests, self.cemu_requests)
        self.thread = threading.Thread(target=worker_entry, args=(worker,), daemon=True)
        self.thread.start()

    def on_event(self, event: str, **data: Any) -> None:
        if event in ('cemu_done', 'cemu_progress'):
            line = data.get('text', '')
            self.append('CEMU : ' + line)
            if self.cemu_text is not None:
                try:
                    self.cemu_text.configure(state='normal')
                    self.cemu_text.insert('end', line + '\n')
                    self.cemu_text.see('end')
                    self.cemu_text.configure(state='disabled')
                except Exception:
                    self.cemu_text = None
            return
        super().on_event(event, **data)

    def open_cemu(self):
        import tkinter as tk
        from tkinter import filedialog, messagebox
        if self.cemu_window is not None and self.cemu_window.winfo_exists():
            self.cemu_window.lift(); return
        p = tk.Toplevel(self.root)
        p.title('Bridge Cemu V3 — première passerelle .sky')
        p.geometry('850x545')
        p.configure(bg=self.BG)
        self.cemu_window = p
        tk.Label(p, text='BLE → SAUVEGARDE .SKY → CEMU', fg=self.ACCENT, bg=self.BG,
                 font=('Segoe UI', 15, 'bold')).pack(anchor='w', padx=16, pady=12)
        tk.Label(p, text=(
            'V3 : étape 1. Exporte UNE vraie figurine ou UN piège en 64 blocs (1 024 octets).\n'
            'Charge ensuite le .sky dans Cemu : Tools → Emulated USB Devices → Skylanders Portal → Load.\n'
            'Cemu ne reçoit pas encore automatiquement les poses/retraits du portail Bluetooth.\n'
            'Attention : les sauvegardes faites par le jeu dans le .sky ne reviennent PAS sur la figurine physique.'),
                 fg=self.TEXT, bg=self.BG, justify='left', wraplength=790).pack(anchor='w', padx=16)
        bar = tk.Frame(p, bg=self.BG); bar.pack(fill='x', padx=16, pady=14)
        def export_live():
            if not self.running or not self.portal_connected:
                messagebox.showwarning('Portail déconnecté', 'Connecte le portail dans la fenêtre principale.', parent=p)
                return
            if not self.allow_reads.is_set():
                messagebox.showwarning('Lecture NFC', 'Active « Autoriser la lecture NFC automatique », puis repose ton objet.', parent=p)
                return
            if not messagebox.askyesno('Lecture seule', 'Lire 64 blocs (1 024 octets) sur UN objet et créer un fichier .sky ?\n'
                                        'Il n’y aura aucune écriture NFC physique.', parent=p):
                return
            self.cemu_requests.put('export_one')
            self.append('CEMU : Demande d’export reçue.')
        def import_report():
            filename = filedialog.askopenfilename(parent=p, title='Ancienne sauvegarde complète V2.3',
                                                   filetypes=[('Rapport de piège JSON', 'trap_*.json'), ('JSON', '*.json')])
            if not filename:
                return
            try:
                image, ident = load_old_dump(Path(filename))
                target = save_sky(image, ident, 'Trap', f'archive-v2.3:{Path(filename).name}')
                self.on_event('cemu_done', text=f'Ancien piège exporté : {target}', path=str(target))
            except Exception as exc:
                messagebox.showerror('Export refusé', str(exc), parent=p)
        def open_folder():
            EXPORT_DIR.mkdir(exist_ok=True)
            if os.name == 'nt':
                os.startfile(str(EXPORT_DIR))
            else:
                self.on_event('cemu_progress', text=f'Dossier : {EXPORT_DIR}')
        for title, fn in [('Exporter l’objet présent (.sky)', export_live),
                          ('Convertir une ancienne sauvegarde piège', import_report),
                          ('Ouvrir les .sky', open_folder)]:
            tk.Button(bar, text=title, command=fn, bg=self.PANEL2, fg=self.TEXT, padx=10, pady=7).pack(side='left', padx=4)
        self.cemu_text = tk.Text(p, fg=self.TEXT, bg=self.PANEL, font=('Consolas', 10), height=15)
        self.cemu_text.pack(fill='both', expand=True, padx=16, pady=(0, 16))
        self.cemu_text.insert('end', 'Cette V3 effectue l’export, pas encore une connexion virtuelle en temps réel.\n')
        self.cemu_text.configure(state='disabled')
        def on_close():
            self.cemu_text = None; self.cemu_window = None; p.destroy()
        p.protocol('WM_DELETE_WINDOW', on_close)


def self_test():
    import tempfile
    from skylanders_bridge_v1_2 import Slot, NfcResult
    v2_self_test()
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        # Synthesize structurally valid NFC image, no real keys or user dumps.
        arr = bytearray(1024)
        arr[0:4] = bytes.fromhex('01 02 03 04')
        arr[16:18] = (470).to_bytes(2, 'little')
        arr[28:30] = (12288).to_bytes(2, 'little')
        arr[30:32] = crc16(arr[:30]).to_bytes(2, 'little')
        blocks = {i: bytes(arr[i*16:(i+1)*16]) for i in range(64)}
        assert verified_image(blocks, (470,12288)) == bytes(arr)
        try:
            verified_image({i:b for i,b in blocks.items() if i != 17}, (470,12288))
            raise AssertionError('incomplete dump accepted')
        except ValueError: pass
        raw = save_sky(bytes(arr), (470,12288), 'Jawbreaker', 'test', root)
        assert raw.stat().st_size == 1024
        assert raw.read_bytes() == bytes(arr)
        report = {'format': 'skylanders-bridge-trap-readonly-v1',
                  'blocks': {str(i): blocks[i].hex() for i in range(64)},
                  'identity': {'character_id': 470, 'variant_id': 12288},
                  'sha256': hashlib.sha256(arr).hexdigest()}
        f = root/'trap_test.json'; f.write_text(json.dumps(report), encoding='utf8')
        got, identity = load_old_dump(f)
        assert got == bytes(arr) and identity == (470,12288)
        report['blocks'].pop('5'); f.write_text(json.dumps(report))
        try:
            load_old_dump(f)
            raise AssertionError('incomplete JSON accepted')
        except ValueError: pass
        events = queue.Queue(); s = threading.Event()
        worker = CemuExportWorker(events,s,s,s,queue.Queue(),None,queue.Queue(),queue.Queue())
        worker.slots[0] = Slot(since=time.monotonic()-2, readings=5,
                               result=NfcResult(0,1,470,12288,'','Jawbreaker'))
        worker.slot_present_frames[0] = 5
        worker.last_slot_present[0] = time.monotonic()
        worker.cemu_requests.put('export_one')
        class FakeClient:
            def __init__(self): self.sent=[]
            async def write_gatt_char(self, _handle, payload, response=True):
                assert payload[0] == ord('Q') and response
                self.sent.append(payload)
        client=FakeClient()
        asyncio.run(worker.tick(client, object()))
        assert worker.cemu_active and worker.dump is not None
        assert len(client.sent) == 1 and client.sent[0][:3] == bytes.fromhex('51 10 01')
        # Simulate 64 BLE Q replies and verify a complete live .sky is exported.
        global EXPORT_DIR
        old_dir = EXPORT_DIR
        EXPORT_DIR = root / 'live_exports'
        try:
            async def simulated_hardware():
                processed = 0
                while worker.dump is not None:
                    if len(client.sent) == processed:
                        await worker.tick(client, object())
                        continue
                    packet = client.sent[processed]
                    processed += 1
                    block = packet[2]
                    reply = bytes((ord('Q'), packet[1], block)) + blocks[block] + bytes(1)
                    worker.process_q(reply)
                return processed
            count = asyncio.run(simulated_hardware())
            assert count == 64, count
            outputs = list(EXPORT_DIR.glob('*.sky'))
            assert len(outputs) == 1 and outputs[0].read_bytes() == bytes(arr)
            assert len(client.sent) == 64
            assert not any(req[:1] == b'W' for req in client.sent)
        finally:
            EXPORT_DIR = old_dir
    print('V3 OK : export .sky 1024, CRC, SHA, refus incomplet, requête Q unitaire, compat V2.')


def main():
    ap=argparse.ArgumentParser(description='Skylanders Bridge V3 — import .sky Cemu')
    ap.add_argument('--self-test', action='store_true')
    args=ap.parse_args()
    if args.self_test:
        self_test(); return
    import tkinter as tk
    root=tk.Tk()
    CemuSuite(root)
    root.mainloop()


if __name__ == '__main__':
    main()
