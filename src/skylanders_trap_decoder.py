#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Skylanders Bridge V2.3: décodeur HORS LIGNE, LECTURE SEULE, des pièges Trap Team.

64 blocs de 16 octets, sauvegarde MIFARE Classic 1K.
Dérivation AES documentée par Brandon L. Wilson, implémentée par Dolphin/PortalSync.
Organisation des méchants d'après PortalSync (rhsts, GPL-2.0-or-later).
Ne contacte JAMAIS un portail ; n'écrit JAMAIS sur la puce.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    Cipher = algorithms = modes = None


VILLAINS = {
    1: 'Chompy Mage', 2: 'Dr. Krankcase', 3: 'Wolfgang',
    4: 'Chef Pepper Jack', 5: 'Nightshade', 6: 'Luminous',
    7: 'Golden Queen', 8: 'Dreamcatcher', 9: 'The Gulper', 10: 'Kaos',
    11: 'Cuckoo Clocker', 12: 'Buzzer Beak', 13: 'Shield Shredder',
    14: 'Cross Crow', 15: 'Chompy', 16: 'Brawl and Chain',
    17: 'Bomb Shell', 18: 'Masker Mind', 19: 'Chill Bill',
    20: 'Sheep Creep', 21: 'Shrednaught', 22: 'Chomp Chest',
    23: 'Broccoli Guy', 24: 'Rage Mage', 25: 'Lob Goblin',
    26: 'Bone Chompy', 27: 'Fisticuffs', 28: 'Trolling Thunder',
    29: 'Hood Sickle', 30: 'Bruiser Cruiser', 31: 'Brawlrus',
    32: 'Tussle Sprout', 33: 'Krankenstein', 34: 'Scrap Shooter',
    35: 'Slobber Trap', 36: 'Grinnade', 37: 'Bad Juju',
    38: 'Blaster-Tron', 39: 'Tae Kwon Crow', 40: 'Pain-Yatta',
    41: 'Smoke Scream', 42: 'Eye Five', 43: 'Grave Clobber',
    44: 'Threatpack', 45: 'Mab Lobs', 46: 'Eye Scream',
}
CONST = b' Copyright (C) 2010 Activision. All Rights Reserved. '


class TrapDecodeError(ValueError):
    pass


def crc16(data: bytes) -> int:
    v = 0xFFFF
    for b in data:
        v ^= b << 8
        for _ in range(8):
            v = ((v << 1) ^ (0x1021 if v & 0x8000 else 0)) & 0xFFFF
    return v


def reconstruct_bytes(report: dict) -> bytes:
    if report.get('format') != 'skylanders-bridge-trap-readonly-v1':
        raise TrapDecodeError('Format de sauvegarde inconnu.')
    blocks = report.get('blocks', {})
    if not isinstance(blocks, dict) or len(blocks) != 64 or set(blocks) != {str(i) for i in range(64)}:
        raise TrapDecodeError(f'Sauvegarde incomplète ({len(blocks)} blocs) : 64 blocs requis, sans remplacer les manquants par zéro.')
    try:
        records = [bytes.fromhex(blocks[str(i)]) for i in range(64)]
    except (ValueError, TypeError) as e:
        raise TrapDecodeError('Contenu hexadécimal incorrect.') from e
    if any(len(r) != 16 for r in records):
        raise TrapDecodeError('Chaque bloc doit faire exactement 16 octets.')
    image = b''.join(records)
    if report.get('sha256') and hashlib.sha256(image).hexdigest().lower() != report['sha256'].lower():
        raise TrapDecodeError('SHA256 incorrect : la sauvegarde a été modifiée ou corrompue.')
    return image


