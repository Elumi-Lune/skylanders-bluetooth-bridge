#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Skylanders Bluetooth Bridge V2.3 — GUI unifiée, Windows.

V1.2 conservée ; extension pour lire les blocs NFC des pièges,
inspecter des sauvegardes locales et connecter la manette BLE.
Aucune commande de modification du contenu NFC n'est implémentée.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from skylanders_bridge_v1_2 import BridgeApp, worker_entry, self_test as old_self_test
from skylanders_extras import (
    ResearchPortalWorker, ControllerWorker, controller_entry,
    read_dump, compare_dumps, BACKUP_DIR, decode_controller_packet,
    decode_q, nfc_query,
)


class SkylandersSuite(BridgeApp):
    def __init__(self, root):
        import tkinter as tk
        self.portal_connected = False
        self.gamepad_stop = threading.Event()
        self.gamepad_thread = None
        self.gamepad_window = None
        self.trap_window = None
        self.workshop_window = None
        self.gamepad_vars = {}
        self.trap_text = None
        self.workshop_report = None
        super().__init__(root)
        root.title('Skylanders Bluetooth Bridge V2.3 — Portail + Manette + Atelier NFC')
        root.geometry('1090x820')
        menu = tk.Menu(root)
        portal = tk.Menu(menu, tearoff=False)
        portal.add_command(label='Scanner et sauvegarder un piège…', command=self.open_traps)
        portal.add_command(label='Manette Bluetooth…', command=self.open_gamepad)
        portal.add_command(label='Atelier NFC (hors ligne)…', command=self.open_workshop)
        menu.add_cascade(label='Outils V2', menu=portal)
        root.config(menu=menu)
        self.append('V2.3 : lecture pièges sur leur emplacement réel (non fixé à 2). Écriture NFC physique NON disponible.')

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
        self.running = True
        self.demo_mode = False
        self.update_buttons()
        self.connection_label.set('Recherche…')
        self.status_dot.configure(fg=self.ORANGE)
        self.hint.set('Connexion BLE. Pour sauvegarder un piège, menu Outils V2.')
        worker = ResearchPortalWorker(self.events, self.stop, self.allow_reads,
                                      self.allow_trap_reads, self.reread_requests,
                                      self.catalogue, self.dump_requests)
        self.thread = threading.Thread(target=worker_entry, args=(worker,), daemon=True)
        self.thread.start()

    def on_event(self, event: str, **data: Any) -> None:
        if event == 'connected':
            self.portal_connected = True
        elif event in ('stopped', 'error'):
            self.portal_connected = False
        if event in ('dump_progress', 'dump_finished'):
            line = data.get('text', '')
            self.append('PIÈGE : ' + line)
            if self.trap_text is not None:
                try:
                    self.trap_text.configure(state='normal')
                    self.trap_text.insert('end', line + '\n')
                    self.trap_text.see('end')
                    self.trap_text.configure(state='disabled')
                except Exception:
                    self.trap_text = None
            return
        if event.startswith('gamepad_'):
            if event == 'gamepad_state':
                for key, value in data.items():
                    if key in self.gamepad_vars:
                        self.gamepad_vars[key].set(str(value))
            elif event in ('gamepad_info', 'gamepad_connected', 'gamepad_error', 'gamepad_stopped'):
                text = data.get('text', '')
                if 'status' in self.gamepad_vars:
                    self.gamepad_vars['status'].set(text)
                self.append('MANETTE : ' + text)
            return
        super().on_event(event, **data)
        if event == 'stopped':
            self.clear_objects()  # Never display an old trap after disconnection.

    def open_traps(self):
        import tkinter as tk
        from tkinter import messagebox
        if self.trap_window is not None and self.trap_window.winfo_exists():
            self.trap_window.lift(); return
        p = tk.Toplevel(self.root)
        p.title('Atelier pièges — sauvegarde NFC sans écriture')
        p.geometry('850x550')
        p.configure(bg=self.BG)
        self.trap_window = p
        tk.Label(p, text='PIÈGES TRAPTANIUM — LECTURE UNIQUEMENT', bg=self.BG,
                 fg=self.ACCENT, font=('Segoe UI', 15, 'bold')).pack(anchor='w', padx=16, pady=12)
        instructions = (
            '1. Connecte le portail dans la fenêtre principale. 2. Pose un piège seul dans sa fente et active sa lecture NFC dans la fenêtre principale.\n'
            '3. Le piège est suivi à sa position BLE réelle (0, 1, 2, etc.), puis lu sur demande.\n'
            'Lecture ciblée (13 blocs) ou complète (64 blocs) : commandes Q uniquement, une à la fois.\n'
            'Après 64 blocs : déchiffrement local du méchant actuel et historique. Aucun bloc modifié.'
        )
        tk.Label(p, text=instructions, bg=self.BG, fg=self.TEXT, justify='left',
                 wraplength=800).pack(anchor='w', padx=16)
        bar = tk.Frame(p, bg=self.BG); bar.pack(fill='x', padx=16, pady=12)
        def submit(mode):
            if not self.running or not self.portal_connected:
                messagebox.showwarning('Portail absent', 'Attends la confirmation de connexion Bluetooth dans la fenêtre principale.', parent=p)
                return
            if not self.allow_reads.is_set():
                messagebox.showwarning('Lecture NFC désactivée',
                    'Active « Autoriser la lecture NFC automatique » dans la fenêtre principale, puis repose le piège pour identifier son ID. Le piège peut être en emplacement 0, 1, 2, etc.', parent=p)
                return
            explanation = ('13 blocs ciblés' if mode == 'focus' else '64 blocs / 1024 octets')
            if not messagebox.askyesno('Confirmer lecture NFC',
                     f'Lire {explanation} sur le piège identifié dans son emplacement réel ?\n\n'
                     'Cette opération n’envoie aucune commande de modification NFC.\n'
                     'La lecture peut échouer sur des blocs protégés.', parent=p):
                return
            self.dump_requests.put(mode)
            self.append('Lecture du piège demandée : ' + explanation)
        for text, mode in [('Lire les blocs ciblés', 'focus'), ('Sauvegarde complète (64 blocs)', 'full')]:
            tk.Button(bar, text=text, command=lambda m=mode: submit(m),
                      bg=self.PANEL2, fg=self.TEXT, padx=12, pady=7).pack(side='left', padx=5)
        tk.Button(bar, text='Ouvrir les sauvegardes', command=lambda: self.open_workshop(),
                  bg=self.PANEL2, fg=self.TEXT, padx=12, pady=7).pack(side='right')
        self.trap_text = tk.Text(p, bg=self.PANEL, fg=self.TEXT, wrap='word',
                                 font=('Consolas', 10), borderwidth=0)
        self.trap_text.pack(fill='both', expand=True, padx=16, pady=(0, 16))
        self.trap_text.insert('end', 'Journal des lectures de piège. Les sauvegardes sont dans skylanders_backups.\n')
        self.trap_text.configure(state='disabled')
        def on_close():
            self.trap_text = None; self.trap_window = None; p.destroy()
        p.protocol('WM_DELETE_WINDOW', on_close)

    def open_gamepad(self):
        import tkinter as tk
        from tkinter import messagebox
        if self.gamepad_window is not None and self.gamepad_window.winfo_exists():
            self.gamepad_window.lift(); return
        p = tk.Toplevel(self.root)
        p.title('Skylanders GamePad — Manette Bluetooth')
        p.geometry('720x520')
        p.configure(bg=self.BG)
        self.gamepad_window = p
        tk.Label(p, text='MANETTE BLUETOOTH SKYLANDERS', bg=self.BG, fg=self.ACCENT,
                 font=('Segoe UI', 15, 'bold')).pack(anchor='w', padx=16, pady=12)
        tk.Label(p, text='Surveillance BLE sans pilote par défaut. XInput facultatif nécessite vgamepad\n'
                 'et un pilote ViGEmBus installé à part (projet abandonné : lire les avertissements du guide).',
                 bg=self.BG, fg=self.TEXT, justify='left').pack(anchor='w', padx=16)
        xinput = tk.BooleanVar(value=False)
        tk.Checkbutton(p, text='Activer une manette Xbox virtuelle (EXPÉRIMENTAL, installation manuelle)',
                       variable=xinput, bg=self.BG, fg=self.TEXT, activebackground=self.BG,
                       selectcolor=self.PANEL).pack(anchor='w', padx=16, pady=10)
        fields = {'status': 'Déconnectée', 'buttons': '—', 'left': '—', 'right': '—',
                  'triggers': '—', 'battery': '—', 'frames': '0', 'raw': '—'}
        self.gamepad_vars = {key: tk.StringVar(value=value) for key, value in fields.items()}
        frame = tk.Frame(p, bg=self.PANEL, padx=16, pady=13); frame.pack(fill='both', expand=True, padx=16)
        for key, title in [('status','État'),('buttons','Boutons'),('left','Stick gauche X,Y'),
                           ('right','Stick droit X,Y'),('triggers','Gâchettes G/D'),
                           ('battery','Batterie (valeur brute)'),('frames','Paquets'),('raw','Trame BLE')]:
            row = tk.Frame(frame, bg=self.PANEL); row.pack(fill='x', pady=6)
            tk.Label(row, text=title, width=23, anchor='w', bg=self.PANEL, fg=self.MUTED).pack(side='left')
            tk.Label(row, textvariable=self.gamepad_vars[key], anchor='w', bg=self.PANEL,
                     fg=self.TEXT, wraplength=460, justify='left').pack(side='left')
        buttons = tk.Frame(p, bg=self.BG); buttons.pack(fill='x', padx=16, pady=14)
        def connect():
            if self.gamepad_thread and self.gamepad_thread.is_alive(): return
            if xinput.get() and not messagebox.askyesno('XInput expérimental',
                  'XInput peut exiger un pilote tiers ViGEmBus abandonné et non installé par ce programme.\n'
                  'As-tu déjà vérifié ce pilote et souhaites-tu activer XInput ?', parent=p):
                return
            self.gamepad_stop = threading.Event()
            worker = ControllerWorker(self.events, self.gamepad_stop, bool(xinput.get()))
            self.gamepad_thread = threading.Thread(target=controller_entry, args=(worker,), daemon=True)
            self.gamepad_thread.start()
            self.gamepad_vars['status'].set('Recherche BLE…')
        tk.Button(buttons, text='Connecter la manette', command=connect,
                  bg=self.ACCENT, fg='#071525', padx=12, pady=7).pack(side='left')
        tk.Button(buttons, text='Déconnecter', command=lambda: self.gamepad_stop.set(),
                  bg=self.PANEL2, fg=self.TEXT, padx=12, pady=7).pack(side='left', padx=12)
        def on_close():
            self.gamepad_stop.set(); self.gamepad_vars = {}; self.gamepad_window = None; p.destroy()
        p.protocol('WM_DELETE_WINDOW', on_close)

    def open_workshop(self):
        import tkinter as tk
        from tkinter import filedialog, messagebox
        if self.workshop_window is not None and self.workshop_window.winfo_exists():
            self.workshop_window.lift(); return
        p = tk.Toplevel(self.root); self.workshop_window = p
        p.title('Atelier NFC — sauvegardes, comparaison, projet de modification')
        p.geometry('940x710'); p.configure(bg=self.BG)
        tk.Label(p, text='ATELIER NFC — MODIFICATIONS HORS LIGNE', bg=self.BG, fg=self.ORANGE,
                 font=('Segoe UI', 15, 'bold')).pack(anchor='w', padx=15, pady=10)
        tk.Label(p, text='Lecture/inspection des pièges : OUI. Préparation d’un fichier modifié : OUI. '
                 'Écriture physique NFC : BLOQUÉE.\n'
                 'Une écriture erronée peut détruire une sauvegarde ou rendre une figurine illisible. '
                 'Aucune commande W n’est incluse.',
                 bg=self.BG, fg=self.TEXT, justify='left', wraplength=900).pack(anchor='w', padx=15)
        controls = tk.Frame(p, bg=self.BG); controls.pack(fill='x', padx=15, pady=12)
        display = tk.Text(p, bg=self.PANEL, fg=self.TEXT, wrap='none', font=('Consolas', 10))
        display.pack(fill='both', expand=True, padx=15, pady=8)
        def log(text):
            display.insert('end', text+'\n'); display.see('end')
        def open_report():
            path = filedialog.askopenfilename(parent=p, title='Ouvrir une sauvegarde JSON',
                  initialdir=str(BACKUP_DIR), filetypes=[('Sauvegarde Skylanders', '*.json')])
            if not path: return
            try:
                self.workshop_report = read_dump(path)
            except Exception as exc:
                messagebox.showerror('Rapport illisible', str(exc), parent=p); return
            display.delete('1.0','end')
            report = self.workshop_report
            log('Fichier : ' + path)
            log(f"Blocs lus : {len(report['blocks'])}/{len(report['requested_blocks'])}")
            from skylanders_trap_decoder import decode_trap_report, format_summary, TrapDecodeError
            try:
                decoded = decode_trap_report(report)
                log(format_summary(decoded))
            except TrapDecodeError as exc:
                log('Contenu non décodable : ' + str(exc))
            for k,v in sorted(report['blocks'].items(), key=lambda t: int(t[0])):
                log(f'Bloc {int(k):02d} : {bytes.fromhex(v).hex(" ")}')
            if report.get('errors'): log('Erreurs : ' + repr(report['errors']))
        def diff():
            a = filedialog.askopenfilename(parent=p, title='Première sauvegarde', initialdir=str(BACKUP_DIR), filetypes=[('JSON', '*.json')])
            if not a: return
            b = filedialog.askopenfilename(parent=p, title='Seconde sauvegarde', initialdir=str(BACKUP_DIR), filetypes=[('JSON', '*.json')])
            if not b: return
            try: changes = compare_dumps(read_dump(a), read_dump(b))
            except Exception as exc:
                messagebox.showerror('Erreur de comparaison',str(exc),parent=p); return
            display.delete('1.0','end')
            log(f'Comparaison : {Path(a).name} ↔ {Path(b).name}')
            log(f'{len(changes)} blocs différents / manquants')
            for change in changes: log(change)
        tk.Button(controls,text='Ouvrir sauvegarde',command=open_report,bg=self.PANEL2,fg=self.TEXT,padx=8,pady=6).pack(side='left')
        tk.Button(controls,text='Comparer deux sauvegardes',command=diff,bg=self.PANEL2,fg=self.TEXT,padx=8,pady=6).pack(side='left',padx=9)
        tk.Label(p,text='Brouillon de modification d’un seul bloc (enregistré dans un JSON, jamais envoyé à la puce)',
                 bg=self.BG, fg=self.MUTED).pack(anchor='w', padx=15, pady=(8,4))
        draftframe = tk.Frame(p,bg=self.BG); draftframe.pack(fill='x',padx=15)
        tk.Label(draftframe,text='Bloc (8–62) :',bg=self.BG,fg=self.TEXT).pack(side='left')
        block_val=tk.StringVar(value='37'); tk.Entry(draftframe,textvariable=block_val,width=5).pack(side='left',padx=6)
        tk.Label(draftframe,text='16 octets hex :',bg=self.BG,fg=self.TEXT).pack(side='left')
        hex_val=tk.StringVar(); tk.Entry(draftframe,textvariable=hex_val,width=43).pack(side='left',padx=6)
        def prepare():
            report=self.workshop_report
            if not report:
                messagebox.showwarning('Sauvegarde requise','Ouvre d’abord une sauvegarde de piège.',parent=p);return
            try:
                block=int(block_val.get()); data=bytes.fromhex(hex_val.get())
                if block < 8 or block > 62 or block % 4 == 3:
                    raise ValueError('Bloc protégé dans notre atelier (secteur/manufacturier ou remorque)')
                if len(data)!=16: raise ValueError('Il faut exactement 16 octets')
                old=report['blocks'].get(str(block))
                if old is None: raise ValueError('Ce bloc n’a pas été sauvegardé : modification refusée')
                if not messagebox.askyesno('Créer un brouillon NON APPLIQUÉ',
                    f'Bloc {block}\nAVANT : {old}\nAPRÈS : {data.hex()}\n\n'
                    'Seul un fichier de brouillon sera créé. La puce ne sera PAS modifiée.\nConfirmer ?',parent=p):return
                BACKUP_DIR.mkdir(exist_ok=True)
                target=BACKUP_DIR/('brouillon_NON_APPLIQUE_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json')
                draft={'format':'skylanders-bridge-DRAFT-NO-WRITES','source':'rapport de sauvegarde local',
                       'old_block_hex':old,'new_block_hex':data.hex(),'block':block,
                       'WARNING':'PAS APPLIQUÉ AU MATÉRIEL; checksums/chiffrement non recalculés'}
                target.write_text(json.dumps(draft,ensure_ascii=False,indent=2),encoding='utf-8')
                log('BROUILLON créé (NON ÉCRIT) : '+str(target))
            except Exception as exc:
                messagebox.showerror('Brouillon refusé',str(exc),parent=p)
        tk.Button(draftframe,text='Préparer brouillon',command=prepare,
                  bg=self.PANEL2,fg=self.TEXT,padx=10,pady=6).pack(side='left',padx=9)
        tk.Label(p,text='Écriture physique sur les pièges et figurines : verrouillée (protocole de restauration non validé).',
                 bg=self.BG,fg=self.ORANGE).pack(anchor='w',padx=15,pady=(12,16))
        def on_close(): self.workshop_window=None; p.destroy()
        p.protocol('WM_DELETE_WINDOW', on_close)

    def close(self):
        self.gamepad_stop.set()
        super().close()


