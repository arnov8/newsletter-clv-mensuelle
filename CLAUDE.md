# CLAUDE.md - Historique des modifications et contexte du projet

> **Dernière mise à jour** : 19 août 2026
> **Dernier commit** : `6dcf68b` (Finit le pipeline : charte août 2026, données authentifiées, cron GitHub Actions)
> **Branche** : `main`
> **Repo** : https://github.com/arnov8/newsletter-clv-mensuelle (public, hors iCloud, cloné dans `~/Developer/`)

---

## Contexte du projet

Pipeline qui génère automatiquement, le **1er de chaque mois**, un **brouillon** de la newsletter mensuelle du Cabinet Laurent Valère à partir des biens réellement en vente sur [cabinetlaurentvalere.com](https://www.cabinetlaurentvalere.com), puis l'envoie par email à Arnaud pour relecture avant chargement manuel dans Listmonk.

**Stack** : Python 3.12, Jinja2 (rendu HTML email), Resend (envoi), GitHub Actions (cron).
**Ce projet n'envoie jamais directement à la liste** — uniquement un brouillon à `EMAIL_TO` (par défaut `valere.arnaud@gmail.com`) avec le HTML en pièce jointe.

## Architecture

- `generate.py` — logique complète : fetch des données, catégorisation, rendu, archivage, envoi.
- `template.html.j2` — template Jinja2 qui reproduit la charte éditoriale (fonts Plus Jakarta Sans / Space Grotesk / DM Sans, sections numérotées N°01…).
- `.github/workflows/newsletter-mensuelle.yml` — cron `0 7 1 * *` (UTC) + déclenchement manuel (`workflow_dispatch`).

### Sources de données (repo privé `arnov8/cabinetlaurentvalere`)

Fetch authentifié via `CABINETLV_DATA_TOKEN` (header `Authorization: token`) sur `raw.githubusercontent.com` :
- `data/biens.json` — biens en vente
- `data/articles.json` — articles de blog (le plus récent par `datePublication` est mis en avant → rotation naturelle chaque mois)
- `data/avis-google.json` — avis Google (fichier **maintenu manuellement par Arnaud**, on ne fait que le lire, jamais le modifier/scraper)

### Logique de sélection (100 % automatique, sans curation manuelle)

- Sections : **Appartements** (`type == appartement`) et **Villas & investissements** (`villa`/`terrain`/`immeuble`/`local`), triées par prix croissant, plafonnées à `MAX_PER_SECTION = 3` biens "normaux" chacune (constante en tête de `generate.py`).
- Carte **highlight "★ À ne pas manquer"** : le bien portant le label `coup-de-coeur` (s'il existe), affiché en plus dans sa section d'origine.
- Article de blog : le plus récent publié.
- Avis Google : les 3 premiers de `avis-google.json` (déjà triés du plus récent au plus ancien).
- Stat "à partir de" du hero : prix le plus bas parmi les biens sélectionnés du mois.

### Secrets GitHub Actions (repo `newsletter-clv-mensuelle`)

| Secret | Valeur / origine |
|---|---|
| `CABINETLV_DATA_TOKEN` | Token GitHub CLI d'Arnaud (scope `repo`) — **large** (accès à tous ses repos), pas un fine-grained PAT scoppé lecture seule. À resserrer un jour si besoin via `gh secret set`. |
| `RESEND_API_KEY` | Réutilisée depuis les env vars Vercel du projet `cabinetlaurentvalere` (déjà validée sur le domaine `contact@cabinetlaurentvalere.com`). |
| `EMAIL_TO` / `EMAIL_FROM` | `valere.arnaud@gmail.com` / `contact@cabinetlaurentvalere.com` |

---

## Chronologie des tâches réalisées

### Session du 19 août 2026 — Finalisation complète du pipeline (jamais fonctionnel avant)

**État trouvé** : un seul commit du 12/05/2026, jamais retouché ni déployé.
- `generate.py` fetchait `biens.json` sans authentification sur le repo `cabinetlaurentvalere` — **repo privé → 404 garanti**, le script n'avait donc jamais pu tourner en réel.
- Aucun serveur Hetzner configuré malgré la mention en commentaire du code (`run.sh` supprimé, jamais déployé nulle part).
- `template.html.j2` reprenait le style "bento cards" de mai 2026 (dégradés teal/bleu, emojis), obsolète par rapport à la charte éditoriale en usage depuis (vue dans `newsletter-aout-2026-v2.html` : sections numérotées, encart croisé DocUrbanisme, avis Google réels, CTA vendeur avec photo).

**Travail effectué** :
1. Réécriture de `generate.py` : fetch authentifié (PAT), nouvelle catégorisation par type de bien, sélection auto de la carte coup de cœur / de l'article de blog / des avis Google.
2. Réécriture intégrale de `template.html.j2` pour matcher la charte d'août 2026.
3. Ajout du workflow GitHub Actions (`.github/workflows/newsletter-mensuelle.yml`) — choisi plutôt qu'un VPS Hetzner car le repo est **public** (minutes Actions illimitées et gratuites).
4. Secrets configurés sur le repo (voir tableau ci-dessus), clé Resend récupérée depuis Vercel plutôt que recréée.
5. **Vérification de bout en bout réussie** : run local + run réel `workflow_dispatch` sur GitHub Actions (`32275135343`) → email de brouillon effectivement reçu par Arnaud, avec sélection dynamique confirmée (l'article mis en avant a changé entre deux tests à 7 min d'intervalle suite à la publication d'un nouvel article sur le site).

**Statut** : ✅ pipeline terminé, testé en conditions réelles, cron actif pour le 1er de chaque mois.
