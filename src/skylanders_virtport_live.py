#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Skylanders BLE -> VirtPort/Cemu, sans clics sur la fenêtre de jeu.

Utilise seulement Q (lecture) sur le portail physique. Cemu peut modifier
les copies virtuelles .dump ; on NE réécrit jamais sur les puces NFC.
Prototype non testé sur un ordinateur Windows réel avec VirtPort.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from skylanders_bridge_v1_2 import worker_entry
from skylanders_catalogue import Catalogue, load_catalog
from skylanders_cemu_bridge import CemuExportWorker, verified_image, identity_from_data
from skylanders_extras import TrapDump, ControllerWorker, controller_entry
from skylanders_trap_decoder import decode_trap_bytes, TrapDecodeError
from skylanders_sync_guard import (register_reference, register_virtual, compare,
                                   prepare_reports, atomic_write_new, sha256, SafetyError)

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / 'virtport_cache'
INDEX = CACHE_DIR / 'index.json'
GAME_DIR = ROOT / 'virtport_game_saves'
DEVICE_ID = 'skylanders-ble-bridge-v4'  # garder l'identité réseau déjà testée
BASE_URL = 'http://127.0.0.1:5678'


def trap_summary(image: bytes) -> str:
    """Identité et méchant contenu dans une IMAGE VIRTUELLE; pas de contact NFC."""
    if len(image) != 1024:
        return 'Données incomplètes : 1 024 octets attendus.'
    fid = int.from_bytes(image[16:18], 'little')
    if not (210 <= fid <= 220):
        return ''
    try:
        info = decode_trap_bytes(image)
        current = info.get('current_villain')
        name = current['name'] if current else 'aucun / vide'
        others = ', '.join(x['name'] for x in info.get('villains_in_active_save', [])) or 'aucun'
        return f'Piège #{fid} : méchant sélectionné = {name} ; enregistrés : {others}'
    except (TrapDecodeError, ValueError, TypeError) as exc:
        return f'Piège #{fid} : contenu non décodable ({exc}) ; données brutes conservées.'


def cache_key(result) -> str:
    # Bloc 1 comprend des octets de puce plus discriminants que l'ID du modèle.
    # Ce n'est PAS une garantie d'UID unique : le cache se désactive si nécessaire.
    data = bytes.fromhex(result.data_hex)
    return hashlib.sha256(data).hexdigest()


def load_index() -> dict:
    try:
        result = json.loads(INDEX.read_text(encoding='utf-8'))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def persist_index(index: dict) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    temp = INDEX.with_suffix('.tmp')
    temp.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding='utf-8')
    temp.replace(INDEX)


def validate_image(path: Path, identity: tuple[int, int]) -> bytes:
    data = path.read_bytes()
    if len(data) != 1024:
        raise ValueError('Taille NFC incorrecte : 1024 octets attendus')
    blocks = {i: data[16*i:16*(i+1)] for i in range(64)}
    verified_image(blocks, identity)
    return data


def import_sky_files(files: list[Path], index: dict) -> tuple[int, list[str]]:
    """Importe des exports V3 existants sans les modifier, cache local isolé."""
    CACHE_DIR.mkdir(exist_ok=True)
    imported, problems = 0, []
    for file in files:
        try:
            original = Path(file).read_bytes()
            if len(original) != 1024:
                raise ValueError('1024 octets requis')
            ident = identity_from_data(original)
            verified_image({i: original[i*16:(i+1)*16] for i in range(64)}, ident)
            key = hashlib.sha256(original[16:32]).hexdigest()
            # Le nom du fichier tient compte du CONTENU : une sauvegarde éditée
            # du même Skylander ne peut plus être bloquée par une ancienne version.
            version = hashlib.sha256(original).hexdigest()[:16]
            output = CACHE_DIR / f'{key}_{version}.sky'
            if not output.exists():
                with output.open('xb') as fd:
                    fd.write(original)
            index[key] = {'path': str(output.resolve()), 'ident': list(ident), 'version': version}
            imported += 1
        except (OSError, ValueError) as exc:
            problems.append(f'{Path(file).name} : {exc}')
    if imported:
        persist_index(index)
    return imported, problems


