# Contribuer

Merci de contribuer à la préservation du matériel Skylanders de l'édition tablette !

1. Ouvre d'abord une **Issue** décrivant le bug, l'équipement utilisé, la version de Windows et celle de VirtPort.
2. Pour le code, travaille sur une branche dédiée puis soumets une Pull Request avec une description des changements et les commandes de test utilisées.
3. Ne colle jamais de dumps NFC complets, d'adresses Bluetooth non masquées, de copies du jeu, d'APK propriétaires ou de pilotes dans les commits, Issues et PR.
4. Teste au minimum `python -m unittest discover -s tests -v`, puis, si tu possèdes le matériel, confirme ton résultat séparément dans la PR.
5. **Aucune écriture physique NFC** ne doit être introduite comme fonctionnalité par défaut. Une telle contribution nécessite une revue du protocole, une stratégie fiable de sauvegarde et restauration et des tests physiques contrôlés.
6. Respecte les licences des projets externes : ne copie pas dans ce dépôt de fichiers de VirtPort, Cemu ou Skylander-IDs sans permissions adaptées.

Merci aux communautés Cemu, VirtPort, Skylander-IDs, Bleak et aux passionnés ayant documenté le matériel BLE.
