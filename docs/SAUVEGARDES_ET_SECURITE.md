# Sécurité, NFC, sauvegardes et confidentialité

## Ce qui est envoyé au portail

La caractéristique BLE `533e1543…` accepte des commandes envoyées *au portail*. Dans ce projet, elle reçoit uniquement des commandes `Q` qui **demandent une lecture des blocs NFC** ; cela ne correspond pas à une écriture dans une puce. **Aucune commande NFC `W` n'est construite ou exposée dans cette version**.

## Ce qui est sauvegardé sur le PC

- `src/virtport_cache/` : copies réutilisées pour accélérer les nouvelles poses.
- `src/virtport_game_saves/` : copies de la progression récupérées depuis Cemu.
- `src/safesync/` : références, index et rapports des différences.
- `src/skylanders_backups/` : dumps ou journaux créés par certains modules.
- `src/skylanders_logs/` : journaux, qui peuvent contenir des identifiants d'appareils.

Le format `.sky` stocke 1 024 octets, et peut inclure l'historique de progression et une identité de puce NFC. **Ne le publie pas sur GitHub** sans comprendre son contenu et tes droits à le partager.

## Garanties et limites de SafeSync

La V4.3 vérifie des sauvegardes de taille attendue et certaines données d'identité avant de mettre à jour le cache. Elle conserve des références et produit des rapports de différences. Cela ne prouve **pas** qu'une réécriture physique serait possible ou sans risque ; la restauration sur puce reste volontairement indisponible.

Une coupure pendant une sauvegarde ou une erreur du serveur VirtPort peut retarder le retrait d'un objet virtuel. En cas de panne, **n'écrase pas les fichiers originaux**. Fais une copie de l'ensemble des répertoires ci-dessus avant toute migration.

## Sécurité réseau

VirtPort possède une API locale sur le port `5678`. Notre client se connecte uniquement à `127.0.0.1` ; **n'ajoute pas d'exception de pare-feu entrante et n'expose pas ce port à ton réseau ou à Internet**. Le projet n'a pas de serveur externe à configurer. Évite de lancer un Cemu modifié téléchargé depuis une source non officielle.

## Publication GitHub

- `.gitignore` protège contre l'ajout ordinaire de `.sky`, `.dump`, `.bin`, journaux et caches ; il ne remplace pas une vérification avec `git status`.
- Vérifie `git status` et `git diff --cached --name-only` avant le commit. Si un fichier personnel a été commité par erreur, retirer le fichier ne retire pas automatiquement son historique : il faudra nettoyer l'historique ou recréer le dépôt.
- N'ajoute ni ton ancienne application mobile, ni l'APK du jeu, ni son binaire ARM, ni des copies de jeux Wii U, ni le Cemu modifié (qui possède sa licence propre).
