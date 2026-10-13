"""Assemble les pages du dossier à partir des fichiers de contenu, des CSV et des figures.

Le texte n'est pas ici : il est dans `contenu/dossier.html` (le dossier détaillé),
`contenu/synthese.html` (la version courte) et `contenu/accueil.html`, que l'on édite
comme du HTML ordinaire. Ce script ne fait que remplacer des marqueurs et habiller le
résultat.

Marqueurs reconnus :

    {{fig:nom}}              insère la figure sortie/figures/nom.png
    {{fig:nom|Légende}}      idem, avec un titre au-dessus
    {{limite}} … {{/limite}} encart « limite assumée »
    {{sources}}              tableau des sources, lu dans _sources.csv
    {{notes}}                tableau du journal, lu dans _notes.csv
    {{calculette}}           bloc de calcul du coût annuel par motorisation

Chaque contenu donne une page du site, dont les images sont référencées :

    site/prix_energie.html   dossier détaillé
    site/synthese.html       synthèse
    site/index.html          accueil

Usage :  python -m prix_energie pages
"""
from __future__ import annotations

import html
import json
import re
import shutil
import unicodedata
from pathlib import Path

import pandas as pd

from prix_energie.chemins import CONTENU as DOSSIER_CONTENU
from prix_energie.chemins import DONNEES, FIGURES, RACINE, SITE
SORTIE = SITE
FIGS = FIGURES
CONTENU = DOSSIER_CONTENU / "dossier.html"
SYNTHESE = DOSSIER_CONTENU / "synthese.html"
ACCUEIL = DOSSIER_CONTENU / "accueil.html"


class SiteIncomplet(RuntimeError):
    """Le site publié serait incomplet : on s'arrête plutôt que de le livrer."""


TITRE = "Anatomie d'un prix de l'énergie"
SOUS_TITRE = ("Ce que paient les ménages français pour un litre de carburant et un "
              "kilowattheure d'électricité, d'où vient chaque centime, et ce qui a fait "
              "bouger ces prix. Toutes les séries proviennent de statistiques publiques ; "
              "ce qui manque est dit.")

# Version courte, pour qui n'ouvrira jamais les cinquante figures du dossier.
TITRE_SYNTHESE = "Carburants et électricité : ce qui a changé depuis 2005"
SOUS_TITRE_SYNTHESE = ("Le carburant n'a jamais coûté autant d'euros. Les taxes baissent "
                       "depuis 2018 et le pétrole est moins cher qu'en 2013 : la hausse "
                       "vient d'ailleurs.")

# Page d'accueil : la seule que GitHub Pages sert à la racine du dépôt.
TITRE_ACCUEIL = "Anatomie d'un prix de l'énergie"
SOUS_TITRE_ACCUEIL = ("Ce que paient les ménages français pour un litre de carburant et "
                      "un kilowattheure, poste par poste, depuis 2005. Données, méthode "
                      "et limites.")


# --------------------------------------------------------------------------- tableaux
def _table(csv: str, colonnes: list[tuple[str, str]], tri: dict | None = None) -> str:
    df = pd.read_csv(DONNEES / csv)
    if tri:
        df = df.assign(_o=df["Type"].map(tri).fillna(9)).sort_values(["_o", "Série"])
    lignes = []
    for _, r in df.iterrows():
        cells = []
        for col, classe in colonnes:
            v = str(r[col])
            if col == "Producteur" and str(r.get("URL", "")).startswith("http"):
                v = f'<a href="{html.escape(str(r["URL"]))}">{html.escape(v)}</a>'
            elif col == "Type":
                v = f'<span class="tag tag-{v.lower()}">{html.escape(v)}</span>'
            else:
                v = html.escape(v)
            cells.append(f'<td class="{classe}">{v}</td>' if classe else f"<td>{v}</td>")
        lignes.append("<tr>" + "".join(cells) + "</tr>")
    entetes = "".join(f"<th>{c}</th>" for c, _ in colonnes)
    return (f'<div class="scroll"><table><thead><tr>{entetes}</tr></thead>'
            f'<tbody>{"".join(lignes)}</tbody></table></div>')


