# Dépannage — erreurs fréquentes

| Symptôme | Vérification / solution |
| --- | --- |
| `py` non reconnu | Réinstalle Python 3.10+ depuis python.org avec le lanceur Python, puis rouvre PowerShell. |
| Bleak ne trouve pas le portail | Vérifie Bluetooth Windows, piles, portée, portail allumé et absence de connexion à un ancien iPad. Essaie un adaptateur BLE compatible. |
| `WinError 10061` | Lance **Cemu modifié VirtPort**, puis ouvre `Tools → Emulated USB Devices` (fenêtre ouverte, même minimisée). |
| `TcpTestSucceeded : False` sur 5678 | Le serveur VirtPort n'écoute pas. Vérifie son processus, sa version, son initialisation. N'ouvre pas ce port sur Internet. |
| Le Cemu standard n'a pas de bridge | Normal : l'API HTTP locale est spécifique à VirtPort. |
| Le jeu ne voit pas le personnage | Vérifie le ping local, le journal du bridge et la présence du portail virtuel dans VirtPort. Essaie un personnage seul. |
| Le premier switch est lent | Premier passage = 64 lectures NFC. Les suivants utilisent le cache, sauf si `--fresh` est utilisé. |
| Le piège est identifié mais son méchant est inconnu | Fais une sauvegarde complète de 64 blocs ; un scan partiel ne permet pas de décoder le contenu. |
| La manette se connecte mais n'agit pas en jeu | Vérifie `vgamepad` / pilote, la présence d'un contrôleur XInput et la configuration Wii U GamePad de Cemu. |
| Le BLE se coupe | Vérifie les piles du portail et de la manette, rapproche-les du PC ; désactive temporairement la mise en veille de l'adaptateur Bluetooth si approprié. |
| Le jeu semble perdre la progression | Ferme le jeu proprement, regarde `src\virtport_game_saves` et `src\safesync` ; ne supprime pas les anciennes versions. |

## Diagnostic utile

```powershell
py --version
Test-NetConnection 127.0.0.1 -Port 5678
Get-Process Cemu* | Select-Object ProcessName,Path
```

Pour signaler un bug, fournis la séquence exacte, la dernière erreur et la version des outils. **Masque les adresses Bluetooth et ne publie pas de dumps NFC ou de sauvegardes personnelles.**
