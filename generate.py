#!/usr/bin/env python3
"""
Pipeline newsletter mensuel — Cabinet Laurent Valère
Fetch biens.json → génère HTML → archive sur serveur → envoie par email (Resend)
Cron : 0 7 1 * * /opt/newsletter-clv-mensuelle/run.sh
"""

import base64
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import jinja2
import resend

# ── Config ────────────────────────────────────────────────────────────────────
BIENS_JSON_URL = (
    "https://raw.githubusercontent.com/arnov8/cabinetlaurentvalere/main/data/biens.json"
)
SITE_BASE = "https://www.cabinetlaurentvalere.com"
ARCHIVE_PATH = Path(os.environ.get("ARCHIVE_PATH", "/srv/newsletters"))
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "valere.arnaud@gmail.com")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "contact@cabinetlaurentvalere.com")

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
    "nouveau": "🔥 Nouveau",
    "coup-de-coeur": "❤️ Coup de cœur",
    "vue-mer": "🌊 Vue mer",
    "piscine": "🏊 Piscine",
    "neuf": "✨ Neuf",
    "prestige": "💎 Prestige",
    "architecte": "✨ Architecte",
    "lumineux": "☀️ Lumineux",
    "rare": "💎 Rare",
    "investissement": "📈 Invest.",
}

TYPE_DISPLAY = {
    "appartement": "🏘️ Appartement",
    "villa": "🏡 Villa",
    "terrain": "🌿 Terrain",
    "immeuble": "🏢 Immeuble",
    "local": "🏪 Local",
}


# ── Helpers exposés au template ───────────────────────────────────────────────
def get_badge(bien: dict) -> str:
    for lbl in bien.get("labels", []):
        if lbl in LABEL_DISPLAY:
            return LABEL_DISPLAY[lbl]
    return TYPE_DISPLAY.get(bien.get("type", ""), "🏠 Bien")


def get_image_url(bien: dict) -> str:
    imgs = bien.get("images", [])
    path = imgs[0] if imgs else "/images/biens/placeholder.jpg"
    return path if path.startswith("http") else SITE_BASE + path


def get_prix_display(bien: dict) -> str:
    prix = int(bien.get("prix", 0))
    # Séparateur milliers : espace fine insécable + signe euro insécable
    return f"{prix:,}".replace(",", " ") + " €"


def get_commune_display(bien: dict) -> str:
    slug = bien.get("commune", "")
    name = COMMUNE_DISPLAY.get(slug, slug.replace("-", " ").title())
    quartier = bien.get("quartier")
    return f"{name}, {quartier}" if quartier else name


def get_surface_line(bien: dict) -> str:
    parts = []
    if s := bien.get("surfaceHabitable"):
        parts.append(f"{s} m²")
    if ch := bien.get("chambres"):
        parts.append(f"{ch} ch.")
    if (sdb := bien.get("sallesEau")) and sdb > 1:
        parts.append(f"{sdb} SDB")
    if st := bien.get("surfaceTerrain"):
        parts.append(f"{st:,} m² terrain".replace(",", " "))
    if "piscine" in bien.get("caracteristiques", []):
        parts.append("Piscine")
    return " · ".join(parts)


def get_wa_url(bien: dict) -> str:
    titre = bien.get("titre", "Bien")[:40]
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
    if len(desc) <= 320:
        return desc
    chunk = desc[:320]
    cut = chunk.rfind(". ")
    if cut > 150:
        return chunk[: cut + 1]
    return chunk[: chunk.rfind(" ")] + "…"


def get_titre_display(bien: dict) -> str:
    titre = bien.get("titre", "")
    # Convertit les titres tout-caps en title case
    return titre.title() if titre and titre == titre.upper() else titre


# ── Catégorisation ────────────────────────────────────────────────────────────
def categorize(biens: list) -> tuple:
    actifs = [b for b in biens if b.get("statut") == "a-vendre"]
    opportunites = sorted(
        [b for b in actifs if b.get("prix", 0) < 350_000],
        key=lambda x: x.get("prix", 0),
    )
    villas = sorted(
        [b for b in actifs if 350_000 <= b.get("prix", 0) < 600_000],
        key=lambda x: x.get("prix", 0),
    )
    prestige = sorted(
        [b for b in actifs if b.get("prix", 0) >= 600_000],
        key=lambda x: x.get("prix", 0),
    )
    return opportunites, villas, prestige


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now()
    mois_num = now.month
    year = now.year
    mois_slug = MOIS_FR[mois_num]
    mois_cap = mois_slug.capitalize()
    campaign = f"{mois_slug}-{year}"

    print(f"[{now:%Y-%m-%d %H:%M}] Génération newsletter {mois_cap} {year}")

    with urllib.request.urlopen(BIENS_JSON_URL, timeout=30) as resp:
        raw = json.loads(resp.read())
    biens_list = raw.get("biens", raw) if isinstance(raw, dict) else raw

    opportunites, villas, prestige = categorize(biens_list)
    total = len(opportunites) + len(villas) + len(prestige)
    print(f"  → {len(opportunites)} opportunités | {len(villas)} villas | {len(prestige)} prestige ({total} biens)")

    sample = (opportunites + villas + prestige)[:3]
    preheader = " · ".join(
        f"{get_titre_display(b)[:25]} {get_prix_display(b)}" for b in sample
    ) + f" — {total} biens sélectionnés ce mois-ci."

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
        get_badge=get_badge,
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
        opportunites=opportunites,
        villas=villas,
        prestige=prestige,
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
  <li>{len(opportunites)} opportunité(s) — moins de 350&nbsp;000&nbsp;€</li>
  <li>{len(villas)} villa(s) — 350&nbsp;000&nbsp;€ → 600&nbsp;000&nbsp;€</li>
  <li>{len(prestige)} prestige — plus de 600&nbsp;000&nbsp;€</li>
</ul>
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