def table_sources() -> str:
    return _table("_sources.csv", [("Série", ""), ("Producteur", ""), ("Détail", "detail")])


def table_notes() -> str:
    ordre = {"INDISPONIBLE": 0, "RUPTURE": 1, "PROVISOIRE": 2, "DEFINITION": 3, "METHODE": 4}
    return _table("_notes.csv", [("Type", ""), ("Série", ""), ("Message", "detail")], ordre)


# --------------------------------------------------------------------------- calculette
def calculette() -> str:
    """Bloc de calcul : le lecteur saisit ses chiffres, la page recalcule.

    Les derniers prix connus sont figés dans la page au moment du build : le bloc
    fonctionne sans réseau et sans serveur, donc aussi bien dans un article WordPress
    qu'en fichier local.
    """
    cfg = {"essence": 6.5, "diesel": 5.5, "ve": 18.0, "km": 12000}
    sp = pd.read_csv(DONNEES / "carburants_sansplomb_mensuel.csv").dropna(subset=["ttc"])
    gz = pd.read_csv(DONNEES / "carburants_gazole_mensuel.csv").dropna(subset=["ttc"])
    el = pd.read_csv(DONNEES / "electricite_mensuel_prolonge.csv").dropna(subset=["ttc"])
    prix = {"sp": float(sp["ttc"].iloc[-1]), "gz": float(gz["ttc"].iloc[-1]),
            "el": float(el["ttc"].iloc[-1]), "mois": str(sp["mois"].iloc[-1])[:7]}
    data = json.dumps({**cfg, **prix})
    return f"""
<div class="calc" id="calc">
  <h4>Et pour vous ?</h4>
  <p class="calc-intro">Les kilomètres d'abord, puis la consommation de chaque
  motorisation. Le calcul se refait avec les derniers prix connus ({prix['mois']}).</p>

  <label class="calc-km" for="calc-km">Kilomètres par an
    <input type="number" id="calc-km" value="{cfg['km']}" min="0" step="500"></label>

  <div class="calc-grille">
    <div class="calc-entete">
      <span>Motorisation</span><span>Consommation</span><span>Coût annuel</span><span>Écart</span>
    </div>
    <div class="calc-ligne" data-cle="essence">
      <span class="calc-nom">Essence</span>
      <label class="calc-hyp"><input type="number" id="calc-essence" value="{cfg['essence']}"
        min="0" step="0.1"><span>l/100 km</span></label>
      <span class="calc-val" id="val-essence"></span>
      <span class="calc-ecart" id="ecart-essence"></span>
    </div>
    <div class="calc-ligne" data-cle="diesel">
      <span class="calc-nom">Gazole</span>
      <label class="calc-hyp"><input type="number" id="calc-diesel" value="{cfg['diesel']}"
        min="0" step="0.1"><span>l/100 km</span></label>
      <span class="calc-val" id="val-diesel"></span>
      <span class="calc-ecart" id="ecart-diesel"></span>
    </div>
    <div class="calc-ligne" data-cle="ve">
      <span class="calc-nom">Électrique</span>
      <label class="calc-hyp"><input type="number" id="calc-ve" value="{cfg['ve']}"
        min="0" step="0.5"><span>kWh/100 km</span></label>
      <span class="calc-val" id="val-ve"></span>
      <span class="calc-ecart" id="ecart-ve"></span>
    </div>
  </div>
  <p class="calc-note">Recharge à domicile au tarif réglementé. Hors achat, entretien
  et assurance.</p>
</div>
<script>
(function () {{
  var D = {data};
  var LIG = [
    {{cle: "essence", prix: D.sp}},
    {{cle: "diesel", prix: D.gz}},
    {{cle: "ve", prix: D.el}}
  ];
  function val(id) {{
    var el = document.getElementById("calc-" + id);
    return parseFloat(el && el.value) || 0;
  }}
  function euro(v) {{
    return v.toLocaleString("fr-FR", {{maximumFractionDigits: 0}}) + " €";
  }}
  function calc() {{
    var cent = val("km") / 100;
    var couts = LIG.map(function (l) {{ return cent * val(l.cle) * l.prix / 100; }});
    var mini = Math.min.apply(null, couts);
    LIG.forEach(function (l, i) {{
      document.getElementById("val-" + l.cle).textContent = euro(couts[i]);
      var e = couts[i] - mini;
      document.getElementById("ecart-" + l.cle).textContent =
        e < 1 ? "le moins cher" : "+" + euro(e);
      var ligne = document.querySelector('.calc-ligne[data-cle="' + l.cle + '"]');
      if (ligne) {{ ligne.classList.toggle("calc-mini", e < 1); }}
    }});
  }}
  ["km", "essence", "diesel", "ve"].forEach(function (k) {{
    var el = document.getElementById("calc-" + k);
    if (el) {{ el.addEventListener("input", calc); }}
  }});
  calc();
}})();
</script>"""


