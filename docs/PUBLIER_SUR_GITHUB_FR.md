# Publier le bridge sur GitHub

La publication du code source et la publication d'un ZIP de **release** sont deux opérations différentes. Le dépôt contient les scripts et la documentation ; les jeux, émulateurs, pilotes et sauvegardes personnelles n'y figurent pas.

## Vérifications avant publication

1. Garde une copie de tes anciens dossiers du bridge, de tes fichiers `.sky` et de tes sauvegardes NFC **en dehors du dossier du dépôt**.
2. Depuis le dossier du dépôt, vérifie qu'il **ne contient pas** `src/virtport_cache`, `src/virtport_game_saves`, `src/safesync`, `src/skylanders_backups` ou `src/skylanders_logs`.
3. Vérifie le `README.md` et la licence MIT ; ce projet est non officiel et les dépendances externes restent régies par leurs propres licences.
4. Lance `TESTER_SANS_MATERIEL.bat` pour vérifier les cinq tests avant publication.

## Méthode recommandée : Git en ligne de commande

Crée un **dépôt GitHub vide** nommé `skylanders-bluetooth-bridge` (sans générer de README ni de licence, puisqu'ils sont déjà présents ici). Dans PowerShell, positionne-toi dans le dossier de ce projet :

```powershell
git init
git add .
git status
git diff --cached --name-only
git commit -m "Initial public beta: Skylanders Bluetooth Bridge 4.3 SafeSync"
git branch -M main
git remote add origin https://github.com/VOTRE_COMPTE/skylanders-bluetooth-bridge.git
git push -u origin main
```

Remplace `VOTRE_COMPTE` par ton identifiant GitHub. **Lis la liste de `git diff --cached --name-only` avant de créer le commit.** Si tu y vois une sauvegarde `.sky`, un fichier de jeu, des informations personnelles ou une archive binaire : stoppe la procédure et retire le fichier de l'index avant de publier.

## Alternative : site GitHub

Crée un dépôt vide, clique sur **Add file → Upload files**, puis glisse le **contenu extrait** de ce dossier, avec `.github`, `.gitignore`, `src`, `docs`, `scripts` et `tests`. Ne te contente pas de téléverser le ZIP : cela ne crée pas un dépôt avec les fichiers consultables.

## Publication d'une version téléchargeable

Une fois le dépôt en ligne, tu peux créer une release **`v4.3.0-beta`** dans **Releases** avec un ZIP des fichiers du projet. N'y ajoute pas de sauvegardes `.sky`, de dumps, de jeux, de versions tierces de Cemu ni de pilotes.

En cas de mise à jour, vérifie toujours `git status`, `git diff --cached --name-only` et les licences avant `git push`.
