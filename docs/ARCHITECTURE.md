# Architecture actuelle (V4.3)

## Flux du portail

1. Découverte BLE (`bleak`) du nom annoncé **Skylanders Portal**.
2. Connexion au service du portail `533e1530…` ; écoute des notifications `533e1542…`.
3. Paquets `S` : suivi des emplacements (états codés par groupes de 2 bits : absent, présent, retrait, ajout).
4. Paquets `Q` : lecture **seule** d'un bloc NFC de 16 octets ; une seule demande en vol ; lecture jusqu'à 64 blocs par objet à la première pose.
5. Vérification d'identité et constitution d'un `.sky` de 1024 octets ; cache local pour les poses suivantes.
6. Opérations HTTP sur `127.0.0.1:5678` pour charger/enlever une figurine de VirtPort et récupérer sa sauvegarde virtuelle.

Les commandes exposées côté VirtPort dans la branche testée incluent `/ping`, `/heartbeat`, `/claim`, `/upload`, `/download` et `SUMMON` / `CLEAR`. Le bridge ne modifie pas Cemu ; il utilise la version adaptée publiée séparément par le projet VirtPort.

## Manette

La petite manette annonce son propre service BLE. Le module `ControllerWorker` lit ses notifications et transmet le résultat à `vgamepad`, qui émule XInput avec un pilote externe installé séparément.

## Données / persistance

- `skylanders_catalogue.py` télécharge le README des identifiants sous forme de Markdown, le valide (taille et présence de plusieurs paires connues) et enregistre un catalogue local. Aucun code téléchargé n'est exécuté.
- `skylanders_sync_guard.py` conserve les copies de référence et compare les sauvegardes Cemu ; aucune méthode de réécriture NFC physique.
- L'interface, les modules lecteurs et les tests conservent certains noms hérités de versions précédentes pour éviter de casser une chaîne fonctionnelle.

## Limites et prochaines étapes

- Tests BLE sur plusieurs adaptateurs Windows et tolérance aux déconnexions.
- Robustesse des sauvegardes au moment des coupures.
- Compatibilité des variantes, figurines à pièces interchangeables, véhicules et pièges spéciaux.
- Mesure fiable du niveau des piles si le protocole l'expose.
- **Aucun support d'écriture physique NFC**, même si certains outils externes la proposent pour d'autres portails.
