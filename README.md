# prix-energie

Décomposition du prix de l'énergie payé par les ménages français depuis 2005 :
carburants routiers et électricité, poste par poste, en euros courants et en euros
constants, à partir des seules sources publiques.

Le projet produit un dossier détaillé, une synthèse courte, et les séries qui les
alimentent. Tout est recalculable : les CSV publiés viennent des mêmes scripts que les
figures.

## Installer

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
```

## Lancer

```sh
python -m prix_energie build            # tout : téléchargement, données, figures, pages
python -m prix_energie build --only figures   # repart des CSV, sans réseau ni parsing
python -m prix_energie pages            # réassemble seulement les pages
pytest                                  # tests
```

`data/` est versionné, `site/` ne l'est pas. Les figures se déduisent des CSV, donc les
verser dans l'historique y ferait entrer sept mégaoctets à chaque mise à jour mensuelle
sans rien apporter. La forge reconstruit le site depuis `data/` à chaque poussée et le
publie, sauf si `build` s'arrête en erreur (code 4) parce que le site serait incomplet :
une figure ou une image du fil inscrite dans `viz/catalogue.py` qui n'a pas été
produite, une image produite qui n'y figure pas, ou un marqueur `{{fig:...}}` de
`contenu/` qui appelle une figure introuvable.

`build` rappelle `pages` à la fin : les pages reprennent des tableaux et des valeurs lus
dans les CSV, donc régénérer les données sans réassembler laisserait des pages périmées
sans que rien ne le signale.

Options utiles de `build` :

| option | effet |
|---|---|
| `--offline` | rejoue tout depuis le cache disque, sans réseau |
| `--sur-perte ecraser` | accepte un CSV dont la nouvelle version perd des lignes |
| `--csv-dialect excel-fr` | point-virgule et virgule décimale, pour ouvrir dans Excel |
| `--xlsx` | régénère le classeur, qui n'est plus produit par défaut |

## Organisation

```
src/prix_energie/
├── donnees/      ce qui entre et ce qui sort
│   ├── sources/  un module par producteur : WOB, DGEC, INSEE, Eurostat, CRE…
│   ├── contracts.py  ce qu'une source doit fournir pour être acceptée
│   ├── guard.py      refus d'écraser un CSV qui perdrait des données
│   ├── tidy.py       lecture et écriture des CSV
│   ├── excel.py      export du classeur
│   └── fetch.py      téléchargement avec cache disque
├── modele/       le calcul
│   ├── assemblage.py     construit le Bundle à partir des sources
│   └── decomposition.py  décomposition du prix, déflation, remise 2022
├── viz/          tout ce qui dessine
│   ├── style.py  la palette, partagée par le dossier et le fil
│   ├── figures/  le registre et cinq modules : communs, empilements, courbes, dispersion, controle
│   ├── feed.py       second jeu, format timeline
│   ├── carrousel.py  les images du fil en un PDF
│   └── catalogue.py  la liste des figures que le site doit contenir
├── bundle.py     le contrat de données, qui n'appartient à aucune couche
├── journal.py    le logger et le journal publié dans le dossier
├── common.py     utilitaires : TVA, dates, repérage de tables
├── config.py
└── cli/          pipeline.py, pages.py
contenu/          le texte, en HTML ordinaire
tests/            non-régression, architecture, débordements de texte
data/             les séries normalisées, versionnées
site/             le site produit, reconstruit par la forge, non versionné
```

Le texte vit dans `contenu/`, pas dans le code. `pages` y remplace des marqueurs :
`{{fig:nom}}` insère une figure numérotée, `{{sources}}` et `{{notes}}` déroulent des
tableaux construits à partir du journal d'exécution, `{{calculette}}` insère un bloc de
calcul du coût annuel par motorisation.

## Conventions de lecture des figures

Un trait noir tireté vertical marque un changement de définition : on ne compare plus
la même chose de part et d'autre. Un trait gris fin marque un simple changement de
source. Une courbe en pointillé porte une valeur reconstituée, jamais une valeur
mesurée.

## Ce que les données ne permettent pas

La marge de raffinage est publiée en un seul chiffre, pas par carburant : il n'est donc
pas possible de séparer ce qui revient au raffineur de ce qui revient au distributeur.
L'accise est déduite par solde, et non lue au barème, ce qui la rend sensible à toute
erreur sur le couple hors-taxes / prix payé. Le coût de transport-distribution est
annuel et reconduit en cours d'année. Le dossier reprend ces limites là où elles pèsent
sur une conclusion.

## Sources

Weekly Oil Bulletin de la Commission européenne, direction générale de l'énergie et du
climat, INSEE pour le Brent et l'indice des prix, Eurostat et Commission de régulation
de l'énergie pour l'électricité, data.economie.gouv.fr pour les prix par station.
