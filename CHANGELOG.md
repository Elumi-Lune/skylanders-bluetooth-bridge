# Changelog

## 4.3-beta — préparation GitHub (2026-11-01)

- Dossier prêt à publier : README détaillé, installation et dépannage en français, aperçu anglais.
- Conserve le moteur SafeSync 4.3 et ses noms de modules pour minimiser les régressions.
- Lanceurs Windows et environnement Python `.venv` isolé ; support manette optionnel avec avertissement sur ViGEmBus.
- Tests automatiques supplémentaires sans portail ni Cemu réel ; GitHub Actions.
- Catalogue complet synchronisable depuis l'auteur, exclu de Git. Petit catalogue de secours basé sur 8 identités testées.
- `.gitignore` excluant les sauvegardes `.sky`, les journaux et autres données personnelles.
- Écriture NFC physique toujours désactivée.

## 4.3 SafeSync — base de travail

- Références NFC, rapports de changements, sauvegardes virtuelles contrôlées, protection contre perte de progression.
- Bridge temps réel VirtPort, cache rapide et petite manette via XInput conservés.