# --------------------------------------------------------------------------- assemblage
def _ancre(txt: str) -> str:
    """Identifiant stable tiré d'un intitulé, pour pouvoir y pointer."""
    t = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode().lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", t)).strip("-")


def rendre(contenu: str, src_figure) -> str:
    """Remplace les marqueurs de contenu.html par leur contenu réel.

    Chaque figure reçoit un numéro d'ordre et une ancre : on peut ainsi désigner
    « figure 12 » sans ambiguïté et pointer directement dessus.
    """
    compteur = {"n": 0}

    def fig(m: re.Match) -> str:
        nom, _, legende = m.group(1).partition("|")
        src = src_figure(nom.strip())
        if not src:
            # Écrire un commentaire à la place laissait un trou invisible dans la page
            # publiée, et décalait la numérotation de toutes les figures suivantes.
            raise SiteIncomplet(f"marqueur {{{{fig:{nom.strip()}}}}} : figure introuvable")
        compteur["n"] += 1
        n = compteur["n"]
        lg = html.escape(legende.strip())
        titre = (f'<figcaption class="fig-titre"><a href="#fig{n}" class="fig-num">Fig. {n}</a>'
                 + (f"<span>{lg}</span>" if lg else "") + "</figcaption>")
        return (f'<figure id="fig{n}">{titre}<img src="{src}" '
                f'alt="Figure {n} : {lg or html.escape(nom.strip())}" loading="lazy"></figure>')

    contenu = re.sub(r"\{\{fig:([^}]+)\}\}", fig, contenu)

    def h3(m: re.Match) -> str:
        t = m.group(1)
        a = _ancre(t)
        return f'<h3 id="{a}"><a href="#{a}">{t}</a></h3>'

    contenu = re.sub(r"<h3>(.*?)</h3>", h3, contenu)
    contenu = contenu.replace("{{limite}}", '<aside class="limite"><h4>Limite assumée</h4>')
    contenu = contenu.replace("{{/limite}}", "</aside>")
    contenu = contenu.replace("{{sources}}", table_sources())
    contenu = contenu.replace("{{notes}}", table_notes())
    contenu = contenu.replace("{{calculette}}", calculette())
    return contenu


