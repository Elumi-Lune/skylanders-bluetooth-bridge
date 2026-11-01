# Installation Windows — guide pas à pas

## Avant de commencer

- **Windows 10 ou 11**, Bluetooth BLE fonctionnel sur le PC, portail Traptanium **version tablette Bluetooth** (avec piles fonctionnelles).
- **Python 3.10+**, commande `py --version` dans PowerShell ; Internet pour installer les dépendances Python et récupérer le catalogue.
- **Une copie légitimement obtenue de Skylanders Trap Team (Wii U)**, à configurer dans Cemu VirtPort par tes propres moyens. Le jeu ne se trouve pas dans ce dépôt.
- **Cemu modifié VirtPort** : [versions publiées](https://github.com/TonyHacker03/SkylandersVirtualPortal/releases). Cemu officiel et VirtPort ne sont pas interchangeables pour notre API temps réel.

## Étape 1 — Récupérer et installer le bridge

1. Sur GitHub, clique **Code → Download ZIP**, extrais dans `Documents\SkylandersBridge` (évite `Program Files`).
2. Depuis le dossier extrait, double-clique `scripts\install_windows.bat` et attends la fin de l'installation. Le script crée `.venv`, un environnement Python isolé, puis installe `bleak` et `cryptography`.
3. Exécute `TESTER_SANS_MATERIEL.bat`. Les tests simulés doivent se terminer sans échec.
4. Double-clique `METTRE_A_JOUR_CATALOGUE.bat`. Cette opération importe le catalogue à jour depuis le dépôt **Skylander-IDs**. Le fichier `src\catalogue_local.json` n'est pas ajouté à Git ; tu peux ensuite jouer hors ligne.

Si l'installation échoue, regarde [Dépannage](DEPANNAGE_FR.md).

## Étape 2 — Configurer Cemu VirtPort

1. Décompresse `Cemu_4_virtport.zip` dans **son propre dossier**, sans écraser ton Cemu habituel.
2. Démarre `Cemu.exe` **de ce dossier VirtPort**.
3. Configure une copie personnelle de Trap Team Wii U et vérifie que le jeu démarre.
4. Ouvre `Tools → Emulated USB Devices` : laisse cette fenêtre **ouverte**, éventuellement **minimisée**. C'est nécessaire au serveur de VirtPort sur la version actuellement testée.
5. Tu peux passer le jeu en **plein écran** ensuite.

Pour vérifier le port de VirtPort :

```powershell
Test-NetConnection 127.0.0.1 -Port 5678
```

Si `TcpTestSucceeded : False`, vérifie que tu utilises bien le Cemu VirtPort, que sa fenêtre Emulated USB Devices a été ouverte et que le processus n'a pas été fermé.

## Étape 3 — Connecter le portail

1. Allume le portail et garde-le à proximité du PC. Désactive la connexion Bluetooth de l'ancien iPad si elle interfère.
2. Lance `LANCER_BRIDGE.bat`.
3. Clique **Tester Cemu/VirtPort** : le ping doit réussir.
4. Clique **Connecter le portail BLE**.
5. Pose **une seule figurine** pour le premier essai. Le premier export lit 64 blocs NFC, donc il peut prendre quelques secondes. Les poses suivantes utilisent un cache `.sky` local ; elles devraient être beaucoup plus rapides.
6. Lorsque le bridge indique le chargement, regarde le jeu : ton personnage doit apparaître. Retire la figurine et vérifie qu'il disparaît.
7. Répète avec un piège. Si tu y avais déjà capturé des méchants, leurs données de progression peuvent être présentes dans l'image NFC.

## Étape 4 — Petites manettes de l'édition tablette (facultatif)

Lis [MANETTE_FR.md](MANETTE_FR.md) avant d'installer un pilote. Après installation, clique **Connecter manette Xbox** dans le bridge ; puis, dans Cemu, choisis l'API **XInput** et un contrôleur **Wii U GamePad**. Vérifie les sticks et boutons avant de jouer.

## Étape 5 — Conserver la progression

- Le bouton **Sauvegarder maintenant (.sky)** récupère une copie des données virtuelles du jeu.
- Le bridge tente aussi des sauvegardes lors des retraits et périodiquement, **mais attends toujours une confirmation avant de fermer**.
- Les sauvegardes sont dans `src\virtport_game_saves` et `src\safesync` : conserve-en une copie séparée.
- **Aucune donnée n'est réécrite sur la vraie figurine ou le vrai piège.**
- En cas d'erreur de sauvegarde, le bridge peut différer un retrait pour éviter une perte de progression. Consulte le journal avant de forcer la fermeture.

## Mettre à jour depuis une ancienne V4 / V4.1 / V4.2

1. Ne supprime pas l'ancienne version ni ses caches (`virtport_cache`, `virtport_game_saves`, `safesync`, `skylanders_backups`).
2. Installe cette version dans un **nouveau dossier**.
3. Depuis l'ancienne application, copie les `.sky` dans un dossier temporaire. Dans la nouvelle fenêtre, utilise **Importer .sky V3** : l'option accepte également les copies compatibles des versions suivantes. N'écrase pas les originaux.
4. Teste une seule figurine, puis un piège, avant de remplacer ton ancienne version.

## Ce que ce projet ne fait pas

Il ne fournit aucun jeu, ne permet pas de télécharger des copies commerciales, n'écrit pas sur les puces NFC physiques, et n'offre pas de jauges de batteries validées. Le premier scan n'est pas garanti instantané, les performances et les reconnexions BLE dépendent aussi du PC et de l'état des piles.
