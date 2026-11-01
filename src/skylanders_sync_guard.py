#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Skylanders Bridge SafeSync: immutable local snapshots and NFC change plans.

IMPORTANT: No BLE stack, no NFC commands, NO physical write functions.
Every proposal is a dry-run for human inspection, never a validated write recipe.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from skylanders_cemu_bridge import verified_image, identity_from_data

ROOT = Path(__file__).resolve().parent
SAFE_DIR = ROOT / 'safesync'
ORIGINAL_DIR = SAFE_DIR / 'reference_snapshots'
PLAN_DIR = SAFE_DIR / 'change_reports'
STATE_PATH = SAFE_DIR / 'snapshots_index.json'
TRAILERS = frozenset(range(3, 64, 4))

class SafetyError(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_image(data: bytes, expected: tuple[int, int] | None = None) -> tuple[int, int]:
    if len(data) != 1024:
        raise SafetyError('Image NFC incomplète : 1024 octets requis.')
    try:
        verified_image({i: data[i*16:(i+1)*16] for i in range(64)}, expected)
    except Exception as exc:
        raise SafetyError(str(exc)) from exc
    return identity_from_data(data)


def atomic_write_new(path: Path, data: bytes) -> bool:
    """Create once; never overwrite a reference snapshot (even on races)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        return True
    except FileExistsError:
        return False


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + '.' + secrets.token_hex(6) + '.tmp')
    try:
        with tmp.open('x', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def load_state() -> dict:
    try:
        raw = json.loads(STATE_PATH.read_text(encoding='utf-8'))
        return raw if isinstance(raw, dict) and raw.get('format') == 'skylanders-safesync-v1' else new_state()
    except (OSError, ValueError):
        return new_state()


def new_state() -> dict:
    return {'format': 'skylanders-safesync-v1', 'objects': {}}


def register_reference(fingerprint: str, image: bytes, *, provenance: str, name: str = '') -> Path:
    """Save a reference snapshot before any Cemu mutation.
    If initial data came from a previous PC cache we say so; never claim it is NFC pristine.
    """
    ident = check_image(image)
    if not fingerprint or len(fingerprint) != 64 or any(x not in '0123456789abcdef' for x in fingerprint):
        raise SafetyError('Empreinte de cache invalide.')
    state = load_state()
    old = state['objects'].get(fingerprint)
    if old:
        ref = Path(old['reference'])
        if not ref.is_file() or sha256(ref.read_bytes()) != old['reference_sha256']:
            raise SafetyError('Référence manquante ou altérée : action annulée.')
        if tuple(old['identity']) != ident:
            raise SafetyError('Identité différente de la référence NFC : action annulée.')
        if ref.read_bytes()[:48] != image[:48]:
            raise SafetyError('Empreinte du cache identique mais UID/en-tête différents : '
                              'deux figurines distinctes sont peut-être confondues.')
        return ref
    path = ORIGINAL_DIR / (fingerprint + '.sky')
    created = atomic_write_new(path, image)
    if not created and path.read_bytes() != image:
        raise SafetyError('Conflit avec référence déjà existante.')
    state['objects'][fingerprint] = {
        'reference': str(path.resolve()), 'reference_sha256': sha256(image),
        'provenance': provenance, 'label': name,
        'identity': list(ident), 'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'latest_virtual_path': None, 'latest_virtual_sha256': None,
    }
    atomic_write_json(STATE_PATH, state)
    return path


def register_virtual(fingerprint: str, image: bytes, path: Path) -> None:
    check_image(image)
    state = load_state()
    obj = state['objects'].get(fingerprint)
    if not obj:
        raise SafetyError('Référence absente : sauvegarde virtuelle non indexée.')
    reference = Path(obj['reference']).read_bytes()
    changes = compare(reference, image)
    # Allow the game image to be preserved as a backup even if protected bytes changed;
    # report refuses any proposal for physical writing.
    obj['latest_virtual_path'] = str(path.resolve())
    obj['latest_virtual_sha256'] = sha256(image)
    obj['has_protected_changes'] = not changes['potentially_editable']
    obj['last_saved_utc'] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(STATE_PATH, state)


def compare(reference: bytes, candidate: bytes) -> dict:
    expected = check_image(reference)
    check_image(candidate, expected)
    changed = [i for i in range(64) if reference[16*i:16*(i+1)] != candidate[16*i:16*(i+1)]]
    risky = [i for i in changed if i in TRAILERS or i in (0, 1, 2)]
    uid_same = reference[:4] == candidate[:4]
    metadata_same = reference[:48] == candidate[:48]
    safe = not risky and uid_same and metadata_same
    return {
        'identity': list(expected), 'reference_sha256': sha256(reference),
        'virtual_sha256': sha256(candidate),
        'changed_blocks': changed, 'changed_block_count': len(changed),
        'protected_or_identity_blocks_changed': risky,
        'uid_unchanged': uid_same, 'static_header_unchanged': metadata_same,
        'potentially_editable': safe,
        'writing_is_implemented': False,
        'warning': ('DIAGNOSTIC UNIQUEMENT. Ne permet PAS de conclure que ces blocs sont sûrs '
                    'à écrire sur une vraie puce. Aucune commande NFC W dans la V4.3.'),
    }


def prepare_reports() -> list[Path]:
    state = load_state()
    result = []
    for fingerprint, entry in sorted(state['objects'].items()):
        dst = entry.get('latest_virtual_path')
        if not dst:
            continue
        try:
            ref_path = Path(entry['reference'])
            candidate_path = Path(dst)
            ref = ref_path.read_bytes()
            image = candidate_path.read_bytes()
            if sha256(ref) != entry['reference_sha256'] or sha256(image) != entry['latest_virtual_sha256']:
                raise SafetyError('Empreinte SHA-256 différente : fichier modifié depuis la dernière sauvegarde.')
            diff = compare(ref, image)
            report = {'format': 'skylanders-nfc-offline-plan-v1',
                      'created_utc': datetime.now(timezone.utc).isoformat(),
                      'fingerprint': fingerprint, 'reference_provenance': entry['provenance'],
                      'reference': str(ref_path), 'virtual': str(candidate_path), 'result': diff}
        except (OSError, ValueError, TypeError, KeyError) as exc:
            report = {'format': 'skylanders-nfc-offline-plan-v1', 'fingerprint': fingerprint,
                      'error': str(exc), 'writing_is_implemented': False}
        filename = (fingerprint[:12] + '_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
        target = PLAN_DIR / filename
        atomic_write_json(target, report)
        result.append(target)
    return result


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='Examine deux fichiers .sky sans contacter le portail Bluetooth')
    p.add_argument('reference', type=Path)
    p.add_argument('virtual', type=Path)
    args = p.parse_args()
    comparison = compare(args.reference.read_bytes(), args.virtual.read_bytes())
    print(json.dumps(comparison, indent=2, ensure_ascii=False))