CSS = """
:root{--ground:#f6f7f9;--surface:#fff;--surface-2:#eef1f5;--ink:#14171a;--ink-2:#4a5158;
--ink-3:#7b848c;--rule:#dde2e8;--accent:#2a78d6;--accent-soft:#e9f0fb;--warn:#b4541f;
--serif:"Spectral",Georgia,serif;--sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
--mono:"IBM Plex Mono",ui-monospace,monospace;--lisible:68ch}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--ground:#0f1215;--surface:#161a1e;
--surface-2:#1d2328;--ink:#eef1f4;--ink-2:#aab3bb;--ink-3:#7b848c;--rule:#252b31;
--accent:#6aa4ea;--accent-soft:#17212e;--warn:#e0925f}}
:root[data-theme="dark"]{--ground:#0f1215;--surface:#161a1e;--surface-2:#1d2328;--ink:#eef1f4;
--ink-2:#aab3bb;--ink-3:#7b848c;--rule:#252b31;--accent:#6aa4ea;--accent-soft:#17212e;--warn:#e0925f}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
font-size:16px;line-height:1.62;-webkit-font-smoothing:antialiased}
.wrap{max-width:1160px;margin:0 auto;padding:0 24px}
.nav{display:flex;flex-wrap:wrap;gap:22px;padding-top:24px;font-size:.92rem}
.nav a{color:var(--ink-2);text-decoration:none}.nav a:hover{color:var(--accent)}
.nav a[aria-current]{color:var(--ink);font-weight:600}
.masthead{padding-block:72px 40px;border-bottom:1px solid var(--rule)}
.masthead h1{font-family:var(--serif);font-weight:600;font-size:clamp(2.1rem,5vw,3.4rem);
line-height:1.08;letter-spacing:-.015em;margin:0 0 18px;text-wrap:balance;max-width:18ch}
.masthead p{max-width:var(--lisible);color:var(--ink-2);font-size:1.06rem;margin:0}
.meta{display:flex;flex-wrap:wrap;gap:28px;margin-top:34px;font-family:var(--mono);
font-size:.78rem;color:var(--ink-3)}
.meta div{display:flex;flex-direction:column;gap:3px}
.meta b{color:var(--ink);font-weight:500;font-size:.92rem;font-variant-numeric:tabular-nums}
.meta span{text-transform:uppercase;letter-spacing:.09em;font-size:.68rem}
nav.sommaire{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
gap:18px 28px;padding-block:24px;border-bottom:1px solid var(--rule);font-size:.86rem}
.som-groupe{display:flex;flex-direction:column;gap:3px}
.som-h2{color:var(--ink);text-decoration:none;font-weight:600}
.som-h3{color:var(--ink-3);text-decoration:none;font-size:.78rem;padding-left:10px}
nav.sommaire a:hover{color:var(--accent)}
section{scroll-margin-top:20px}h3{scroll-margin-top:20px}
h3 a{color:inherit;text-decoration:none}h3 a:hover{color:var(--accent)}
section{padding-block:60px;border-bottom:1px solid var(--rule)}
section:last-of-type{border-bottom:0}
.eyebrow{font-family:var(--mono);font-size:.72rem;text-transform:uppercase;
letter-spacing:.12em;color:var(--accent);margin:0 0 10px}
h2{font-family:var(--serif);font-weight:600;font-size:clamp(1.5rem,3.2vw,2.1rem);
line-height:1.16;margin:0 0 14px;letter-spacing:-.01em;text-wrap:balance;max-width:var(--lisible)}
h3{font-family:var(--serif);font-size:1.18rem;font-weight:600;margin:38px 0 6px}
.chapo{max-width:var(--lisible);color:var(--ink-2);font-size:1.02rem;margin:0 0 30px}
section p{max-width:var(--lisible);color:var(--ink-2)}
strong{color:var(--ink);font-weight:600}
.formule{font-family:var(--mono);font-size:.9em;background:var(--surface-2);
padding:1px 6px;border-radius:3px;white-space:nowrap}
figure{margin:30px 0;display:flex;flex-direction:column;gap:9px;max-width:1000px}
.fig-titre{font-family:var(--mono);font-size:.74rem;text-transform:uppercase;
letter-spacing:.09em;color:var(--ink-2);font-weight:500;display:flex;gap:10px;align-items:baseline}
.fig-num{color:var(--accent);text-decoration:none;flex:none}
.fig-num:hover{text-decoration:underline}
figure{scroll-margin-top:20px}
figure img{display:block;width:100%;height:auto;background:#fcfcfb;
border:1px solid var(--rule);border-radius:2px}
.limite{max-width:var(--lisible);margin:30px 0;padding:20px 22px;background:var(--surface);
border-left:3px solid var(--warn);border-radius:0 3px 3px 0}
.limite h4{margin:0 0 8px;font-family:var(--mono);font-size:.72rem;text-transform:uppercase;
letter-spacing:.1em;color:var(--warn);font-weight:500}
.limite p{margin:0;font-size:.95rem}
.glossaire{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));
gap:22px 34px;margin:0}
.glossaire div{padding-top:13px;border-top:1px solid var(--rule)}
.glossaire dt{font-family:var(--mono);font-size:.8rem;font-weight:500;color:var(--ink);margin-bottom:5px}
.glossaire dd{margin:0;font-size:.88rem;line-height:1.55;color:var(--ink-2)}
.scroll{overflow-x:auto;margin-top:14px}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th{text-align:left;font-family:var(--mono);font-size:.7rem;text-transform:uppercase;
letter-spacing:.09em;color:var(--ink-3);font-weight:500;padding:0 14px 8px 0;
border-bottom:1px solid var(--rule);white-space:nowrap}
td{padding:11px 14px 11px 0;border-bottom:1px solid var(--rule);vertical-align:top;color:var(--ink)}
td.detail{color:var(--ink-2);font-size:.82rem;line-height:1.5}
td a{color:var(--accent);text-decoration:none}
td a:hover{text-decoration:underline}
.tag{font-family:var(--mono);font-size:.64rem;letter-spacing:.06em;text-transform:uppercase;
padding:2px 7px;border-radius:2px;white-space:nowrap;background:var(--surface-2);color:var(--ink-2)}
.tag-indisponible{background:var(--warn);color:#fff}
.tag-rupture{background:var(--accent-soft);color:var(--accent)}
.calc{max-width:var(--lisible);margin:30px 0;padding:24px;background:var(--surface);
border:1px solid var(--rule);border-radius:4px}
.calc h4{margin:0 0 6px;font-family:var(--serif);font-size:1.15rem;font-weight:600;color:var(--ink)}
.calc-intro{margin:0 0 18px;font-size:.9rem;color:var(--ink-2)}
.calc-km{display:flex;align-items:center;gap:12px;font-size:.85rem;color:var(--ink-2);
padding-bottom:16px;border-bottom:1px solid var(--rule);margin-bottom:6px}
.calc-km input{font-family:var(--mono);font-size:1.05rem;padding:7px 12px;width:11ch;
border:1px solid var(--rule);border-radius:3px;background:var(--ground);color:var(--ink)}
.calc-grille{display:flex;flex-direction:column}
.calc-entete{display:grid;grid-template-columns:1fr 1.5fr 1fr .9fr;gap:14px;
padding:8px 12px;font-family:var(--mono);font-size:.66rem;text-transform:uppercase;
letter-spacing:.08em;color:var(--ink-3)}
.calc-ligne{display:grid;grid-template-columns:1fr 1.5fr 1fr .9fr;gap:14px;
align-items:center;padding:10px 12px;border-radius:3px;border-top:1px solid var(--rule)}
.calc-hyp{display:flex;align-items:center;gap:7px;font-size:.74rem;color:var(--ink-3)}
.calc-hyp input{font-family:var(--mono);font-size:.95rem;padding:6px 10px;width:9ch;
border:1px solid var(--rule);border-radius:3px;background:var(--ground);color:var(--ink)}
.calc-mini{background:var(--accent-soft)}
.calc-nom{font-size:.92rem;color:var(--ink)}
.calc-val{font-family:var(--mono);font-size:1.05rem;font-weight:500;color:var(--ink);
font-variant-numeric:tabular-nums}
.calc-ecart{font-family:var(--mono);font-size:.76rem;color:var(--ink-3);text-align:right}
@media (max-width:620px){.calc-entete{display:none}.calc-ligne{grid-template-columns:1fr 1fr;row-gap:8px}}
.calc-note{margin:16px 0 0;font-size:.78rem;color:var(--ink-3)}
footer{padding-block:44px 64px;color:var(--ink-3);font-size:.82rem;max-width:var(--lisible)}
a:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""


def bandeau() -> str:
    sp = pd.read_csv(DONNEES / "carburants_sansplomb_mensuel.csv")
    el = pd.read_csv(DONNEES / "electricite_mensuel_prolonge.csv")
    d, f = pd.to_datetime(sp["mois"]).min(), pd.to_datetime(sp["mois"]).max()
    fe = pd.to_datetime(el["mois"]).max()
    return (f'<div class="meta">'
            f'<div><span>Carburants</span><b>{d:%Y} → {f:%m/%Y}</b></div>'
            f'<div><span>Électricité</span><b>2007 → {fe:%m/%Y}</b></div>'
            f'<div><span>Producteurs</span><b>INSEE · Eurostat · DGEC · CRE</b></div>'
            f'<div><span>Euros constants</span><b>base 08/2026</b></div></div>')


def sommaire(corps: str) -> str:
    """Sommaire à deux niveaux : les sections, et leurs sous-titres."""
    out = []
    for bloc in re.split(r"(?=<section )", corps):
        m = re.search(r'<section id="([^"]+)">\s*<h2>([^<]+)</h2>', bloc)
        if not m:
            continue
        out.append(f'<div class="som-groupe"><a class="som-h2" href="#{m.group(1)}">'
                   f'{html.escape(m.group(2))}</a>')
        for a, t in re.findall(r'<h3 id="([^"]+)"><a[^>]*>([^<]+)</a></h3>', bloc):
            out.append(f'<a class="som-h3" href="#{a}">{html.escape(t)}</a>')
        out.append("</div>")
    return '<nav class="sommaire">' + "".join(out) + "</nav>"


PAGES = (("index", "Accueil"), ("synthese", "Synthèse"), ("prix_energie", "Dossier complet"))


def navigation(stem: str) -> str:
    """Les trois pages se lient entre elles : un lecteur arrivé par la synthèse depuis
    un post doit pouvoir rejoindre le dossier et les données sans revenir en arrière."""
    liens = (f'<a href="{s}.html"{' aria-current="page"' if s == stem else ''}>{nom}</a>'
             for s, nom in PAGES)
    return f'<nav class="nav">{"".join(liens)}</nav>'


def construire(source: Path, titre: str, sous_titre: str, stem: str,
               avec_sommaire: bool) -> set[str]:
    """Produit une page du site et rend les figures qu'elle cite.

    Le sommaire n'a de sens qu'au-delà de quelques sections : sur une page courte, il
    occupe l'écran d'ouverture sans rien faire gagner au lecteur.
    """
    contenu = source.read_text(encoding="utf-8")

    # Les images sont référencées, pas encodées : elles existent déjà dans
    # site/figures/, et le navigateur ne charge que celles qu'il affiche.
    def chemin(nom: str) -> str:
        return f"{FIGS.name}/{nom}.png" if (FIGS / f"{nom}.png").exists() else ""

    corps = rendre(contenu, chemin)
    doc = f"""<title>{titre}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=Spectral:wght@400;600&display=swap">
