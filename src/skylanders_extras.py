# -*- coding: utf-8 -*-
"""Skylanders Bridge V2 — fonctions additionnelles, préservant la V1.2.

Tous les accès NFC sont des demandes Q de lecture. Aucune commande W n'est
construite dans cette application. Une écriture BLE pour envoyer Q n'est PAS
une écriture de mémoire NFC.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from skylanders_bridge_v1_2 import PortalWorker, NFC_BLOCK_IDENTITY, status_codes, REMOVAL_GRACE_SECONDS
from skylanders_ble_coord import guarded_discover

HERE = Path(__file__).resolve().parent
BACKUP_DIR = HERE / 'skylanders_backups'
CONTROLLER_SERVICE = '533e1531-3abe-f33f-cd00-594e8b0a8ea3'
CONTROLLER_NOTIFY = '533e1541-3abe-f33f-cd00-594e8b0a8ea3'
CONTROLLER_ADV_SERVICE = '00001531-0000-1000-8000-00805f9b34fb'
# Zones de sauvegarde des pièges mentionnées par nfc.toys : blocs 8-9,
# 13, 17, 33, 37-38, 42 et 62 ; ajout 0 et 1 pour comparer les identités.
TRAP_FOCUS_BLOCKS = (0, 1, 8, 9, 13, 17, 29, 33, 37, 38, 42, 61, 62)
TRAP_WAIT_SECONDS = 12.0   # Max wait for a real, stable identified trap signal
TRAP_STATUS_STALE_SECONDS = 1.8
TRAP_STABLE_FRAMES = 2


def nfc_query(slot: int, block: int) -> bytes:
    """Only the previously verified Q read command, for block 0..63."""
    if not (0 <= slot <= 15 and 0 <= block <= 63):
        raise ValueError('Emplacement ou bloc NFC hors limites')
    return bytes((ord('Q'), 0x10 | slot, block)) + bytes(17)


def decode_q(packet: bytes, expected_slot: int, expected_block: int) -> bytes:
    if len(packet) < 19 or packet[0] != ord('Q'):
        raise ValueError('Réponse Q tronquée ou mal formée')
    if packet[1] & 0x0F != expected_slot:
        raise ValueError('Emplacement Q différent')
    if not packet[1] & 0x10:
        raise ValueError('La lecture Q a échoué (drapeau de réussite absent)')
    if packet[2] != expected_block:
        raise ValueError('Réponse Q pour un autre bloc')
    return packet[3:19]


@dataclass
class TrapDump:
    requested: tuple[int, ...]
    slot: int = -1
    identity: tuple[int, int] = (-1, -1)
    started: float = field(default_factory=time.monotonic)
    waiting: tuple[int, float] | None = None
    completed: dict[int, bytes] = field(default_factory=dict)
    errors: dict[int, str] = field(default_factory=dict)
    next_index: int = 0
    failures_in_row: int = 0
    unstable_since: float | None = None


class ResearchPortalWorker(PortalWorker):
    """Extends the existing working portal worker with an explicitly requested
    trap block backup. Never writes to the NFC memory. One Q in flight max.
    """

    def __init__(self, events, stop, allow_reads, allow_trap_reads,
                 reread_requests, catalogue, dump_requests):
        super().__init__(events, stop, allow_reads, allow_trap_reads,
                         reread_requests, catalogue)
        self.dump_requests: queue.Queue = dump_requests
        self.dump: TrapDump | None = None
        self.waiting_for_trap: tuple[str, float] | None = None
        self.slot_present_frames: dict[int, int] = {}
        self.last_slot_present: dict[int, float] = {}
        self.last_trap_status = 0.0

    def process_status(self, payload: bytes) -> None:
        # Physical traps are NOT fixed to logical slot 2. In measured frames
        # a trap alone occupied slot 1; alongside a figure it occupied slot 2.
        # Track all logical slots and associate a trap with an NFC-verified ID.
        states = status_codes(payload)
        if states is not None:
            now = time.monotonic()
            self.last_trap_status = now
            for slot, code in enumerate(states):
                if code in (1, 3):
                    self.slot_present_frames[slot] = min(self.slot_present_frames.get(slot, 0) + 1, 20)
                    self.last_slot_present[slot] = now
                else:
                    self.slot_present_frames[slot] = 0
        super().process_status(payload)

    def identified_traps(self) -> list[tuple[int, Any]]:
        """Only NFC-identified traps, never an unclassified BLE presence."""
        return [(slot, obj) for slot, obj in sorted(self.slots.items())
                if obj.result is not None
                and 210 <= obj.result.character_id <= 220]

    def trap_is_stable(self, now: float, slot: int) -> bool:
        obj = self.slots.get(slot)
        return bool(obj is not None and obj.result is not None
                    and 210 <= obj.result.character_id <= 220
                    and obj.missing_since is None
                    and self.slot_present_frames.get(slot, 0) >= TRAP_STABLE_FRAMES
                    and now - self.last_slot_present.get(slot, -1e9) <= TRAP_STATUS_STALE_SECONDS)

    def trap_diagnostic(self, now: float) -> str:
        identified = self.identified_traps()
        if not identified:
            other = [str(i) for i, obj in sorted(self.slots.items()) if obj.missing_since is None]
            return ('aucun piège identifié par lecture NFC ; emplacements présents : '
                    + (', '.join(other) if other else 'aucun')
                    + '. Active la lecture NFC, puis retire et repose le piège')
        if len(identified) > 1:
            return 'plusieurs pièges identifiés ; laisse un seul piège sur le portail'
        slot, obj = identified[0]
        if obj.missing_since is not None:
            return f'piège reconnu en emplacement {slot}, mais signal de retrait détecté'
        age = now - self.last_slot_present.get(slot, -1e9)
        if age > TRAP_STATUS_STALE_SECONDS:
            return f'piège reconnu en emplacement {slot}, mais aucune trame S récente'
        return f'piège reconnu en emplacement {slot}, {self.slot_present_frames.get(slot, 0)} confirmation(s) de présence'

    async def run(self) -> None:
        try:
            await super().run()
        finally:
            if self.dump is not None:
                self.finish_dump('Connexion interrompue pendant la sauvegarde')
            if self.waiting_for_trap is not None:
                self.waiting_for_trap = None
                self.emit('dump_finished', text='Déconnexion avant stabilisation ; aucune commande Q de sauvegarde envoyée.')

    def process_q(self, payload: bytes) -> None:
        if self.dump is not None and self.dump.waiting is not None:
            block, _ = self.dump.waiting
            slot = self.dump.slot
            self.log('dump_response', block=block, raw_hex=payload.hex(' '))
            # Unexpected replies may be delayed from an earlier request;
            # do NOT attribute them to the currently requested block.
            try:
                result = decode_q(payload, slot, block)
            except ValueError as exc:
                self.log('dump_unmatched_reply', waiting_for=block, error=str(exc))
                return
            # Read block 1 at the start and check it belongs to the same trap
            # that was identified by the normal reader before this dump.
            if block == 1:
                actual_identity = (int.from_bytes(result[0:2], 'little'),
                                   int.from_bytes(result[12:14], 'little'))
                if actual_identity != self.dump.identity:
                    self.log('dump_identity_mismatch', slot=slot,
                             expected=self.dump.identity, got=actual_identity)
                    self.finish_dump('Identité du piège différente pendant la sauvegarde ; arrêt de sécurité')
                    return
            self.dump.completed[block] = result
            self.dump.waiting = None
            self.dump.failures_in_row = 0
            self.emit('dump_progress', text=f'Bloc {block:02d} : {result.hex(" ")}',
                      completed=len(self.dump.completed), requested=len(self.dump.requested))
            return
        super().process_q(payload)

    def finish_dump(self, reason: str = '') -> None:
        dump = self.dump
        if dump is None:
            return
        self.dump = None
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        name = datetime.now().strftime('trap_%Y%m%d_%H%M%S')
        json_file = BACKUP_DIR / (name + '.json')
        records = {str(i): data.hex() for i, data in sorted(dump.completed.items())}
        report = {
            'format': 'skylanders-bridge-trap-readonly-v1',
            'warning': 'Dump local, lecture seule. Un bloc absent n\'est pas un bloc de zéros.',
            'slot': dump.slot,
            'identity': {'character_id': dump.identity[0], 'variant_id': dump.identity[1]},
            'requested_blocks': list(dump.requested),
            'blocks': records,
            'errors': {str(i): err for i, err in sorted(dump.errors.items())},
            'reason': reason or 'Fin de lecture',
            'generated': datetime.now().isoformat(timespec='seconds'),
            'complete_1024_bytes': all(i in dump.completed for i in range(64)),
        }
        if report['complete_1024_bytes']:
            data = b''.join(dump.completed[i] for i in range(64))
            bin_file = BACKUP_DIR / (name + '.bin')
            bin_file.write_bytes(data)
            report['sha256'] = hashlib.sha256(data).hexdigest()
            report['bin_file'] = str(bin_file)
        if report['complete_1024_bytes']:
            # Read-only offline analysis. A failure never alters the original dump.
            try:
                from skylanders_trap_decoder import decode_trap_bytes, format_summary
                decoded = decode_trap_bytes(data, expected_identity=dump.identity)
                report['decoded_content'] = decoded
                self.emit('dump_progress', text='\n' + format_summary(decoded))
            except Exception as exc:
                report['decode_error'] = str(exc)
                self.emit('dump_progress', text=f'Déchiffrement indisponible : {exc}')
        tmp = json_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        tmp.replace(json_file)
        self.log('dump_finished', path=str(json_file), blocks=len(records), reason=reason)
        self.emit('dump_finished', text=f'Lecture terminée : {len(records)}/{len(dump.requested)} blocs. {json_file}',
                  path=str(json_file), count=len(records), failures=len(dump.errors))

    async def tick(self, client: Any, write_char: Any) -> None:
        now = time.monotonic()
        if self.dump is not None:
            op = self.dump
            trap = self.slots.get(op.slot)
            if trap is None or trap.missing_since is not None:
                self.finish_dump('Piège retiré ou signal interrompu pendant la lecture')
                return
            if trap.result is None or (trap.result.character_id, trap.result.variant_id) != op.identity:
                self.finish_dump('Identité du piège modifiée pendant la lecture')
                return
            if op.waiting:
                block, t0 = op.waiting
                if now - t0 >= 3.7:
                    op.errors[block] = 'Aucune réponse Q validée dans les 3,7 secondes'
                    op.waiting = None
                    op.failures_in_row += 1
                    self.emit('dump_progress', text=f'Bloc {block:02d} : délai dépassé',
                              completed=len(op.completed), requested=len(op.requested))
                    if op.failures_in_row >= 3:
                        self.finish_dump('Arrêt après 3 lectures sans réponse')
                return
            if op.next_index >= len(op.requested):
                self.finish_dump()
                return
            # Do not issue a new Q while the trap is bouncing in/out of RF range.
            if not self.trap_is_stable(now, op.slot):
                if op.unstable_since is None:
                    op.unstable_since = now
                elif now - op.unstable_since > TRAP_WAIT_SECONDS:
                    self.finish_dump('Signal du piège absent/trop instable pendant la sauvegarde')
                return
            op.unstable_since = None
            block = op.requested[op.next_index]
            op.next_index += 1
            frame = nfc_query(op.slot, block)
            op.waiting = (block, time.monotonic())
            self.log('dump_query', slot=op.slot, block=block, frame=frame.hex(' '))
            try:
                await client.write_gatt_char(write_char, frame, response=True)
            except Exception as exc:
                op.errors[block] = f'{type(exc).__name__} : {exc}'
                op.waiting = None
                op.failures_in_row += 1
                if op.failures_in_row >= 3:
                    self.finish_dump('Erreurs BLE répétées')
            return

        # Queue a request until exactly one NFC-identified trap is stable in
        # whichever logical slot the physical portal assigned to it.
        if self.waiting_for_trap is None:
            try:
                mode = self.dump_requests.get_nowait()
            except queue.Empty:
                mode = None
            if mode:
                if mode not in ('focus', 'full'):
                    self.emit('dump_finished', text='Mode de sauvegarde inconnu ; rien envoyé.')
                else:
                    self.waiting_for_trap = (mode, now)
                    self.emit('dump_progress', text='Demande reçue. Recherche de l’emplacement réel du piège identifié…',
                              completed=0, requested=13 if mode == 'focus' else 64)
                    self.log('dump_waiting', mode=mode)
        if self.waiting_for_trap is not None:
            mode, started = self.waiting_for_trap
            if now - started >= TRAP_WAIT_SECONDS:
                self.waiting_for_trap = None
                reason = self.trap_diagnostic(now)
                self.log('dump_wait_timeout', reason=reason)
                self.emit('dump_finished', text=f'Piège non disponible après {TRAP_WAIT_SECONDS:.0f}s ({reason}). Aucune lecture de sauvegarde envoyée.')
            elif self.pending is None:
                candidates = [(slot, obj) for slot, obj in self.identified_traps()
                              if self.trap_is_stable(now, slot)]
                if len(candidates) == 1 and len(self.identified_traps()) == 1:
                    slot, obj = candidates[0]
                    blocks = TRAP_FOCUS_BLOCKS if mode == 'focus' else tuple(range(64))
                    self.waiting_for_trap = None
                    identity = (obj.result.character_id, obj.result.variant_id)
                    self.dump = TrapDump(requested=blocks, slot=slot, identity=identity)
                    self.emit('dump_progress',
                              text=f'Piège ID {identity[0]} / variante {identity[1]} reconnu en emplacement {slot} : lecture de {len(blocks)} blocs…',
                              completed=0, requested=len(blocks))
                    self.log('dump_started', requested=list(blocks), slot=slot, identity=list(identity))
                    return
        await super().tick(client, write_char)


@dataclass(frozen=True)
class ControllerState:
    buttons: tuple[str, ...]
    lx: int
    ly: int
    rx: int
    ry: int
    lt: int
    rt: int
    battery: int
    raw: str


def signed_byte(b: int) -> int:
    return b - 256 if b >= 128 else b


def decode_controller_packet(raw: bytes) -> ControllerState:
    if len(raw) < 16:
        raise ValueError(f'Trame manette trop courte : {len(raw)} octets')
    first = raw[8]
    second = raw[9]
    mask1 = [('↑', 0x01), ('↓', 0x02), ('←', 0x04), ('→', 0x08),
             ('A', 0x10), ('B', 0x20), ('X', 0x40), ('Y', 0x80)]
    mask2 = [('Guide', 0x04), ('LB', 0x10), ('RB', 0x20)]
    buttons = tuple(name for name, m in mask1 if first & m) + tuple(name for name, m in mask2 if second & m)
    return ControllerState(buttons, signed_byte(raw[14]), signed_byte(raw[15]),
                           signed_byte(raw[12]), signed_byte(raw[13]),
                           raw[10], raw[11], raw[3], raw.hex(' '))


class XInputAdapter:
    """Optional, explicitly enabled. Never installs kernel drivers."""
    def __init__(self):
        import vgamepad as vg  # only optional, never installed by the launcher
        self.vg = vg
        self.pad = vg.VX360Gamepad()
        self.map = {
            '↑': vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
            '↓': vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
            '←': vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
            '→': vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
            'A': vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
            'B': vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
            'X': vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
            'Y': vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
            'LB': vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
            'RB': vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
        }
        if hasattr(vg.XUSB_BUTTON, 'XUSB_GAMEPAD_GUIDE'):
            self.map['Guide'] = vg.XUSB_BUTTON.XUSB_GAMEPAD_GUIDE

    @staticmethod
    def normal(b: int) -> float:
        return max(-1.0, min(1.0, b / 127.0))

    def update(self, state: ControllerState) -> None:
        self.pad.reset()
        for name in state.buttons:
            if name in self.map:
                self.pad.press_button(button=self.map[name])
        # Direction Y des joysticks à ajuster après test sur matériel.
        self.pad.left_joystick_float(x_value_float=self.normal(state.lx),
                                     y_value_float=self.normal(state.ly))
        self.pad.right_joystick_float(x_value_float=self.normal(state.rx),
                                      y_value_float=self.normal(state.ry))
        self.pad.left_trigger(value=state.lt)
        self.pad.right_trigger(value=state.rt)
        self.pad.update()

    def close(self) -> None:
        self.pad.reset()
        self.pad.update()


class ControllerWorker:
    def __init__(self, events: queue.Queue, stop: threading.Event, xinput: bool = False):
        self.events = events
        self.stop = stop
        self.xinput = xinput
        self.last_render = 0.0
        self.frames = 0
        self.output: XInputAdapter | None = None

    def emit(self, kind: str, **kw: Any) -> None:
        self.events.put((kind, kw))

    async def run(self) -> None:
        from bleak import BleakScanner, BleakClient
        self.emit('gamepad_info', text='Recherche de la petite manette Bluetooth (15 s)…')
        matches = []
        for dev, adv in (await guarded_discover(BleakScanner, timeout=15, return_adv=True)).values():
            name = (adv.local_name or dev.name or '').lower()
            uuids = [u.lower() for u in (adv.service_uuids or [])]
            if ('skylanders' in name and ('gamepad' in name or 'controller' in name)) or CONTROLLER_ADV_SERVICE in uuids:
                matches.append((adv.rssi or -999, dev))
        if not matches:
            self.emit('gamepad_error', text='Manette introuvable. Allume-la et tente le bouton d’appairage.')
            return
        matches.sort(key=lambda x: x[0], reverse=True)
        async with BleakClient(matches[0][1], timeout=22) as client:
            ch = client.services.get_characteristic(CONTROLLER_NOTIFY)
            if not ch or 'notify' not in ch.properties:
                self.emit('gamepad_error', text='Canal de notifications du GamePad absent ; capture GATT nécessaire.')
                return
            if self.xinput:
                try:
                    self.output = XInputAdapter()
                except Exception as exc:
                    self.emit('gamepad_error', text=f'XInput indisponible : {exc}. Teste en mode surveillance seule.')
                    return
            def callback(_char, data):
                try:
                    state = decode_controller_packet(bytes(data))
                except ValueError:
                    return
                if self.output:
                    try:
                        self.output.update(state)
                    except Exception as exc:
                        self.emit('gamepad_error', text=f'Erreur XInput : {exc}')
                        self.stop.set()
                self.frames += 1
                if time.monotonic() - self.last_render > 0.09:
                    self.last_render = time.monotonic()
                    self.emit('gamepad_state', buttons=' '.join(state.buttons) or 'aucun',
                              left=f'{state.lx:+d}, {state.ly:+d}',
                              right=f'{state.rx:+d}, {state.ry:+d}',
                              triggers=f'{state.lt} / {state.rt}', battery=state.battery,
                              frames=self.frames, raw=state.raw)
            await client.start_notify(ch, callback)
            self.emit('gamepad_connected', text='Manette connectée ! ' + ('Sortie XInput active' if self.output else 'Surveillance seulement'))
            try:
                while not self.stop.is_set() and client.is_connected:
                    await asyncio.sleep(0.2)
            finally:
                if client.is_connected:
                    await client.stop_notify(ch)
                if self.output:
                    self.output.close()
                    self.output = None


def controller_entry(worker: ControllerWorker) -> None:
    try:
        asyncio.run(worker.run())
    except Exception as exc:
        worker.emit('gamepad_error', text=f'{type(exc).__name__} : {exc}')
    finally:
        worker.emit('gamepad_stopped', text='Manette déconnectée')


def read_dump(path: str | Path) -> dict:
    obj = json.loads(Path(path).read_text(encoding='utf-8'))
    if obj.get('format') != 'skylanders-bridge-trap-readonly-v1':
        raise ValueError('Ce fichier n’est pas un rapport NFC du Bridge V2')
    for k, v in obj['blocks'].items():
        if not (0 <= int(k) <= 63 and len(bytes.fromhex(v)) == 16):
            raise ValueError(f'Bloc invalide dans le rapport : {k}')
    return obj


def compare_dumps(a: dict, b: dict) -> list[str]:
    first = a['blocks']; second = b['blocks']
    result = []
    for key in sorted(set(first) | set(second), key=int):
        va, vb = first.get(key), second.get(key)
        if va != vb:
            result.append(f'Bloc {int(key):02d} : {va or "non lu"} → {vb or "non lu"}')
    return result
