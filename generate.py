#!/usr/bin/env python3
"""
Pipeline newsletter mensuel — Cabinet Laurent Valère
Fetch biens/articles/avis (repo privé cabinetlaurentvalere) → génère HTML (charte août 2026)
→ archive → envoie un brouillon par email (Resend) pour relecture avant chargement dans Listmonk.
Cron : 0 7 1 * * (GitHub Actions, voir .github/workflows/newsletter-mensuelle.yml)
"""

import base64
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import jinja2
import resend

# ── Config ────────────────────────────────────────────────────────────────────
DATA_REPO = "arnov8/cabinetlaurentvalere"
CABINETLV_DATA_TOKEN = os.environ.get("CABINETLV_DATA_TOKEN", "")
SITE_BASE = "https://www.cabinetlaurentvalere.com"
ARCHIVE_PATH = Path(os.environ.get("ARCHIVE_PATH", "/srv/newsletters"))
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "valere.arnaud@gmail.com")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "contact@cabinetlaurentvalere.com")

MAX_PER_SECTION = 3  # nombre de biens "normaux" affichés par section (hors carte coup de cœur)

MOIS_FR = {
    1: "janvier", 2: "février", 3: "mars", 4: "avril",
    5: "mai", 6: "juin", 7: "juillet", 8: "août",
    9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre",
}

COMMUNE_DISPLAY = {
    "fort-de-france": "Fort-de-France",
    "le-marin": "Le Marin",
    "trois-ilets": "Trois-Îlets",
    "schoelcher": "Schœlcher",
    "le-vauclin": "Le Vauclin",
    "ducos": "Ducos",
    "le-lamentin": "Le Lamentin",
    "sainte-anne": "Sainte-Anne",
    "saint-joseph": "Saint-Joseph",
    "le-robert": "Le Robert",
    "riviere-pilote": "Rivière-Pilote",
    "sainte-marie": "Sainte-Marie",
    "le-francois": "Le François",
    "saint-esprit": "Saint-Esprit",
    "trinite": "La Trinité",
    "case-pilote": "Case-Pilote",
    "le-carbet": "Le Carbet",
    "saint-pierre": "Saint-Pierre",
    "marigot": "Marigot",
    "sainte-luce": "Sainte-Luce",
    "riviere-salee": "Rivière-Salée",
    "les-anses-darlets": "Les Anses-d'Arlet",
}

LABEL_DISPLAY = {
    "nouveau": "Nouveau",
    "coup-de-coeur": "Coup de cœur",
    "vue-mer": "Vue mer",
    "piscine": "Piscine",
    "neuf": "Neuf",
    "prestige": "Prestige",
    "architecte": "Architecte",
    "lumineux": "Lumineux",
    "rare": "Rare",
    "investissement": "Investissement",
}

TYPE_DISPLAY = {
    "appartement": "Appartement",
    "villa": "Villa",
    "terrain": "Terrain",
    "immeuble": "Immeuble",
    "local": "Local",
}

CATEGORIE_ARTICLE_DISPLAY = {
    "prix": "Analyse du marché",
    "conseils": "Conseils",
    "financement": "Financement",
    "vente": "Vente",
    "succession": "Succession",
    "fiscalite": "Fiscalité",
    "urbanisme": "Urbanisme",
    "notaire": "Notaire",
    "estimation": "Estimation",
    "promesse": "Promesse de vente",
}

APPARTEMENT_TYPES = {"appartement"}
VILLA_TYPES = {"villa", "terrain", "immeuble", "local"}