def decode_trap_bytes(image: bytes, expected_identity: tuple[int,int] | None = None) -> dict:
    if len(image) != 1024:
        raise TrapDecodeError('1024 octets requis pour lire le contenu du piège.')
    fid = int.from_bytes(image[16:18], 'little')
    variant = int.from_bytes(image[28:30], 'little')
    if not (210 <= fid <= 220):
        raise TrapDecodeError(f'Ce n’est pas un piège Trap Team (ID={fid}).')
    if expected_identity is not None and (fid, variant) != expected_identity:
        raise TrapDecodeError('Identité du piège différente de celle attendue : décodage bloqué.')
    expected_crc = int.from_bytes(image[30:32], 'little')
    computed_crc = crc16(image[:30])
    if expected_crc != computed_crc:
        raise TrapDecodeError(f'CRC d’en-tête incorrect : {expected_crc:04x} != {computed_crc:04x}.')
    if Cipher is None:
        raise TrapDecodeError('Installer cryptography : py -m pip install cryptography')
    data = bytearray(image)
    for index in range(8, 64):
        block = image[index*16:(index+1)*16]
        if index % 4 == 3 or not any(block):
            continue  # Remorques de secteurs et blocs entièrement vides : jamais chiffrés ici.
        key = hashlib.md5(image[:32] + bytes([index]) + CONST).digest()
        decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        data[index*16:(index+1)*16] = decryptor.update(block) + decryptor.finalize()
    older_base, newer_base = 0x80, 0x240
    ca, cb = data[older_base + 9], data[newer_base + 9]
    # La zone de sauvegarde la plus récente a le compteur suivant (modulo 256).
    active = newer_base if (ca + 1) & 0xFF == cb or not any(data[older_base:older_base+16]) else older_base
    def listing(base: int):
        count = int(data[base+1]);
        if count > 6:
            raise TrapDecodeError(f'Nombre de méchants incohérent ({count}) dans la zone 0x{base:03x}.')
        ids = [int(data[base+0x10+0x40*k]) for k in range(count)]
        return [{'id': i, 'name': VILLAINS.get(i, f'Méchant inconnu ({i})')} for i in ids]
    active_list = listing(active)
    # Zone inverse = sauvegarde redondante plus ancienne, dont la liste peut différer.
    other = 0x240 if active == 0x80 else 0x80
    history = listing(other) if any(data[other:other+16]) else []
    return {
        'character_id': fid, 'variant_id': variant,
        'header_crc_valid': True, 'active_zone': f'0x{active:03X}',
        'active_counter': data[active+9], 'previous_zone': f'0x{other:03X}',
        'previous_counter': data[other+9],
        'current_villain': active_list[0] if active_list else None,
        'villains_in_active_save': active_list,
        'villains_in_previous_save': history,
        'note': 'Le premier de la zone active est le méchant sélectionné. Les autres représentent un historique mémorisé.',
    }


def decode_trap_report(report: dict) -> dict:
    identity = report.get('identity') or {}
    expected = None
    if 'character_id' in identity and 'variant_id' in identity:
        expected = (int(identity['character_id']), int(identity['variant_id']))
    return decode_trap_bytes(reconstruct_bytes(report), expected)


def format_summary(result: dict) -> str:
    current = result.get('current_villain')
    lines = [f"PIÈGE : ID {result['character_id']} / variante {result['variant_id']}",
             f"MÉCHANT ACTUEL : {current['name'] if current else 'aucun'}",
             f"Enregistrés ({len(result['villains_in_active_save'])}) :"]
    for n, villain in enumerate(result['villains_in_active_save'], 1):
        lines.append(f"  {n}. {villain['name']} (ID {villain['id']})")
    previous = result['villains_in_previous_save']
    if previous:
        lines.append(f"Sauvegarde précédente : {previous[0]['name']} était sélectionné.")
    lines.append('Déchiffrement local uniquement : aucune écriture NFC.')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Afficher le méchant capturé depuis un fichier NFC complet (lecture seule)')
    parser.add_argument('file', help='trap_....json ou .bin de 1024 octets')
    args = parser.parse_args()
    f = Path(args.file)
    try:
        if f.suffix.lower() in ('.bin', '.sky'):
            result = decode_trap_bytes(f.read_bytes())
        else:
            result = decode_trap_report(json.loads(f.read_text(encoding='utf-8')))
        print(format_summary(result))
    except (TrapDecodeError, OSError, ValueError, KeyError) as exc:
        parser.exit(2, f'Impossible de décoder : {exc}\n')


if __name__ == '__main__':
    main()
