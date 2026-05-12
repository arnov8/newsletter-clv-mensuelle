#!/bin/bash
# Pipeline newsletter mensuel — Cabinet Laurent Valère
# Appelé par cron le 1er de chaque mois : 0 7 1 * * /opt/newsletter-clv-mensuelle/run.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="/var/log/newsletter-clv.log"

echo "$(date '+%Y-%m-%d %H:%M:%S') — Démarrage" >> "$LOG"

cd "$SCRIPT_DIR"

# Charger les variables d'environnement
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# Exécuter le script Python
python3 generate.py 2>&1 | tee -a "$LOG"

echo "$(date '+%Y-%m-%d %H:%M:%S') — Terminé" >> "$LOG"