# ── Fetch données (repo privé) ─────────────────────────────────────────────────
def fetch_data_json(path: str):
    url = f"https://raw.githubusercontent.com/{DATA_REPO}/main/{path}"
    req = urllib.request.Request(url)
    if CABINETLV_DATA_TOKEN:
        req.add_header("Authorization", f"token {CABINETLV_DATA_TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


# ── Helpers biens ────────────────────────────────────────────────────────────
def get_badge_text(bien: dict) -> str:
    for lbl in bien.get("labels", []):
        if lbl in LABEL_DISPLAY:
            return LABEL_DISPLAY[lbl]
    return TYPE_DISPLAY.get(bien.get("type", ""), "Bien")


def get_image_url(bien: dict) -> str:
    imgs = bien.get("images", [])
    path = imgs[0] if imgs else "/images/biens/placeholder.jpg"
    return path if path.startswith("http") else SITE_BASE + path


def get_prix_display(bien: dict) -> str:
    prix = int(bien.get("prix", 0))
    display = f"{prix:,}".replace(",", " ") + " €"
    if bien.get("prixLabel"):
        display += f" {bien['prixLabel']}"
    return display


def get_commune_display(bien: dict) -> str:
    slug = bien.get("commune", "")
    name = COMMUNE_DISPLAY.get(slug, slug.replace("-", " ").title())
    quartier = bien.get("quartier")
    return f"{name}, {quartier}" if quartier else name


def get_surface_line(bien: dict) -> str:
    parts = []
    if s := bien.get("surfaceHabitable"):
        parts.append(f"{s} m²")
    if ch := bien.get("chambres"):
        parts.append(f"{ch} ch.")
    if (sdb := bien.get("sallesEau")) and sdb > 1:
        parts.append(f"{sdb} SDB")
    if st := bien.get("surfaceTerrain"):
        parts.append(f"{st:,} m² terrain".replace(",", " "))
    if "piscine" in bien.get("caracteristiques", []):
        parts.append("Piscine")
    return " · ".join(parts)


def get_wa_url(bien: dict) -> str:
    titre = get_titre_display(bien)[:40]
    prix = int(bien.get("prix", 0))
    msg = urllib.parse.quote(f"Bonjour, {titre} {prix} EUR")
    return f"https://wa.me/596696334700?text={msg}"


def get_bien_url(bien: dict, campaign: str, content_prefix: str) -> str:
    slug = bien.get("slug") or bien.get("id", "")
    return (
        f"https://cabinetlaurentvalere.com/achat/{slug}"
        f"?utm_source=newsletter&utm_medium=email"
        f"&utm_campaign={campaign}&utm_content={content_prefix}-{slug}"
    )


def get_short_desc(bien: dict) -> str:
    desc = bien.get("description", "").strip()
    if not desc:
        return ""
    paragraph = desc.split("\n\n")[0].strip()
    if len(paragraph) <= 280:
        return paragraph
    chunk = paragraph[:280]
    cut = chunk.rfind(". ")
    if cut > 120:
        return chunk[: cut + 1]
    return chunk[: chunk.rfind(" ")] + "…"


def get_titre_display(bien: dict) -> str:
    titre = bien.get("titre", "")
    if not titre or titre != titre.upper():
        return titre
    display = titre.title()
    # "3ÈME" -> title() -> "3Ème" (une majuscule après un chiffre) : on corrige les ordinaux (3ème, 1er…)
    return re.sub(r"(\d)([A-ZÀ-Ÿ])", lambda m: m.group(1) + m.group(2).lower(), display)


# ── Catégorisation biens + sélection de la carte "coup de cœur" ───────────────
def build_cards(biens: list) -> tuple:
    actifs = [b for b in biens if b.get("statut") == "a-vendre"]

    highlight = next((b for b in actifs if "coup-de-coeur" in b.get("labels", [])), None)
    reste = [b for b in actifs if b is not highlight]

    appartements = sorted(
        [b for b in reste if b.get("type") in APPARTEMENT_TYPES],
        key=lambda b: b.get("prix", 0),
    )[:MAX_PER_SECTION]
    villas = sorted(
        [b for b in reste if b.get("type") in VILLA_TYPES],
        key=lambda b: b.get("prix", 0),
    )[:MAX_PER_SECTION]

    num = 0
    appartement_cards = []
    for b in appartements:
        num += 1
        appartement_cards.append({"bien": b, "num": num, "highlight": False})
    if highlight and highlight.get("type") in APPARTEMENT_TYPES:
        num += 1
        appartement_cards.append({"bien": highlight, "num": num, "highlight": True})

    villa_cards = []
    for b in villas:
        num += 1
        villa_cards.append({"bien": b, "num": num, "highlight": False})
    if highlight and highlight.get("type") in VILLA_TYPES:
        num += 1
        villa_cards.append({"bien": highlight, "num": num, "highlight": True})

    return appartement_cards, villa_cards


# ── Article de blog (change chaque mois selon le dernier article publié) ──────
def strip_markdown_bold(text: str) -> str:
    return text.replace("**", "")


def select_article(articles: list, campaign: str):
    publies = [a for a in articles if a.get("datePublication") and a.get("contenu")]
    if not publies:
        return None
    article = max(publies, key=lambda a: a["datePublication"])
    contenu = strip_markdown_bold(article["contenu"].split("\n\n")[0].strip())
    excerpt = contenu if len(contenu) <= 320 else contenu[:320].rsplit(" ", 1)[0] + "…"
    image_path = article.get("image", "")
    image_url = image_path if image_path.startswith("http") else SITE_BASE + image_path
    url = (
        f"{SITE_BASE}/infos-conseils/{article['slug']}"
        f"?utm_source=newsletter&utm_medium=email&utm_campaign={campaign}&utm_content=card-blog"
    )
    return {
        "titre": article["titre"],
        "categorie": CATEGORIE_ARTICLE_DISPLAY.get(article.get("categorie"), "Conseils"),
        "excerpt": excerpt,
        "temps_lecture": article.get("tempsLecture"),
        "image_url": image_url,
        "url": url,
    }


# ── Avis Google (déjà triés du plus récent au plus ancien) ────────────────────
def select_avis(avis_data: dict) -> dict:
    avis_liste = avis_data.get("avis", [])[:3]
    for a in avis_liste:
        a["initiale"] = (a.get("nom") or "?").strip()[0].upper()
    note_globale = avis_data.get("note_globale", 4.8)
    return {
        "liste": avis_liste,
        "note_globale": f"{note_globale:.1f}".replace(".", ","),
        "nombre_avis": avis_data.get("nombre_avis", len(avis_data.get("avis", []))),
        "lien_google": avis_data.get("lien_google", "https://www.google.fr/maps/place/Cabinet+Laurent+Val%C3%A8re/"),
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now()
    mois_num = now.month
    year = now.year
    mois_slug = MOIS_FR[mois_num]
    mois_cap = mois_slug.capitalize()
    campaign = f"{mois_slug}-{year}"

    print(f"[{now:%Y-%m-%d %H:%M}] Génération newsletter {mois_cap} {year}")

    biens_raw = fetch_data_json("data/biens.json")
    biens_list = biens_raw.get("biens", biens_raw) if isinstance(biens_raw, dict) else biens_raw
    articles_raw = fetch_data_json("data/articles.json")
    articles_list = articles_raw.get("articles", articles_raw) if isinstance(articles_raw, dict) else articles_raw
    avis_raw = fetch_data_json("data/avis-google.json")

    appartement_cards, villa_cards = build_cards(biens_list)
    total = len(appartement_cards) + len(villa_cards)
    print(f"  → {len(appartement_cards)} appartements | {len(villa_cards)} villas/investissements ({total} biens)")

    article = select_article(articles_list, campaign)
    if article:
        print(f"  → Article : {article['titre']}")

    avis = select_avis(avis_raw)

    all_cards = appartement_cards + villa_cards
    sample = [c["bien"] for c in all_cards][:3]
    preheader = " · ".join(
        f"{get_titre_display(b)[:25]} {get_prix_display(b)}" for b in sample
    ) + f" — {total} biens sélectionnés ce mois-ci."

    prix_min = min((c["bien"].get("prix", 0) for c in all_cards), default=0)
    prix_min_display = f"{int(prix_min // 1000)} k€" if prix_min else "—"

    # Rendu Jinja2
    tpl_dir = Path(__file__).parent
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(tpl_dir)),
        autoescape=jinja2.select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals.update(
        get_image_url=get_image_url,
        get_prix_display=get_prix_display,
        get_badge_text=get_badge_text,
        get_commune_display=get_commune_display,
        get_surface_line=get_surface_line,
        get_wa_url=get_wa_url,
        get_bien_url=get_bien_url,
        get_short_desc=get_short_desc,
        get_titre_display=get_titre_display,
    )

    html = env.get_template("template.html.j2").render(
        mois=mois_cap,
        mois_slug=mois_slug,
        year=year,
        campaign=campaign,
        preheader=preheader,
        appartement_cards=appartement_cards,
        villa_cards=villa_cards,
        article=article,
        avis=avis,
        prix_min_display=prix_min_display,
    )

    # Archive locale
    out_dir = ARCHIVE_PATH / "cabinetlaurentvalere" / "email" / f"{mois_slug}-{year}"
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"newsletter-{mois_slug}-{year}.html"
    filepath = out_dir / filename
    filepath.write_text(html, encoding="utf-8")
    print(f"  → Archivé : {filepath}")

    # Envoi email via Resend
    if not RESEND_API_KEY:
        print("  ⚠  RESEND_API_KEY absent — email non envoyé (fichier archivé OK).")
        return

    resend.api_key = RESEND_API_KEY
    r = resend.Emails.send({
        "from": EMAIL_FROM,
        "to": [EMAIL_TO],
        "subject": f"📋 Draft newsletter {mois_cap} {year} — Cabinet Laurent Valère",
        "html": f"""
<p>Bonjour Arnaud,</p>
<p>Le draft de la newsletter <strong>{mois_cap} {year}</strong> est prêt.</p>
<p><strong>{total} biens</strong> sélectionnés automatiquement :</p>
<ul>
  <li>{len(appartement_cards)} appartement(s)</li>
  <li>{len(villa_cards)} villa(s) / investissement(s)</li>
</ul>
<p>Article mis en avant : {article['titre'] if article else '—'}</p>
<p>Le fichier HTML est en pièce jointe. Ouvre-le dans ton navigateur pour vérifier, modifie si besoin, puis charge dans Listmonk pour l'envoi.</p>
<p style="color:#999;font-size:12px;">Archive : {filepath}</p>
""",
        "attachments": [{
            "filename": filename,
            "content": base64.b64encode(html.encode("utf-8")).decode("ascii"),
        }],
    })
    print(f"  → Email envoyé : {r}")


if __name__ == "__main__":
    main()