class VirtPort:
    """Client HTTP du serveur SkylanderServer.cpp de VirtPort (port 5678).
    Aucune interface réseau exposée par NOTRE outil; localhost uniquement.
    """
    def __init__(self, url: str = BASE_URL, device_id: str = DEVICE_ID):
        if url != BASE_URL:
            raise ValueError('Cette V4 n’autorise que http://127.0.0.1:5678')
        self.url, self.device_id = url, device_id

    def request(self, path: str, body: Optional[bytes] = None) -> bytes:
        method = 'POST' if body is not None else 'GET'
        req = urllib.request.Request(
            self.url + path, data=body, method=method,
            headers={'X-Device-Id': self.device_id,
                     'Content-Type': 'application/octet-stream'} if body is not None
            else {'X-Device-Id': self.device_id}
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            raw = response.read()
            if response.status != 200:
                raise RuntimeError(f'HTTP {response.status}: {raw[:120]!r}')
            return raw

    def ping(self) -> bool:
        return self.request('/ping') == b'PONG'

    def url_for(self, path: str, **kwargs) -> str:
        return path + '?' + urllib.parse.urlencode(kwargs)

    def heartbeat(self) -> None:
        self.request(self.url_for('/heartbeat', deviceId=self.device_id))

    def claim(self, slot: int) -> None:
        data = self.request(self.url_for('/claim', slot=slot, deviceId=self.device_id))
        if data != b'CLAIMED':
            raise RuntimeError(f'Réservation slot {slot} : {data[:80]!r}')

    def upload(self, slot: int, image: bytes) -> None:
        if len(image) != 1024:
            raise ValueError('Refus : image NFC incomplète')
        res = self.request(self.url_for('/upload', slot=slot, deviceId=self.device_id), body=image)
        if res != b'OK':
            raise RuntimeError(f'Upload non confirmé : {res[:80]!r}')

    def summon(self, slot: int) -> None:
        # Chemin interprété par Cemu dans son propre dossier de travail.
        name = f'SkylandersDumps/Slot{slot}.dump'
        res = self.request(self.url_for('/', cmd='SUMMON', slot=slot,
                                         file=name, deviceId=self.device_id))
        if res != b'SUMMON OK':
            raise RuntimeError(f'Summon non confirmé : {res[:80]!r}')

    def download(self, slot: int) -> bytes:
        data = self.request(self.url_for('/download', slot=slot))
        if len(data) != 1024:
            raise ValueError('Sauvegarde de Cemu absente ou incomplète')
        return data

    def clear(self, slot: int) -> None:
        res = self.request(self.url_for('/', cmd='CLEAR', slot=slot, deviceId=self.device_id))
        if res != b'CLEAR OK':
            raise RuntimeError(f'Clear non confirmé : {res[:80]!r}')


class LiveWorker(CemuExportWorker):
    """Réutilise le moteur BLE déjà testé, avec Q uniquement.
    Sérialise les 64 demandes Q par objet. Plusieurs slots peuvent être
    chargés mais leur premier scan est séquentiel.
    """
    def __init__(self, events: queue.Queue, stop: threading.Event, catalogue,
                 known_cache: dict, fresh: bool = False):
        a, b = threading.Event(), threading.Event()
        a.set(); b.set()
        super().__init__(events, stop, a, b, queue.Queue(), catalogue,
                         queue.Queue(), queue.Queue())
        self.cache = known_cache
        self.fresh = fresh
        self.scheduled: dict[int, str] = {}
        self.active_slot: Optional[tuple[int, str]] = None

    def emit(self, kind: str, **kw):
        if kind == 'cemu_done' and self.active_slot is not None:
            slot, key = self.active_slot
            if kw.get('path'):
                super().emit('live_ready', slot=slot, fingerprint=key,
                             path=kw['path'], cached=False)
            else:
                super().emit('live_failure', slot=slot, text=kw.get('text', 'Lecture incomplète'))
            self.active_slot = None
        super().emit(kind, **kw)

    async def tick(self, client, write_char):
        await super().tick(client, write_char)
        for slot in tuple(self.scheduled):
            if slot not in self.slots:
                self.scheduled.pop(slot, None)
        if self.dump is not None or self.pending is not None or self.cemu_waiting is not None:
            return
        for slot, obj in sorted(self.slots.items()):
            if slot > 7 or obj.result is None or obj.missing_since is not None:
                continue
            if not self.any_slot_stable(time.monotonic(), slot):
                continue
            key = cache_key(obj.result)
            if self.scheduled.get(slot) == key:
                continue
            self.scheduled[slot] = key
            identity = (obj.result.character_id, obj.result.variant_id)
            previous = self.cache.get(key)
            if previous and not self.fresh:
                try:
                    path = Path(previous['path'])
                    validate_image(path, identity)
                    self.emit('live_ready', slot=slot, fingerprint=key,
                              path=str(path), cached=True)
                    continue
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self.emit('message', text=f'Cache invalide : {exc} ; lecture complète requise.')
            self.cemu_active = True
            self.cemu_name = obj.result.label
            self.active_slot = (slot, key)
            self.dump = TrapDump(requested=(1,) + tuple(i for i in range(64) if i != 1),
                                 slot=slot, identity=identity)
            self.emit('live_progress', text=f'{obj.result.label}, slot {slot} : lecture de 64 blocs (première utilisation)…')
            break


class NetworkQueue:
    """Découple complètement HTTP, Bluetooth et interface graphique."""
    def __init__(self, output: queue.Queue, game_cache: dict, server: VirtPort):
        self.server, self.output, self.cache = server, output, game_cache
        self.tasks = queue.Queue()
        self.live: dict[int, dict] = {}
        self.last_heartbeat = 0.0
        self.pending_removals: dict[int, float] = {}
        self.last_snapshot = time.monotonic()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def enqueue(self, verb: str, **kw):
        self.tasks.put((verb, kw))

    def emit(self, text: str):
        self.output.put(('network_message', {'text': text}))

    def slot_for(self, physical_slot: int) -> int:
        # Simple mapping 0..7. Un objet hors de ces slots sera ignoré.
        return physical_slot

    def save_game(self, item: dict) -> bool:
        """Durable Cemu snapshot, validated against the physical tag reference.

        Network/read errors are propagated: NEVER silently CLEAR an unsaved slot.
        """
        slot = item['virt_slot']
        image = self.server.download(slot)
        ident = tuple(item['ident'])
        verified_image({i: image[i*16:(i+1)*16] for i in range(64)}, ident)
        # A matching character ID is not enough: another figure may share it.
        # Preserve the read-only source tag's UID and identification blocks.
        base = Path(item['reference']).read_bytes()
        if image[:48] != base[:48]:
            raise SafetyError('Identité NFC/UID ou blocs statiques modifiés dans Cemu : '
                              'la sauvegarde virtuelle ne peut pas remplacer cette référence.')
        old_hash = item.get('saved_hash')
        if old_hash == sha256(image):
            return False  # no redundant snapshots every 2 minutes
        GAME_DIR.mkdir(exist_ok=True)
        filename = GAME_DIR / (f'slot{slot}_{datetime.now().strftime("%Y%m%d_%H%M%S_%f")}.sky')
        atomic_write_new(filename, image)
        register_virtual(item['fingerprint'], image, filename)
        item['game_save'] = str(filename)
        item['saved_hash'] = sha256(image)
        # Only advance cache AFTER a validated, durable snapshot has been made.
        self.cache[item['fingerprint']] = {'path': str(filename), 'ident': list(ident)}
        persist_index(self.cache)
        self.emit(f'✅ Progression VirtPort sauvegardée : {filename.name} (copie physique inchangée).')
        summary = trap_summary(image)
        if summary:
            self.emit(summary)
        return True

    def process(self, cmd: str, data: dict):
        if cmd == 'snapshot':
            # Une sauvegarde de secours pendant le jeu, sans retirer le Skylander.
            if not self.live:
                self.emit('Aucun objet actif : rien à sauvegarder.')
            for item in list(self.live.values()):
                self.save_game(item)
            self.last_snapshot = time.monotonic()
        elif cmd == 'inspect_traps':
            traps = [item for item in list(self.live.values()) if 210 <= int(item['ident'][0]) <= 220]
            if not traps:
                self.emit('Aucun piège actuellement chargé dans VirtPort. Pose un piège, attends son chargement, puis réessaie.')
            for item in traps:
                # Stocker l'état virtuel actuel du piège avant de le décoder.
                self.save_game(item)
        elif cmd == 'write_reports':
            reports = prepare_reports()
            self.emit(f'Rapports NFC hors ligne : {len(reports)} créé(s) dans safesync/change_reports. Aucune écriture physique.')
        elif cmd == 'ping':
            self.emit('VirtPort actif, connexion localhost OK.' if self.server.ping() else 'Réponse inattendue de VirtPort.')
        elif cmd == 'ready':
            t0 = time.perf_counter()
            phys = int(data['slot'])
            virt = self.slot_for(phys)
            path = Path(data['path'])
            image = path.read_bytes()
            ident = identity_from_data(image)
            validate_image(path, ident)
            if phys in self.live:
                self.process('remove', {'slot': phys})
                if phys in self.live:
                    raise RuntimeError('Ancienne sauvegarde non récupérée : nouveau chargement refusé pour éviter une perte.')
            # Reference must be durable BEFORE sending the original data to Cemu.
            provenance = ('lecture-directe-BLE' if not data.get('cached')
                          else 'cache-PC-non-certifie-original-NFC')
            reference = register_reference(data['fingerprint'], image, provenance=provenance,
                                           name=f'{ident[0]} / {ident[1]}')
            self.server.claim(virt)
            self.server.upload(virt, image)
            self.server.summon(virt)
            self.live[phys] = {'virt_slot': virt, 'ident': list(ident),
                               'fingerprint': data['fingerprint'], 'path': str(path),
                               'reference': str(reference),
                               'saved_hash': sha256(image) if data.get('cached') else None}
            self.pending_removals.pop(phys, None)
            self.emit(f'✅ Slot {virt} ajouté dans Cemu : ID {ident[0]}, variante {ident[1]} '
                      f'— {"cache" if data.get("cached") else "lecture complète"} ; '
                      f'durée VirtPort {time.perf_counter() - t0:.2f}s.')
            summary = trap_summary(image)
            if summary:
                self.emit('🎮 Piège transmis à VirtPort. ' + summary)
        elif cmd == 'remove':
            phys = int(data['slot'])
            item = self.live.get(phys)
            if item is None:
                self.pending_removals.pop(phys, None)
                return
            try:
                self.save_game(item)
                self.server.clear(item['virt_slot'])
            except Exception as exc:
                # The old bridge CLEARED even when the download failed.
                # Never clear the game slot without a verified local backup.
                self.pending_removals[phys] = time.monotonic() + 5.0
                self.emit(f'⚠️ RETRAIT DIFFÉRÉ slot {phys} : sauvegarde ou CLEAR impossible '
                          f'({exc}). On réessaiera, sans effacer les données VirtPort.')
                return
            self.pending_removals.pop(phys, None)
            self.live.pop(phys, None)
            self.emit(f'Objet retiré de Cemu : slot {item["virt_slot"]}.')
        elif cmd == 'all_clear':
            for slot in list(self.live):
                self.process('remove', {'slot': slot})

    def run(self):
        while not self.stopped.is_set():
            try:
                cmd, data = self.tasks.get(timeout=0.25)
            except queue.Empty:
                cmd = None
            try:
                if cmd:
                    self.process(cmd, data)
                for phys, due in list(self.pending_removals.items()):
                    if time.monotonic() >= due:
                        self.pending_removals[phys] = time.monotonic() + 5.0
                        self.process('remove', {'slot': phys})
                if self.live and time.monotonic() - self.last_heartbeat >= 3:
                    self.server.heartbeat()
                    self.last_heartbeat = time.monotonic()
                # Sauvegarde de secours à intervalle raisonnable, uniquement sur PC.
                if self.live and time.monotonic() - self.last_snapshot >= 120:
                    self.process('snapshot', {})
            except Exception as exc:
                self.emit(f'❌ {cmd or "heartbeat"}: {type(exc).__name__} : {exc}')
            finally:
                if cmd is not None:
                    self.tasks.task_done()
        # Ne pas tenter d'effacer les slots automatiquement en quittant si
        # serveur arrêté : VirtPort possède son propre timeout 10s.



def resilient_portal_entry(events, stop, cache, fresh):
    """Relance proprement un nouveau worker après déconnexion BLE fortuite."""
    attempts = 0
    while not stop.is_set():
        worker = LiveWorker(events, stop, Catalogue(load_catalog()), cache, fresh)
        worker_entry(worker)
        if stop.is_set():
            return
        attempts += 1
        delay = min(2 ** min(attempts, 4), 16)
        events.put(('message', {'text': f'Portail perdu : reconnexion automatique dans {delay}s (tentative {attempts}).'}))
        if stop.wait(delay):
            return


def resilient_controller_entry(events, stop):
    """Relance aussi la manette XInput, en relâchant les boutons à la déconnexion."""
    attempts = 0
    while not stop.is_set():
        worker = ControllerWorker(events, stop, xinput=True)
        controller_entry(worker)
        if stop.is_set():
            return
        attempts += 1
        delay = min(2 ** min(attempts, 4), 16)
        events.put(('gamepad_info', {'text': f'Manette perdue : reconnexion dans {delay}s (tentative {attempts}).'}))
        if stop.wait(delay):
            return


class App:
    def __init__(self, root, fresh: bool = False):
        import tkinter as tk
        self.root, self.fresh = root, fresh
        self.events, self.stop = queue.Queue(), threading.Event()
        self.cache = load_index()
        self.network = NetworkQueue(self.events, self.cache, VirtPort())
        self.portal_thread = None
        self.controller_thread = None
        self.controller_stop = threading.Event()
        self.worker = None
        self.present: set[int] = set()
        self.running = False
        self._closing = False
        self.status = tk.StringVar(value='Pas connecté')
        self.controller_status = tk.StringVar(value='Manette non connectée')
        self.log_box = None
        root.title('Skylanders Bridge V4.3 — SafeSync / plein écran')
        root.geometry('1120x620')
        root.configure(bg='#121b2b')
        fg='#edf5fc'
        tk.Label(root, text='SKYLANDERS  •  BLUETOOTH → CEMU', bg='#121b2b', fg='#61cfff',
                 font=('Segoe UI', 20, 'bold')).pack(anchor='w', padx=18, pady=12)
        tk.Label(root, text='V4.3 • SafeSync : sauvegardes vérifiées, rapports NFC, écriture physique désactivée',
                 bg='#121b2b', fg=fg).pack(anchor='w', padx=18)
        tk.Label(root, textvariable=self.status, bg='#121b2b', fg='#fbdf9a').pack(anchor='w', padx=18, pady=8)
        row = tk.Frame(root, bg='#121b2b'); row.pack(anchor='w', padx=12, pady=9)
        for name, call in [('Tester Cemu/VirtPort', self.ping), ('Importer .sky V3', self.import_existing),
                           ('Connecter le portail BLE', self.connect),
                           ('Connecter manette Xbox', self.connect_controller),
                           ('Arrêter manette', self.disconnect_controller), ('Déconnecter', self.disconnect)]:
            tk.Button(row, text=name, command=call, bg='#284562', fg=fg, padx=9, pady=5).pack(side='left', padx=5)
        extra = tk.Frame(root, bg='#121b2b'); extra.pack(anchor='w', padx=12, pady=3)
        for name, call in [('Sauvegarder maintenant (.sky)', self.snapshot),
                           ('Lire les méchants des pièges VirtPort', self.inspect_traps),
                           ('Préparer rapports NFC (sans écriture)', self.prepare_reports),
                           ('Ouvrir sauvegardes', self.open_saves),
                           ('Ouvrir cache', self.open_cache)]:
            tk.Button(extra, text=name, command=call, bg='#24523b', fg=fg, padx=10, pady=4).pack(side='left', padx=5)
        instructions = (
            'Lance Cemu VirtPort. Ouvre UNE FOIS Tools → Emulated USB Devices ;\n'
            'minimise cette fenêtre (ne la ferme pas), puis joue en plein écran.\n'
            'Premier contact : lecture NFC 64 blocs ; suivants : cache rapide.\n'
            'Pièges : l’emplacement contient une copie complète, que Trap Team peut modifier en jeu.\n'
            'Sauvegarde au retrait / toutes les 2 min ; retrait différé en cas d’erreur réseau. NFC physique lecture seule.'
        )
        tk.Label(root, text=instructions,
                 bg='#121b2b', fg='#d0d9e1', justify='left').pack(anchor='w', padx=18, pady=9)
        tk.Label(root, textvariable=self.controller_status, bg='#121b2b', fg='#a5dbb4').pack(anchor='w', padx=18)
        self.log_box = tk.Text(root, bg='#06111e', fg=fg, font=('Consolas', 10))
        self.log_box.pack(fill='both', expand=True, padx=18, pady=8)
        self.log('Ouvre VirtPort / Cemu, puis clique « Tester Cemu/VirtPort ».')
        self.log('La fenêtre Emulated USB Devices doit rester ouverte (mais peut être minimisée).')
        root.after(120, self.poll)
        root.protocol('WM_DELETE_WINDOW', self.close)

    def log(self, text):
        self.log_box.insert('end', text + '\n')
        self.log_box.see('end')

    def prepare_reports(self):
        self.network.enqueue('write_reports')
        self.log('Génération de rapports de différences, lecture seule, sans Bluetooth.')

    def ping(self):
        self.network.enqueue('ping')

    def snapshot(self):
        self.network.enqueue('snapshot')
        self.log('Demande de sauvegarde de secours envoyée à VirtPort…')

    def inspect_traps(self):
        self.network.enqueue('inspect_traps')
        self.log('Lecture des copies virtuelles des pièges en cours (sans toucher aux puces physiques)...')

    def open_saves(self):
        import os
        GAME_DIR.mkdir(exist_ok=True)
        os.startfile(str(GAME_DIR))  # Windows uniquement

    def open_cache(self):
        import os
        CACHE_DIR.mkdir(exist_ok=True)
        os.startfile(str(CACHE_DIR))  # Windows uniquement


    def import_existing(self):
        from tkinter import filedialog
        selected = filedialog.askopenfilenames(title='Choisir des fichiers .sky V3 précédemment exportés',
                                                filetypes=[('Skylanders', '*.sky')])
        if not selected:
            return
        count, problems = import_sky_files([Path(p) for p in selected], self.cache)
        self.log(f'{count} fichier(s) importé(s) dans le cache, prochain placement plus rapide.')
        for msg in problems:
            self.log('Import refusé : ' + msg)

    def connect(self):
        if self.portal_thread and self.portal_thread.is_alive():
            return
        self.stop = threading.Event()
        self.portal_thread = threading.Thread(target=resilient_portal_entry,
                                             args=(self.events, self.stop, self.cache, self.fresh), daemon=True)
        self.portal_thread.start()
        self.status.set('Recherche portail Bluetooth…')

    def connect_controller(self):
        if self.controller_thread and self.controller_thread.is_alive():
            return
        try:
            import vgamepad  # noqa: F401
        except ImportError:
            self.log('Manette Xbox : lance INSTALLER_SUPPORT_MANETTE.bat puis installe ViGEmBus depuis sa page officielle.')
            return
        self.controller_stop = threading.Event()
        self.controller_thread = threading.Thread(target=resilient_controller_entry,
                                                  args=(self.events, self.controller_stop), daemon=True)
        self.controller_thread.start()
        self.controller_status.set('Recherche manette BLE…')

    def disconnect_controller(self):
        self.controller_stop.set()
        self.controller_status.set('Déconnexion de la manette demandée')

    def disconnect(self):
        self.stop.set()
        self.network.enqueue('all_clear')
        self.status.set('Déconnexion en cours…')

    def poll(self):
        while True:
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            if kind in ('message', 'network_message', 'live_progress', 'live_failure', 'error'):
                self.log(data.get('text', ''))
            elif kind == 'connected':
                self.status.set('Portail connecté — jeu en plein écran possible')
            elif kind == 'slot':
                idx = data.get('index')
                if data.get('present') is False:
                    self.present.discard(idx)
                    self.network.enqueue('remove', slot=idx)
                elif data.get('present') is True:
                    self.present.add(idx)
            elif kind == 'live_ready':
                slot = int(data['slot'])
                if slot in self.present:
                    self.network.enqueue('ready', **data)
                else:
                    self.log('Objet déjà retiré, aucun upload vers Cemu.')
            elif kind == 'cemu_done':
                self.log(data.get('text', ''))
            elif kind in ('gamepad_info', 'gamepad_connected', 'gamepad_error', 'gamepad_stopped'):
                self.log(data.get('text', ''))
                self.controller_status.set(data.get('text', ''))
            elif kind == 'gamepad_state':
                self.controller_status.set('Manette Xbox : boutons ' + data.get('buttons', '') +
                     ' • joystick gauche ' + data.get('left', ''))
            elif kind == 'stopped':
                self.status.set('Portail déconnecté — reconnexion en cours…')
                self.present.clear()
                if not self._closing:
                    self.network.enqueue('all_clear')
            elif kind == 'close_done':
                self.root.destroy()
                return
        self.root.after(120, self.poll)

    def close(self):
        if self._closing:
            return
        self._closing = True
        self.disconnect_controller()
        self.disconnect()
        self.log('Fermeture : récupération des sauvegardes virtuelles avant arrêt…')
        def finish():
            # Évite qu'un processus Python daemon meure avant la sauvegarde.
            self.network.tasks.join()
            self.network.stopped.set()
            self.events.put(('close_done', {}))
        threading.Thread(target=finish, daemon=True).start()



def self_test():
    import tempfile
    from contextlib import contextmanager
    class Handler(BaseHTTPRequestHandler):
        data = {}
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(parsed.query)
            if parsed.path == '/ping': body = b'PONG'
            elif parsed.path == '/heartbeat': body = b'OK'
            elif parsed.path == '/claim': body = b'CLAIMED'
            elif parsed.path == '/download': body = self.data.get(int(q['slot'][0]), b'')
            elif q.get('cmd') == ['SUMMON']: body = b'SUMMON OK'
            elif q.get('cmd') == ['CLEAR']: body = b'CLEAR OK'
            else: self.send_error(404); return
            self.send_response(200); self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            slot = int(urllib.parse.parse_qs(parsed.query)['slot'][0])
            self.data[slot] = self.rfile.read(int(self.headers['Content-Length']))
            body = b'OK'
            self.send_response(200); self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def log_message(self, fmt, *args): pass
    # Fake localhost server: methods testable even on Linux; no actual Cemu needed.
    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as s:
        s_thread = threading.Thread(target=s.serve_forever, daemon=True); s_thread.start()
        class LocalVirt(VirtPort):
            def __init__(self):
                self.url = 'http://127.0.0.1:' + str(s.server_port)
                self.device_id = DEVICE_ID
        api = LocalVirt()
        assert api.ping()
        api.claim(0)
        fake = bytes(range(256)) * 4
        api.upload(0, fake)
        assert api.download(0) == fake
        api.summon(0)
        api.heartbeat()
        api.clear(0)
        s.shutdown()
    from skylanders_bridge_v1_2 import Slot, NfcResult
    now = time.monotonic()
    evs = queue.Queue()
    r = LiveWorker(evs, threading.Event(), Catalogue(load_catalog()), {}, False)
    r.slots[0] = Slot(since=now-2, readings=5, attempted=True,
                      result=NfcResult(0,1,470,12288,'d6 01 00 00 3d 2a 16 dd 8f de 00 00 00 30 af 9e','Jawbreaker'))
    r.slot_present_frames[0] = 3
    r.last_slot_present[0] = time.monotonic()
    class Client:
        def __init__(self): self.queries = []
        async def write_gatt_char(self, char, value, response=True):
            assert value[0] == ord('Q') and len(value) == 20 and response is True
            self.queries.append(value)
    cl = Client()
    asyncio.run(r.tick(cl, object()))
    assert r.dump is not None and r.dump.slot == 0
    asyncio.run(r.tick(cl, object()))
    assert cl.queries and cl.queries[0][:3] == b'Q\x10\x01'
    print('OK: protocole VirtPort vérifié en simulation, premiers Q sécurisés, cache, aucune commande NFC W.')
    print('Non testé sur Cemu VirtPort réel ni portail BLE réel.')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--self-test', action='store_true')
    p.add_argument('--fresh', action='store_true', help='Ignorer cache et relire 64 blocs de chaque objet')
    args = p.parse_args()
    if args.self_test:
        self_test()
    else:
        import tkinter as tk
        app = tk.Tk()
        App(app, fresh=args.fresh)
        app.mainloop()
