# Skylanders Bluetooth Bridge 🎮

> **Portail Traptanium Bluetooth de l'édition tablette → Windows → Cemu VirtPort**, avec les vraies figurines, les pièges et la petite manette d'origine.

[Guide d'installation](docs/INSTALLATION_FR.md) · [Manette](docs/MANETTE_FR.md) · [Dépannage](docs/DEPANNAGE_FR.md) · [Sécurité des sauvegardes](docs/SAUVEGARDES_ET_SECURITE.md) · [Publier sur GitHub](docs/PUBLIER_SUR_GITHUB_FR.md) · [English](README_EN.md)

**Version publiée : 4.3 SafeSync (bêta communautaire).** Projet non officiel et indépendant d'Activision, Toys for Bob et de l'équipe Cemu. Ce dépôt **ne contient ni jeu, ni émulateur, ni firmware, ni fichier `.sky` de figurine, ni pilote Windows**.

## Qu'est-ce que ça fait ?

Tu peux retrouver l'expérience de *Skylanders Trap Team* sur un PC Windows avec le kit Bluetooth de l'ancienne version iPad : poser une figurine sur le portail la fait apparaître dans le jeu, et la retirer la fait disparaître. Les données NFC de la vraie figurine permettent de retrouver sa progression d'origine. Le bridge transmet les objets à **Cemu VirtPort** via une API HTTP locale, sans manipulation de souris ni fenêtre à maintenir au premier plan : le jeu peut fonctionner en plein écran.

Un membre de la communauté a **validé en conditions réelles** le portail Bluetooth, la reconnaissance de personnages et de pièges, la petite manette avec XInput, et l'intégration temps réel avec VirtPort. **La branche 4.3 SafeSync elle-même n'a passé que des tests logiciels et doit encore être validée sur plusieurs configurations Windows.**

## Fonctionnalités / état

| Fonction | Statut |
| --- | --- |
| Détection et reconnexion BLE du portail | ✅ Fonctionne en essai local ; reconnexions à surveiller |
| Lecture de figurines / pièges (64 blocs NFC, commande `Q`) | ✅ Testée sur matériel |
| Reconnaissance des objets via catalogue | ✅ Après synchronisation des identifiants |
| Ajout/retrait des figurines et pièges dans Cemu VirtPort | ✅ Testé sur matériel avec V4/V4.1 ; 4.3 à confirmer |
| Jeu en plein écran | ✅ Testé sur matériel |
| Petite manette → XInput | ✅ Testée sur matériel avec pilote optionnel |
| Cache `.sky` pour les re-poses rapides | ✅ Testé sur matériel |
| Sauvegardes virtuelles et comparaison SafeSync | 🧪 Tests simulés ; validation supplémentaire requise |
| Enregistrer le niveau gagné sur la **puce physique** | ❌ **Non implémenté** |
| Jauges de batterie précises | ❌ Non validées |

## Installation rapide (Windows 10/11)

1. Installe **Python 3.10 ou plus récent** depuis [python.org](https://www.python.org/downloads/windows/) et vérifie `py --version` dans PowerShell. Active le Bluetooth dans Windows.
2. Télécharge **Cemu modifié VirtPort** depuis [ses Releases](https://github.com/TonyHacker03/SkylandersVirtualPortal/releases). Ne lance pas le Cemu standard : l'API utilisée ici est spécifique à VirtPort.
3. Télécharge ce projet sous **Code → Download ZIP**, décompresse-le dans un dossier accessible en écriture (par exemple `Documents\SkylandersBridge`).
4. Lance `scripts\install_windows.bat` une seule fois, puis `METTRE_A_JOUR_CATALOGUE.bat` pour récupérer le catalogue complet depuis son auteur. Tu peux jouer sans Internet après la première synchronisation.
5. Démarre le **Cemu de VirtPort**, puis ouvre `Tools → Emulated USB Devices` **une fois** et laisse la fenêtre ouverte (tu peux la minimiser). Vérifie que le jeu fonctionne.
6. Double-clique sur `LANCER_BRIDGE.bat`, clique sur **Tester Cemu/VirtPort**, puis sur **Connecter le portail BLE**. Place ta figurine sur le portail. La première lecture peut prendre plusieurs secondes ; les suivantes sont normalement plus rapides grâce au cache.
7. Pour la petite manette : lis d'abord [le guide manette](docs/MANETTE_FR.md), puis utilise `INSTALLER_SUPPORT_MANETTE.bat` si tu acceptes les conditions d'installation du pilote optionnel. Configure **XInput / Wii U GamePad** dans Cemu.

**Important :** ne débranche pas le portail pendant une sauvegarde. Pour conserver les progrès réalisés dans Cemu, utilise **Sauvegarder maintenant (.sky)** avant de fermer, puis attends la confirmation dans le journal. Cela ne modifie **jamais** les puces NFC d'origine.

👉 Tous les détails et captures possibles à produire : [installation pas à pas](docs/INSTALLATION_FR.md).

## Comment ça marche ?

```text
Portail Traptanium BLE -- notifications S + lectures Q --> Bridge Python
           |                                           |
           |                                           +-- cache / backups `.sky`
           |                                           +-- API locale 127.0.0.1:5678
           |                                                          |
           +-- figurines et pièges NFC ------------------------------- Cemu VirtPort

Petite manette BLE --> bridge Python --> vgamepad / pilote virtuel --> XInput --> Cemu
```

Le programme utilise les UUID réels du portail, lus sur matériel : service `533e1530…`, notifications `533e1542…`, écriture BLE des **requêtes de lecture NFC** `533e1543…`. Aucune commande d'écriture NFC `W` n'est implémentée. Le serveur VirtPort se trouve sur `127.0.0.1:5678` ; **n'expose jamais ce port à Internet**.

## Fichiers principaux

```text
src/skylanders_virtport_live.py    # Interface et bridge temps réel
src/skylanders_bridge_v1_2.py      # Lecteur BLE et reconnaissance (nom historique)
src/skylanders_extras.py           # Pièges, sauvegardes et manette
src/skylanders_cemu_bridge.py      # Images NFC et export
src/skylanders_trap_decoder.py     # Décodage des pièges
src/skylanders_sync_guard.py       # SafeSync, vérifications et rapports
src/skylanders_catalogue.py       # Catalogue à synchroniser
src/catalogue_secours.json         # 8 objets de test, pas toute la base tierce
tests/                            # Tests sans matériel
```

Le projet conserve quelques **noms de fichiers historiques** afin de ne pas casser les imports d'une version dont le chemin BLE → Cemu a été testé. Un refactor plus ambitieux pourra suivre, avec des tests physiques systématiques.

## Tests (sans matériel)

Sous Windows, double-clique sur `TESTER_SANS_MATERIEL.bat`, ou exécute :

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Ces tests couvrent notamment le protocole `Q`, les identifiants, un serveur VirtPort simulé, le cache et les refus de sauvegarde dangereux. **Ils ne remplacent pas un test avec un vrai portail.**

## Participer et signaler un bug

Ouvre une **Issue GitHub** dans l’onglet « Issues » du dépôt, en suivant le modèle fourni, avec version de Windows, version de Cemu VirtPort, comportement attendu et journal anonymisé. Les contributions sont bienvenues : voir [CONTRIBUTING.md](CONTRIBUTING.md).

⚠️ **Ne joins jamais une sauvegarde NFC complète ou un journal contenant une adresse Bluetooth sans vérification préalable.** Les fichiers de progression contiennent des données individuelles de ta collection ; lis [la politique de sécurité](docs/SAUVEGARDES_ET_SECURITE.md). Le `.gitignore` exclut ces données par défaut, mais ne protège pas contre les fichiers déjà indexés ou les copies publiées manuellement.

## Crédits, compatibilité et droits

- [VirtPort](https://github.com/TonyHacker03/SkylandersVirtualPortal) : Cemu modifié et API locale (à installer séparément).
- [Cemu](https://github.com/cemu-project/Cemu) : émulateur Wii U, **non fourni**.
- [Skylander-IDs (Texthead1)](https://github.com/Texthead1/Skylander-IDs) : catalogue d'identifiants récupéré à la demande, **non recopié intégralement dans ce dépôt**.
- [Bleak](https://github.com/hbldh/bleak), [cryptography](https://github.com/pyca/cryptography), [vgamepad](https://github.com/yannbouteiller/vgamepad) : dépendances installées séparément.
- [ViGEmBus](https://github.com/nefarius/ViGEmBus) : pilote tiers optionnel désormais **archivé et non maintenu** ; installation à vos risques, voir le guide manette.

Le code Python original de ce projet est proposé sous [licence MIT](LICENSE) ; les projets externes restent soumis à leurs propres licences. Les marques Skylanders, Trap Team, les personnages et les jeux appartiennent à leurs détenteurs respectifs. Utilise des copies de jeu et des fichiers NFC que tu es autorisé à posséder et à exploiter.
