#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Skylanders Bluetooth Bridge V1.2 - Windows GUI and read-only NFC identification.

Tested against user-provided BLE status and Q response samples, not tested
on physical hardware by the author of this script.

Device communication: BLE notifications + one Q (NFC query) per figurine
placement, iff the user explicitly enables 'lecture automatique'. No NFC
write commands ('W') exist in this application. BLE write is used to send
read queries. This version DOES NOT connect to Cemu. Trap identification is experimental, opt-in.

Run: py -m pip install bleak
     py skylanders_bridge_v1_2.py
     py skylanders_bridge_v1_2.py --self-test
"""

from __future__ import annotations

import argparse
import asyncio
import json
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from skylanders_catalogue import Catalogue, load_catalog, download_catalog, import_readme
from skylanders_ble_coord import guarded_discover

READ_UUID = "533e1542-3abe-f33f-cd00-594e8b0a8ea3"
WRITE_UUID = "533e1543-3abe-f33f-cd00-594e8b0a8ea3"
PORTAL_NAME = "skylanders portal"
NFC_BLOCK_IDENTITY = 1
MIN_STABLE_SECONDS = 0.8
REMOVAL_GRACE_SECONDS = 0.7
QUERY_TIMEOUT_SECONDS = 7.0
RETRY_DELAY_SECONDS = 1.2

# Confirmed locally by physical tests: ID 462 -> Snap Shot, ID 470 -> Jawbreaker.
# Other IDs in this small, editable offline catalog from:
# https://github.com/Texthead1/Skylander-IDs
KNOWN_CHARACTERS: dict[int, str] = {
    0: "Whirlwind", 1: "Sonic Boom", 2: "Warnado", 3: "Lightning Rod",
    4: "Bash", 5: "Terrafin", 6: "Dino-Rang", 7: "Prism Break",
    8: "Sunburn", 9: "Eruptor", 10: "Ignitor", 11: "Flameslinger",
    12: "Zap", 13: "Wham-Shell", 14: "Gill Grunt", 15: "Slam Bam",
    16: "Spyro", 17: "Voodood", 18: "Double Trouble", 19: "Trigger Happy",
    20: "Drobot", 21: "Drill Sergeant", 22: "Boomer", 23: "Wrecking Ball",
    24: "Camo", 25: "Zook", 26: "Stealth Elf", 27: "Stump Smash",
    28: "Dark Spyro", 29: "Hex", 30: "Chop Chop", 31: "Ghost Roaster",
    32: "Cynder", 100: "Jet-Vac", 101: "Swarm", 102: "Crusher",
    103: "Flashwing", 104: "Hot Head", 105: "Hot Dog", 106: "Chill",
    107: "Thumpback", 108: "Pop Fizz", 109: "Ninjini", 110: "Bouncer",
    111: "Sprocket", 112: "Tree Rex", 113: "Shroomboom", 114: "Eye-Brawl",
    115: "Fright Rider",
    450: "Gusto", 451: "Thunderbolt", 452: "Fling Kong", 453: "Blades",
    454: "Wallop", 455: "Head Rush", 456: "Fist Bump", 457: "Rocky Roll",
    458: "Wildfire", 459: "Ka-Boom", 460: "Trail Blazer", 461: "Torch",
    462: "Snap Shot", 463: "Lob-Star", 464: "Flip Wreck", 465: "Echo",
    466: "Blastermind", 467: "Enigma", 468: "Deja Vu", 469: "Cobra Cadabra",
    470: "Jawbreaker", 471: "Gearshift", 472: "Chopper", 473: "Tread Head",
    474: "Bushwhack", 475: "Tuff Luck", 476: "Food Fight", 477: "High Five",
    478: "Krypt King", 479: "Short Cut", 480: "Bat Spin", 481: "Funny Bone",
    482: "Knight Light", 483: "Spotlight", 484: "Knight Mare", 485: "Blackout",
}
# Exact variant matches that we can name confidently; other variant values
# are shown explicitly, without claiming to know their marketing name.
KNOWN_VARIANTS: dict[tuple[int, int], str] = {
    (462, 12288): "Snap Shot",
    (462, 13314): "Dark Snap Shot",
    (470, 12288): "Jawbreaker",
    (470, 13315): "Legendary Jawbreaker",
    (113, 4096): "Shroomboom",
    (113, 4119): "Shroomboom (Metallic)",
    (113, 4614): "Shroomboom (LightCore)",
    (113, 14341): "Sure Shot Shroomboom",
}


# Trap ID/variant pairs from the community Skylander-IDs catalog.
# The BLE Q query on the *trap slot* has NOT yet been tested on this portal.
# The model (trap shape) is encoded in variant ID. Captured villain data
# is a separate question and is not interpreted by this release.
TRAP_ELEMENTS: dict[int, str] = {
    210: "Magie", 211: "Eau", 212: "Air", 213: "Mort-vivant",
    214: "Tech", 215: "Feu", 216: "Terre", 217: "Vie",
    218: "Ténèbres", 219: "Lumière", 220: "Kaos",
}
TRAP_NAMES: dict[tuple[int, int], str] = {
    (210, 12290): "Biter's Bane (Magie)",
    (210, 12296): "Sorcerous Skull (Magie)",
    (210, 12299): "Axe of Illusion (Magie)",
    (210, 12302): "Arcane Hourglass (Magie)",
    (210, 12306): "Spell Slapper (Magie)",
    (210, 12309): "Rune Rocket (Magie)",
    (211, 12289): "Tidal Tiki (Eau)",
    (211, 12290): "Wet Walter (Eau)",
    (211, 12294): "Flood Flask (Eau)",
    (211, 13318): "Legendary Flood Flask (Eau)",
    (211, 12295): "Soaking Staff (Eau)",
    (211, 12299): "Aqua Axe (Eau)",
    (211, 12310): "Frost Helm (Eau)",
    (212, 12291): "Breezy Bird (Air)",
    (212, 12294): "Drafty Decanter (Air)",
    (212, 12302): "Tempest Timer (Air)",
    (212, 12304): "Cloudy Cobra (Air)",
    (212, 12305): "Storm Warning (Air)",
    (212, 12312): "Cyclone Sabre (Air)",
    (213, 12292): "Spirit Sphere (Mort-vivant)",
    (213, 13316): "Legendary Spirit Sphere (Mort-vivant)",
    (213, 12296): "Spectral Skull (Mort-vivant)",
    (213, 13320): "Legendary Spectral Skull (Mort-vivant)",
    (213, 12299): "Haunted Hatchet (Mort-vivant)",
    (213, 12300): "Grim Gripper (Mort-vivant)",
    (213, 12304): "Spooky Snake (Mort-vivant)",
    (213, 12311): "Dream Piercer (Mort-vivant)",
    (214, 12289): "Tech Totem (Tech)",
    (214, 12295): "Automatic Angel (Tech)",
    (214, 12297): "Factory Flower (Tech)",
    (214, 12300): "Grabbing Gadget (Tech)",
    (214, 12310): "Makers Mana (Tech)",
    (214, 12314): "Topsy Techy (Tech)",
    (215, 12293): "Eternal Flame (Feu)",
    (215, 12297): "Fire Flower (Feu)",
    (215, 12305): "Scorching Stopper (Feu)",
    (215, 12306): "Searing Spinner (Feu)",
    (215, 12311): "Spark Speak (Feu)",
    (215, 12315): "Blazing Belch (Feu)",
    (216, 12291): "Rock Hawk (Terre)",
    (216, 12292): "Banded Boulder (Terre)",
    (216, 12298): "Slag Hammer (Terre)",
    (216, 12302): "Dust of Time (Terre)",
    (216, 12306): "Spinning Sandstorm (Terre)",
    (216, 12314): "Rubble Trouble (Terre)",
    (217, 12291): "Oak Eagle (Vie)",
    (217, 12293): "Emerald Energy (Vie)",
    (217, 12298): "Weed Whacker (Vie)",
    (217, 12304): "Seed Serpent (Vie)",
    (217, 12312): "Jade Blade (Vie)",
    (217, 12315): "Shrub Shrieker (Vie)",
    (218, 12308): "Shadow Spider (Ténèbres)",
    (218, 12312): "Dark Dagger (Ténèbres)",
    (218, 12314): "Ghastly Grimace (Ténèbres)",
    (219, 12303): "Heavenly Hawk (Lumière)",
    (219, 12309): "Shining Ship (Lumière)",
    (219, 12315): "Beam Scream (Lumière)",
    (220, 12318): "Kaos Trap",
    (220, 13343): "Ultimate Kaos Trap",
}


@dataclass(frozen=True)
class NfcResult:
    slot: int
    block: int
    character_id: int
    variant_id: int
    data_hex: str
    label: str
    kind: str = "Figurine"
    exact: bool = False


def status_codes(packet: bytes) -> list[int] | None:
    """Status 'S' + 4 little-endian state bytes (2 bits x 16 slots)."""
    if len(packet) < 5 or packet[0] != 0x53:
        return None
    word = int.from_bytes(packet[1:5], "little")
    return [(word >> (2 * slot)) & 3 for slot in range(16)]


def query_block_one(slot: int) -> bytes:
    """A SINGLE NFC READ request, in a 20-byte BLE frame (never a tag write)."""
    if not 0 <= slot <= 15:
        raise ValueError("Emplacement invalide")
    return bytes([0x51, 0x10 | slot, NFC_BLOCK_IDENTITY]) + bytes(17)


def parse_query_response(packet: bytes, expected_slot: int, catalogue: Catalogue | None = None) -> NfcResult:
    """Reject incorrect, stale or truncated replies before extracting NFC IDs."""
    if len(packet) < 19 or packet[0] != 0x51:
        raise ValueError("Trame Q incorrecte ou trop courte")
    slot = packet[1] & 0x0F
    if slot != expected_slot:
        raise ValueError(f"Réponse pour emplacement {slot}, attendu {expected_slot}")
    if not packet[1] & 0x10:
        raise ValueError("Réponse Q sans drapeau de lecture réussie")
    if packet[2] != NFC_BLOCK_IDENTITY:
        raise ValueError(f"Réponse Q du bloc {packet[2]}, attendu 1")
    block = packet[3:19]
    char_id = int.from_bytes(block[0:2], "little")
    variant_id = int.from_bytes(block[12:14], "little")
    if catalogue is not None:
        match, kind, exact = catalogue.identify(char_id, variant_id, expected_slot)
    elif expected_slot == 2:
        match = TRAP_NAMES.get((char_id, variant_id)) or f"Piège inconnu (ID {char_id}, variante {variant_id})"
        kind, exact = "Piège Traptanium", (char_id, variant_id) in TRAP_NAMES
    else:
        match = KNOWN_VARIANTS.get((char_id, variant_id))
        exact = bool(match)
        match = match or (f"{KNOWN_CHARACTERS[char_id]} (variante {variant_id})"
                           if char_id in KNOWN_CHARACTERS else f"Objet inconnu (ID {char_id}, variante {variant_id})")
        kind = "Figurine"
    return NfcResult(expected_slot, NFC_BLOCK_IDENTITY, char_id, variant_id,
                     block.hex(" "), match, kind, exact)



@dataclass
class Slot:
    since: float
    missing_since: float | None = None
    readings: int = 0
    attempted: bool = False
    result: NfcResult | None = None
    error: str | None = None
    attempts: int = 0
    retry_after: float = 0.0


class PortalWorker:
    """Runs all BLE operations on its own asyncio thread, never on Tk thread."""

    def __init__(self, events: queue.Queue, stop: threading.Event,
                 allow_reads: threading.Event, allow_trap_reads: threading.Event,
                 reread_requests: queue.Queue, catalogue: Catalogue):
        self.events = events
        self.catalogue = catalogue
        self.stop = stop
        self.allow_reads = allow_reads
        self.allow_trap_reads = allow_trap_reads
        self.reread_requests = reread_requests
        self.slots: dict[int, Slot] = {}
        self.pending: tuple[int, float] | None = None
        self.incoming: asyncio.Queue[bytes] = asyncio.Queue(maxsize=512)
        self.logfile = None
        self.log_path: Path | None = None
        self.last_status_raw: bytes | None = None
        self.status_samples = 0

    def emit(self, kind: str, **data: Any) -> None:
        self.events.put((kind, data))

    def log(self, category: str, **fields: Any) -> None:
        if self.logfile:
            self.logfile.write(json.dumps({
                "time": datetime.now().isoformat(timespec="milliseconds"),
                "category": category,
                **fields,
            }, ensure_ascii=False) + "\n")
            self.logfile.flush()

    def receive(self, _characteristic: Any, value: bytearray) -> None:
        # Bleak executes Python callbacks on the asyncio event loop.
        try:
            self.incoming.put_nowait(bytes(value))
        except asyncio.QueueFull:
            self.emit("message", text="Trop de notifications : certaines ont été ignorées")

    def process_status(self, payload: bytes) -> None:
        states = status_codes(payload)
        if states is None:
            return
        self.status_samples += 1
        now = time.monotonic()
        # Full raw byte packets retained for debugging detection fluctuations.
        if payload[1:5] != self.last_status_raw:
            self.log("status", hex=payload.hex(" "), states=states)
            self.last_status_raw = payload[1:5]
        for idx, state in enumerate(states):
            here = state in (1, 3)
            current = self.slots.get(idx)
            if here:
                if current is None:
                    self.slots[idx] = Slot(since=now, readings=1)
                    self.emit("slot", index=idx, present=True, kind_name="Piège (emplacement 2)" if idx == 2 else "Figurine", detail="Détecté, stabilisation…")
                    self.emit("message", text=f"Objet détecté à l'emplacement {idx}")
                else:
                    current.missing_since = None
                    current.readings += 1
            elif current is not None and current.missing_since is None:
                current.missing_since = now

    def process_q(self, payload: bytes) -> None:
        self.log("query_reply", hex=payload.hex(" "), size=len(payload), pending=self.pending[0] if self.pending else None)
        if self.pending is None:
            self.emit("message", text="Réponse Q hors requête (voir le journal).")
            return
        slot, _sent = self.pending
        if len(payload) < 3 or (payload[1] & 0x0F) != slot or payload[2] != NFC_BLOCK_IDENTITY:
            self.log("query_unmatched", expected_slot=slot, hex=payload.hex(" "))
            return
        self.pending = None
        current = self.slots.get(slot)
        if current is None:
            self.emit("message", text=f"Réponse Q emplacement {slot}, mais aucun objet suivi : voir journal.")
            return
        # V1.1 refused valid Q when status briefly reported a removed tag.
        # Keep the response within the same grace period, but never resurrect a
        # slot removed long ago (old delayed answer).
        if current.missing_since is not None and time.monotonic() - current.missing_since > REMOVAL_GRACE_SECONDS:
            self.log("query_reply_after_removal", slot=slot, hex=payload.hex(" "))
            return
        try:
            result = parse_query_response(payload, slot, self.catalogue)
            current.result = result
            current.error = None
            self.emit("slot", index=slot, present=True,
                      kind_name=result.kind,
                      detail=result.label, char_id=result.character_id, variant_id=result.variant_id)
            self.emit("message", text=f"Emplacement {slot} : {result.label} — ID {result.character_id}, variante {result.variant_id}")
            self.log("identified", slot=slot, char_id=result.character_id,
                     variant=result.variant_id, label=result.label, exact=result.exact, kind=result.kind)
        except ValueError as exc:
            current.error = str(exc)
            self.log("query_parse_error", slot=slot, error=str(exc), hex=payload.hex(" "))
            self.emit("slot", index=slot, present=True, kind_name="Piège" if slot == 2 else "Objet", detail=f"Lecture : {exc}")
            self.emit("message", text=f"Lecture emplacement {slot} : {exc}")

    async def tick(self, client: Any, write_char: Any) -> None:
        now = time.monotonic()
        for index, state in list(self.slots.items()):
            if state.missing_since is not None and now - state.missing_since >= REMOVAL_GRACE_SECONDS:
                del self.slots[index]
                self.emit("slot", index=index, present=False)
                self.emit("message", text=f"Objet retiré de l'emplacement {index}")
                if self.pending and self.pending[0] == index:
                    # Keep pending until answer or timeout so a delayed reply cannot
                    # be mistaken for a subsequent request for the same slot.
                    pass
        if self.pending is not None:
            slot, started = self.pending
            if now - started > QUERY_TIMEOUT_SECONDS:
                state = self.slots.get(slot)
                if state is not None:
                    if state.attempts == 1 and state.missing_since is None and slot != 2:
                        state.attempted = False
                        state.retry_after = now + RETRY_DELAY_SECONDS
                        self.emit("message", text=f"Emplacement {slot} : délai dépassé, UN second essai dans {RETRY_DELAY_SECONDS}s.")
                    else:
                        state.error = "Aucune réponse NFC (sélectionne l’objet puis clique sur Relire)"
                        self.emit("slot", index=slot, present=True, kind_name="Piège" if slot == 2 else "Objet", detail=state.error)
                        self.emit("message", text=f"Emplacement {slot} : pas de réponse après {state.attempts} essai(s).")
                self.log("query_timeout", slot=slot, attempts=state.attempts if state else None)
                self.pending = None
            return
        # Manual re-read requests do not trigger NFC queries if the
        # relevant permission is disabled; neither does an absent slot.
        while True:
            try:
                requested_slot = self.reread_requests.get_nowait()
            except queue.Empty:
                break
            allowed = self.allow_trap_reads.is_set() if requested_slot == 2 else self.allow_reads.is_set()
            state = self.slots.get(requested_slot)
            if not allowed:
                self.emit("message", text="Coche d'abord la lecture NFC correspondante.")
            elif state is None or state.missing_since is not None:
                self.emit("message", text=f"Emplacement {requested_slot} absent : rien à relire.")
            elif self.pending is not None:
                self.emit("message", text="Une requête NFC est déjà en cours ; réessaie ensuite.")
            else:
                state.attempted = False
                state.attempts = 0
                state.retry_after = 0.0
                state.error = None
                state.result = None
                state.readings = max(state.readings, 2)
                state.since = now - MIN_STABLE_SECONDS
                self.emit("message", text=f"Nouvelle lecture manuelle demandée pour l'emplacement {requested_slot}.")
        if not (self.allow_reads.is_set() or self.allow_trap_reads.is_set()):
            return
        for idx, state in sorted(self.slots.items()):
            if idx == 2 and not self.allow_trap_reads.is_set():
                continue
            if idx != 2 and not self.allow_reads.is_set():
                continue
            if (state.missing_since is None and not state.attempted and state.readings >= 2
                    and now - state.since >= MIN_STABLE_SECONDS and now >= state.retry_after):
                state.attempted = True
                state.attempts += 1
                request = query_block_one(idx)
                self.pending = (idx, time.monotonic())
                self.emit("message", text=f"Lecture NFC de {'piège' if idx == 2 else 'objet'}, emplacement {idx} (bloc 1, essai {state.attempts})…")
                self.log("query", slot=idx, attempt=state.attempts, frame=request.hex(" "))
                try:
                    # A BLE characteristic write sends a READ request to the portal.
                    # It does NOT write to the NFC tag; no W command exists here.
                    await client.write_gatt_char(write_char, request, response=True)
                except Exception as exc:
                    self.pending = None
                    state.error = f"Erreur de lecture : {type(exc).__name__}: {exc}"
                    self.log("query_ble_error", slot=idx, error=str(exc))
                    self.emit("slot", index=idx, present=True, kind_name="Piège" if idx == 2 else "Figurine", detail=state.error)
                    self.emit("message", text=f"Erreur BLE lors de Q : {exc}")
                return

    async def run(self) -> None:
        from bleak import BleakClient, BleakScanner  # optional until user connects
        logdir = Path(__file__).resolve().parent / "skylanders_logs"
        try:
            logdir.mkdir(exist_ok=True)
        except OSError:
            logdir = Path.home() / "skylanders_logs"
            logdir.mkdir(exist_ok=True)
        self.log_path = logdir / f"bridge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        try:
            with self.log_path.open("w", encoding="utf-8") as logfile:
                self.logfile = logfile
                self.emit("message", text="Recherche de Skylanders Portal (15 secondes)…")
                found = await guarded_discover(BleakScanner, timeout=15, return_adv=True)
                matches = []
                for dev, adv in found.values():
                    name = (adv.local_name or dev.name or "").lower().strip()
                    if PORTAL_NAME in name:
                        matches.append((adv.rssi if adv.rssi is not None else -999, dev))
                if self.stop.is_set():
                    return
                if not matches:
                    raise RuntimeError("Aucun Skylanders Portal trouvé. Vérifie les piles et le Bluetooth de Windows.")
                matches.sort(key=lambda it: it[0], reverse=True)
                device = matches[0][1]
                self.emit("message", text="Portail trouvé, connexion en cours…")
                async with BleakClient(device, timeout=25) as client:
                    read_char = client.services.get_characteristic(READ_UUID)
                    write_char = client.services.get_characteristic(WRITE_UUID)
                    if read_char is None or "notify" not in read_char.properties:
                        raise RuntimeError("Canal de notifications BLE introuvable sur ce portail.")
                    if write_char is None or "write" not in write_char.properties:
                        raise RuntimeError("Canal BLE d'écriture avec réponse introuvable. Aucun Q envoyé.")
                    await client.start_notify(read_char, self.receive)
                    self.emit("connected")
                    self.emit("message", text="Portail connecté. Pose une figurine sur le socle.")
                    try:
                        while not self.stop.is_set() and client.is_connected:
                            try:
                                payload = await asyncio.wait_for(self.incoming.get(), timeout=0.15)
                                if payload[:1] == b"S":
                                    self.process_status(payload)
                                elif payload[:1] == b"Q":
                                    self.process_q(payload)
                                else:
                                    self.log("other_packet", hex=payload.hex(" "))
                            except asyncio.TimeoutError:
                                pass
                            await self.tick(client, write_char)
                        if not client.is_connected and not self.stop.is_set():
                            self.emit("message", text="Connexion Bluetooth perdue.")
                    finally:
                        if client.is_connected:
                            await client.stop_notify(read_char)
        finally:
            self.logfile = None
            self.emit("stopped", log_path=str(self.log_path) if self.log_path else "")


def worker_entry(worker: PortalWorker) -> None:
    try:
        asyncio.run(worker.run())
    except Exception as exc:
        worker.emit("error", text=f"{type(exc).__name__} : {exc}")


class BridgeApp:
    BG = "#0a1423"
    PANEL = "#152438"
    PANEL2 = "#1b3047"
    TEXT = "#eef6ff"
    MUTED = "#a7b8cc"
    ACCENT = "#4eb8ff"
    GREEN = "#67e8ae"
    ORANGE = "#f4c56c"

    def __init__(self, root: Any) -> None:
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.root = root
        self.root.title("Skylanders Bluetooth Bridge V1.2")
        self.root.geometry("1050x800")
        self.root.minsize(850, 710)
        self.root.configure(bg=self.BG)
        self.events: queue.Queue = queue.Queue()
        self.catalogue = Catalogue(load_catalog())
        self.stop = threading.Event()
        self.allow_reads = threading.Event()
        self.thread: threading.Thread | None = None
        self.running = False
        self.demo_mode = False
        self.demo_handles: list[str] = []
        self.row_ids: dict[int, str] = {}
        self.read_var = tk.BooleanVar(value=False)  # explicit opt-in
        self.trap_var = tk.BooleanVar(value=False)  # separate experimental opt-in
        self.allow_trap_reads = threading.Event()
        self.reread_requests = queue.Queue()
        self.connection_label = tk.StringVar(value="Déconnecté")
        self.hint = tk.StringVar(value="Branche le Bluetooth de Windows, allume ton portail et clique sur Connecter.")
        self.catalog_label = tk.StringVar(value="Catalogue local : chargement…")
        self._layout(ttk)
        self.root.after(90, self.poll)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.append("V1.2 : lecture NFC, catalogue local, diagnostics. Pièges expérimentaux. Pas de connexion Cemu.")
        self.update_catalog_label()
        if not self.catalogue.complete:
            self.refresh_catalog(silent=True)

    def update_catalog_label(self) -> None:
        completeness = "COMPLET (GitHub)" if self.catalogue.complete else "PARTIEL (secours)"
        self.catalog_label.set(f"Catalogue local : {len(self.catalogue.rows)} entrées • {completeness}")

    def refresh_catalog(self, silent: bool = False) -> None:
        if not silent:
            self.append("Téléchargement de la base Skylander-IDs en cours…")
        def job():
            try:
                download_catalog()
                self.events.put(("catalog_ready", {}))
            except Exception as exc:
                self.events.put(("catalog_error", {'text': f"Mise à jour impossible ({exc}). Utilisation du cache local."}))
        threading.Thread(target=job, daemon=True).start()

    def import_catalog_file(self) -> None:
        from tkinter import filedialog, messagebox
        filename = filedialog.askopenfilename(parent=self.root, title="Choisir README.md de Skylander-IDs",
                                               filetypes=[("Markdown", "*.md"), ("Tous", "*.*")])
        if not filename:
            return
        try:
            count = import_readme(filename)
            self.catalogue = Catalogue(load_catalog())
            self.update_catalog_label()
            self.append(f"Catalogue importé depuis le fichier local : {count} entrées.")
        except Exception as exc:
            messagebox.showerror("Import impossible", str(exc), parent=self.root)

    def show_catalogue(self) -> None:
        tk = self.tk
        from tkinter import ttk
        popup = tk.Toplevel(self.root)
        popup.title("Catalogue Skylanders local (recherche)")
        popup.geometry("950x590")
        popup.configure(bg=self.BG)
        header = tk.Frame(popup, bg=self.BG)
        header.pack(fill="x", padx=14, pady=12)
        tk.Label(header, text=f"{len(self.catalogue.rows)} références — source : Skylander-IDs",
                 bg=self.BG, fg=self.TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        query = tk.StringVar()
        search = tk.Entry(header, textvariable=query, font=("Segoe UI", 11))
        search.pack(fill="x", pady=8)
        search.focus_set()
        cols = ("name", "type", "character_id", "variant_id", "section")
        table = ttk.Treeview(popup, columns=cols, show="headings", height=20)
        for col, label, width in (("name", "Nom", 280), ("type", "Type", 160),
                                  ("character_id", "ID", 65), ("variant_id", "Variante", 85),
                                  ("section", "Collection", 205)):
            table.heading(col, text=label)
            table.column(col, width=width, anchor="w")
        scroller = ttk.Scrollbar(popup, command=table.yview)
        table.configure(yscrollcommand=scroller.set)
        scroller.pack(side="right", fill="y")
        table.pack(fill="both", expand=True, padx=(14, 0), pady=(0, 14))
        def render(*_):
            text = query.get().strip().casefold()
            table.delete(*table.get_children())
            for r in self.catalogue.rows:
                values = (r['name'], r['type'], r['character_id'],
                          '—' if r['variant_id'] == -1 else r['variant_id'], r['section'])
                if text and text not in ' '.join(map(str, values)).casefold():
                    continue
                table.insert('', 'end', values=values)
        query.trace_add('write', render)
        render()

    def _layout(self, ttk: Any) -> None:
        tk = self.tk
        wrapper = tk.Frame(self.root, bg=self.BG)
        wrapper.pack(fill="both", expand=True, padx=24, pady=18)

        tk.Label(wrapper, text="SKYLANDERS  /  BLUETOOTH BRIDGE", bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(wrapper, text="Ton portail d'enfance, sur Windows.", bg=self.BG, fg=self.TEXT,
                 font=("Segoe UI", 22, "bold")).pack(anchor="w", pady=(3, 5))
        tk.Label(wrapper, text="V1.2 · Figurines et objets · Catalogue hors ligne · Pièges expérimentaux",
                 bg=self.BG, fg=self.MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 12))
        catalogbar = tk.Frame(wrapper, bg=self.PANEL, padx=12, pady=7)
        catalogbar.pack(fill="x", pady=(0, 10))
        tk.Label(catalogbar, textvariable=self.catalog_label, bg=self.PANEL, fg=self.TEXT,
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Button(catalogbar, text="Voir le catalogue", command=self.show_catalogue,
                  bg=self.PANEL2, fg=self.TEXT, relief="flat").pack(side="right", padx=3)
        tk.Button(catalogbar, text="Importer README.md", command=self.import_catalog_file,
                  bg=self.PANEL2, fg=self.TEXT, relief="flat").pack(side="right", padx=3)
        tk.Button(catalogbar, text="MàJ GitHub", command=self.refresh_catalog,
                  bg=self.PANEL2, fg=self.TEXT, relief="flat").pack(side="right", padx=3)

        controls = tk.Frame(wrapper, bg=self.PANEL, padx=16, pady=14)
        controls.pack(fill="x", pady=(0, 12))
        self.status_dot = tk.Label(controls, text="●", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 19))
        self.status_dot.pack(side="left")
        tk.Label(controls, textvariable=self.connection_label, bg=self.PANEL, fg=self.TEXT,
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=(8, 16))
        self.connect_button = tk.Button(controls, text="Connecter le portail", command=self.start,
                 bg=self.ACCENT, fg="#071525", activebackground="#8bd3ff", relief="flat", padx=13, pady=8,
                 font=("Segoe UI", 10, "bold"), cursor="hand2")
        self.connect_button.pack(side="left", padx=(0, 7))
        self.disconnect_button = tk.Button(controls, text="Déconnecter", command=self.disconnect,
                 bg=self.PANEL2, fg=self.TEXT, activebackground="#304b64", relief="flat", padx=12, pady=8,
                 font=("Segoe UI", 10), cursor="hand2", state="disabled")
        self.disconnect_button.pack(side="left", padx=(0, 7))
        tk.Button(controls, text="Mode démo", command=self.run_demo,
                 bg=self.PANEL2, fg=self.TEXT, relief="flat", padx=12, pady=8,
                 font=("Segoe UI", 10), cursor="hand2").pack(side="right")

        opt = tk.Frame(wrapper, bg=self.PANEL, padx=16, pady=8)
        opt.pack(fill="x", pady=(0, 14))
        tk.Checkbutton(opt, text="Autoriser la lecture NFC automatique (commande Q, 1 lecture par pose)",
                       variable=self.read_var, command=self.toggle_read, bg=self.PANEL, fg=self.TEXT,
                       selectcolor=self.BG, activebackground=self.PANEL, activeforeground=self.TEXT,
                       font=("Segoe UI", 10)).pack(anchor="w")
        tk.Checkbutton(opt, text="Essayer la lecture NFC des pièges (EXPÉRIMENTAL, commande Q seulement)",
                       variable=self.trap_var, command=self.toggle_trap_read, bg=self.PANEL, fg=self.TEXT,
                       selectcolor=self.BG, activebackground=self.PANEL, activeforeground=self.TEXT,
                       font=("Segoe UI", 10)).pack(anchor="w", pady=(6, 0))
        tk.Label(opt, text="Ces deux modes sont désactivés au départ. Le piège n'est lu qu'avec ton accord explicite.",
                 bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=24, pady=(3, 0))
        tk.Button(opt, text="Relire la sélection", command=self.reread_selected, bg=self.PANEL2,
                  fg=self.TEXT, relief="flat", padx=12, pady=6,
                  font=("Segoe UI", 10)).pack(anchor="e", pady=(4, 0))

        tk.Label(wrapper, textvariable=self.hint, bg=self.BG, fg=self.ORANGE,
                 font=("Segoe UI", 10), wraplength=840).pack(anchor="w", pady=(0, 10))
        tk.Label(wrapper, text="OBJETS SUR LE PORTAIL", bg=self.BG, fg=self.MUTED,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 7))

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Bridge.Treeview", background=self.PANEL, fieldbackground=self.PANEL,
                        foreground=self.TEXT, rowheight=34, borderwidth=0, font=("Segoe UI", 10))
        style.configure("Bridge.Treeview.Heading", background=self.PANEL2, foreground=self.TEXT,
                        font=("Segoe UI", 10, "bold"), relief="flat")
        style.map("Bridge.Treeview", background=[("selected", "#204b6c")], foreground=[("selected", "white")])
        table = tk.Frame(wrapper, bg=self.PANEL)
        table.pack(fill="x")
        self.tree = ttk.Treeview(table, columns=("slot", "type", "name", "id", "variante"),
                                 show="headings", height=3, style="Bridge.Treeview", selectmode="browse")
        for key, title, width in (("slot", "N°", 45), ("type", "Type", 130),
                                  ("name", "Personnage / état", 420), ("id", "ID", 75),
                                  ("variante", "Variante", 95)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=35, anchor="w", stretch=(key == "name"))
        table_scroll = tk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=table_scroll.set)
        table_scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="x", expand=True, padx=2, pady=2)

        log_top = tk.Frame(wrapper, bg=self.BG)
        log_top.pack(fill="x", pady=(10, 5))
        tk.Label(log_top, text="ACTIVITÉ", bg=self.BG, fg=self.MUTED,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Button(log_top, text="Effacer l'affichage", command=self.clear_log,
                  bg=self.PANEL2, fg=self.TEXT, relief="flat", padx=10, pady=4,
                  font=("Segoe UI", 9)).pack(side="right")
        tk.Label(wrapper, text="Ce programme ne se connecte pas encore à Cemu.",
                 bg=self.BG, fg=self.MUTED, font=("Segoe UI", 9)).pack(side="bottom", anchor="w", pady=(8, 0))
        log_frame = tk.Frame(wrapper, bg=self.PANEL)
        log_frame.pack(fill="both", expand=True)
        scrollbar = tk.Scrollbar(log_frame)
        scrollbar.pack(side="right", fill="y")
        self.log_box = tk.Text(log_frame, bg=self.PANEL, fg=self.TEXT, insertbackground=self.TEXT,
                               selectbackground="#2c5e7d", font=("Consolas", 10), wrap="word",
                               borderwidth=0, padx=14, pady=10, state="disabled", yscrollcommand=scrollbar.set)
        self.log_box.pack(fill="both", expand=True)
        scrollbar.config(command=self.log_box.yview)


    def append(self, line: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {line}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def toggle_read(self) -> None:
        if self.read_var.get():
            self.allow_reads.set()
            self.append("Lecture NFC Q autorisée. Une lecture du bloc 1 par nouvelle figurine.")
        else:
            self.allow_reads.clear()
            self.append("Lecture NFC désactivée : écoute des présences uniquement.")

    def toggle_trap_read(self) -> None:
        if self.trap_var.get():
            from tkinter import messagebox
            confirmed = messagebox.askyesno(
                "Lecture des pièges (expérimental)",
                "Le portail n'a encore jamais été testé avec une commande Q sur le "
                "piège (emplacement 2). La requête est une lecture NFC, sans commande W. "
                "Souhaites-tu autoriser UNE tentative par pose de piège ?",
                parent=self.root,
            )
            if not confirmed:
                self.trap_var.set(False)
                self.allow_trap_reads.clear()
                return
            self.allow_trap_reads.set()
            self.append("Lecture expérimentale des pièges activée (Q, bloc 1, une tentative par pose).")
        else:
            self.allow_trap_reads.clear()
            self.append("Lecture des pièges désactivée.")

    def reread_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            self.append("Sélectionne d'abord un objet dans le tableau.")
            return
        values = self.tree.item(selected[0], "values")
        try:
            index = int(values[0])
        except (IndexError, ValueError):
            self.append("Impossible de déterminer l'emplacement sélectionné.")
            return
        if not self.running:
            self.append("Connecte le portail pour relancer une lecture.")
            return
        if index == 2 and not self.allow_trap_reads.is_set():
            self.append("Coche d'abord la lecture expérimentale des pièges.")
            return
        if index != 2 and not self.allow_reads.is_set():
            self.append("Coche d'abord la lecture NFC automatique des figurines.")
            return
        self.reread_requests.put(index)
        self.append(f"Demande de relecture de l'emplacement {index} envoyée au programme.")

    def update_buttons(self) -> None:
        self.connect_button.configure(state="disabled" if self.running else "normal")
        self.disconnect_button.configure(state="normal" if self.running else "disabled")

    def clear_objects(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.row_ids.clear()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.cancel_demo()
        self.clear_objects()
        self.stop = threading.Event()
        self.allow_reads.set() if self.read_var.get() else self.allow_reads.clear()
        self.allow_trap_reads.set() if self.trap_var.get() else self.allow_trap_reads.clear()
        self.reread_requests = queue.Queue()
        self.running = True
        self.demo_mode = False
        self.update_buttons()
        self.connection_label.set("Recherche...")
        self.status_dot.configure(fg=self.ORANGE)
        self.hint.set("Recherche BLE en cours. Garde le portail allumé et proche du PC.")
        worker = PortalWorker(self.events, self.stop, self.allow_reads, self.allow_trap_reads, self.reread_requests, self.catalogue)
        self.thread = threading.Thread(target=worker_entry, args=(worker,), daemon=True)
        self.thread.start()

    def disconnect(self) -> None:
        self.stop.set()
        self.append("Déconnexion demandée…")

    def cancel_demo(self) -> None:
        for handle in self.demo_handles:
            self.root.after_cancel(handle)
        self.demo_handles.clear()
        self.demo_mode = False

    def run_demo(self) -> None:
        if self.running:
            self.append("Déconnecte le portail avant de lancer la démo.")
            return
        self.cancel_demo()
        self.clear_objects()
        self.demo_mode = True
        self.connection_label.set("Démonstration (sans Bluetooth)")
        self.status_dot.configure(fg=self.ORANGE)
        self.hint.set("Simulation avec les deux réponses NFC que tu as obtenues sur ton vrai portail.")
        self.append("DÉMO : données enregistrées de Jawbreaker et Snap Shot, sans connexion réelle.")
        jaw = bytes.fromhex("51 10 01 d6 01 00 00 3d 2a 16 dd 8f de 00 00 00 30 af 9e 00")
        snap = bytes.fromhex("51 10 01 ce 01 00 00 c7 bc b1 e7 14 ac 00 00 00 30 45 d6 00")
        self.demo_handles.append(self.root.after(800, lambda: self.on_event("slot", index=0, present=True, kind_name="Figurine", detail="Détecté…")))
        self.demo_handles.append(self.root.after(1700, lambda: self.on_event("slot", index=0, present=True, kind_name="Figurine", detail=parse_query_response(jaw, 0).label, char_id=470, variant_id=12288)))
        self.demo_handles.append(self.root.after(4300, lambda: self.on_event("slot", index=0, present=False)))
        self.demo_handles.append(self.root.after(5100, lambda: self.on_event("slot", index=0, present=True, kind_name="Figurine", detail=parse_query_response(snap, 0).label, char_id=462, variant_id=12288)))
        self.demo_handles.append(self.root.after(8600, lambda: self.on_event("slot", index=2, present=True, kind_name="Piège (emplacement 2)", detail="Piège détecté · identité non lue")))
        self.demo_handles.append(self.root.after(11000, self.demo_finished))

    def demo_finished(self) -> None:
        self.demo_handles.clear()
        self.append("Démonstration terminée. Clique sur Connecter le portail pour la vraie expérience.")

    def on_event(self, event: str, **data: Any) -> None:
        if event == "connected":
            self.connection_label.set("Portail connecté")
            self.status_dot.configure(fg=self.GREEN)
            self.hint.set("Pose Jawbreaker, Snap Shot ou une autre figurine. Retire-la pour scanner la suivante.")
        elif event == "stopped":
            self.running = False
            self.update_buttons()
            self.connection_label.set("Déconnecté")
            self.status_dot.configure(fg=self.MUTED)
            self.hint.set("Pour recommencer, allume le portail et clique sur Connecter.")
            if data.get("log_path"):
                self.append("Journal : " + data["log_path"])
        elif event == "error":
            self.append("ERREUR : " + data["text"])
            self.hint.set("Vérifie la connexion BLE. Le message d'erreur est dans l'activité.")
        elif event == "message":
            self.append(data["text"])
        elif event == "catalog_ready":
            self.catalogue = Catalogue(load_catalog())
            self.update_catalog_label()
            self.append(f"Catalogue mis à jour : {len(self.catalogue.rows)} entrées. Reconnecte le portail pour l'utiliser.")
        elif event == "catalog_error":
            self.append("Catalogue : " + data['text'])
        elif event == "slot":
            index = data["index"]
            if data.get("present"):
                values = (str(index), data.get("kind_name", "Figurine"),
                          data.get("detail", "Détecté"),
                          str(data.get("char_id", "—")), str(data.get("variant_id", "—")))
                if index in self.row_ids:
                    self.tree.item(self.row_ids[index], values=values)
                else:
                    iid = self.tree.insert("", "end", values=values)
                    self.row_ids[index] = iid
            elif index in self.row_ids:
                self.tree.delete(self.row_ids.pop(index))

    def poll(self) -> None:
        try:
            for _ in range(120):
                event, values = self.events.get_nowait()
                self.on_event(event, **values)
        except queue.Empty:
            pass
        self.root.after(90, self.poll)

    def close(self) -> None:
        self.cancel_demo()
        self.stop.set()
        self.root.destroy()


def self_test() -> None:
    """Offline regression tests based on actual portal measurements."""
    assert status_codes(bytes.fromhex("53 00 00 00 00")) == [0] * 16
    assert status_codes(bytes.fromhex("53 03 00 00 00"))[:3] == [3, 0, 0]
    assert status_codes(bytes.fromhex("53 05 00 00 00"))[:3] == [1, 1, 0]
    assert status_codes(bytes.fromhex("53 31 00 00 00"))[:3] == [1, 0, 3]
    assert status_codes(bytes.fromhex("53 12 00 00 00"))[:3] == [2, 0, 1]
    assert query_block_one(0) == bytes.fromhex("51 10 01") + bytes(17)
    assert query_block_one(1) == bytes.fromhex("51 11 01") + bytes(17)
    jaw = bytes.fromhex("51 10 01 d6 01 00 00 3d 2a 16 dd 8f de 00 00 00 30 af 9e 00")
    snap = bytes.fromhex("51 10 01 ce 01 00 00 c7 bc b1 e7 14 ac 00 00 00 30 45 d6 00")
    a = parse_query_response(jaw, 0)
    b = parse_query_response(snap, 0)
    assert (a.character_id, a.variant_id, a.label) == (470, 12288, "Jawbreaker")
    assert (b.character_id, b.variant_id, b.label) == (462, 12288, "Snap Shot")
    # Synthetic fixtures for variants and trap parsing: no real trap read yet.
    for variant, label in ((4096, "Shroomboom"), (4119, "Shroomboom (Metallic)"),
                           (4614, "Shroomboom (LightCore)"),
                           (14341, "Sure Shot Shroomboom")):
        block = bytearray(16)
        block[0:2] = (113).to_bytes(2, "little")
        block[12:14] = variant.to_bytes(2, "little")
        resp = b"\x51\x10\x01" + block
        assert parse_query_response(resp, 0).label == label
    block = bytearray(16)
    block[0:2] = (211).to_bytes(2, "little")
    block[12:14] = (12289).to_bytes(2, "little")
    assert parse_query_response(b"\x51\x12\x01" + block, 2).label == "Tidal Tiki (Eau)"
    for incorrect in (jaw[:8], bytes([0x51, 0x11]) + jaw[2:], bytes([0x51, 0x10, 0x02]) + jaw[3:]):
        try:
            parse_query_response(incorrect, 0)
        except ValueError:
            pass
        else:
            raise AssertionError("La validation des réponses Q n'a pas refusé une trame invalide")
    test_catalog = Catalogue(load_catalog())
    assert test_catalog.identify(470, 12288)[0] == "Jawbreaker"
    assert test_catalog.identify(462, 12288)[0] == "Snap Shot"
    assert test_catalog.identify(208, 4614)[0] == "Dragonfire Cannon"
    assert test_catalog.identify(113, 4096)[0] == "Shroomboom"
    from skylanders_catalogue import parse_readme
    fixture = "### Toys For Bob Items/Traps\nSkylander | CharacterID | VariantID\n---|---|---\nDragonfire Cannon | 208 | 4614\nTidal Tiki | 211 | 12289\n"
    parsed = parse_readme(fixture)
    assert len(parsed) == 2 and parsed[1]['type'] == "Piège Traptanium"
    assert test_catalog.identify(123456, 345)[2] is False
    assert parse_query_response(jaw, 0, test_catalog).label == "Jawbreaker"
    assert parse_query_response(snap, 0, test_catalog).label == "Snap Shot"
    print("OK : états, Q, Jawbreaker, Snap Shot, Shroomboom, Dragonfire Cannon, piège simulé, catalogue et réponses invalides.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Skylanders Bluetooth Bridge V1.2 pour Windows")
    parser.add_argument("--self-test", action="store_true", help="Tests sans Bluetooth ni fenêtre")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    import tkinter as tk
    root = tk.Tk()
    BridgeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
