# Manette Bluetooth de Trap Team — XInput

La petite manette de l'édition tablette utilise son propre service BLE. Le bridge peut convertir ses boutons, joysticks et gâchettes vers une **manette Xbox virtuelle**, présentée à Cemu via XInput.

## Avant d'installer

`vgamepad` dépend sous Windows d'un pilote système tiers [ViGEmBus](https://github.com/nefarius/ViGEmBus), dont le projet est **retiré/archivé**. L'installation peut demander des droits administrateur et modifier les pilotes du PC. N'installe jamais de pilote à partir d'un site inconnu. Consulte l'[annonce de fin de vie](https://docs.nefarius.at/projects/ViGEm/End-of-Life/).

## Configuration

1. Installe d'abord le bridge et teste le portail **sans manette**.
2. Si tu acceptes le risque d'un pilote ancien, lance `INSTALLER_SUPPORT_MANETTE.bat`. Le script demande confirmation avant de lancer `pip install vgamepad`. Le paquet peut installer ViGEmBus : lis l'écran d'autorisation avant d'accepter.
3. Allume ta petite manette et clique **Connecter manette Xbox** dans la fenêtre du bridge.
4. Si les boutons/axes réagissent, ouvre Cemu → `Options → Input Settings`. Choisis le **Wii U GamePad** et **XInput**, puis configure les touches.
5. En cas de déconnexion, attends la tentative de reconnexion et vérifie les piles.

**Remarque :** il ne s'agit pas d'un support manette officiel de Cemu. Le pilote est optionnel : le portail BLE et la lecture NFC fonctionnent aussi sans lui.