def self_test():
    old_self_test()
    assert nfc_query(2, 1) == bytes.fromhex('51 12 01') + bytes(17)
    jaw = bytes.fromhex('51 10 01 d6 01 00 00 3d 2a 16 dd 8f de 00 00 00 30 af 9e 00')
    assert decode_q(jaw, 0, 1)[0:2] == b'\xd6\x01'
    raw=bytearray(20)
    raw[8]=0x11; raw[9]=0x10; raw[10]=0xff; raw[14]=0x80
    pad=decode_controller_packet(bytes(raw))
    assert 'A' in pad.buttons and '↑' in pad.buttons and 'LB' in pad.buttons
    assert pad.lt==255 and pad.lx==-128
    import tempfile
    from skylanders_extras import read_dump, compare_dumps
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/'test.json'
        p.write_text(json.dumps({'format':'skylanders-bridge-trap-readonly-v1','blocks':{'1':'aa'*16},'requested_blocks':[1]}))
        assert read_dump(p)['blocks']['1']=='aa'*16
        assert compare_dumps(read_dump(p), {'blocks':{'1':'bb'*16}})
    print('V2 OK : requête Q, decode manette, journal, comparaison et tests V1.2.')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:
        self_test(); return
    import tkinter as tk
    root=tk.Tk()
    SkylandersSuite(root)
    root.mainloop()

if __name__=='__main__':
    main()