<style>{CSS}</style>
<div class="wrap">
{navigation(stem)}
<header class="masthead"><h1>{titre}</h1>{f"<p>{sous_titre}</p>" if sous_titre else ""}{bandeau()}</header>
{sommaire(corps) if avec_sommaire else ""}
{corps}
</div>
"""
    SORTIE.mkdir(parents=True, exist_ok=True)
    cible = SORTIE / f"{stem}.html"
    cible.write_text(doc, encoding="utf-8")
    print(f"{cible.relative_to(RACINE)} : {cible.stat().st_size / 1e6:.2f} Mo")

    return set(re.findall(r"\{\{fig:([^}|]+)", contenu))


def main() -> None:
    # Pas de parseur : la commande n'a plus d'option, et elle est aussi appelée
    # depuis `build`, dont les arguments ne la concernent pas.
    # L'accueil lie les CSV comme des fichiers voisins : ils doivent être publiés avec
    # les pages, sinon chaque lien de données renvoie une 404 sur le site.
    SORTIE.mkdir(parents=True, exist_ok=True)
    for csv in sorted(DONNEES.glob("*.csv")):
        shutil.copy2(csv, SORTIE / csv.name)
    construire(CONTENU, TITRE, SOUS_TITRE, "prix_energie", True)
    if SYNTHESE.exists():
        construire(SYNTHESE, TITRE_SYNTHESE, SOUS_TITRE_SYNTHESE, "synthese", False)
    # index.html est la seule page que GitHub Pages sert à la racine : sans elle,
    # l'URL du dépôt renvoie une 404.
    if ACCUEIL.exists():
        construire(ACCUEIL, TITRE_ACCUEIL, SOUS_TITRE_ACCUEIL, "index", False)
