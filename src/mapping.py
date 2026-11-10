"""Import d'un fichier imparfait (CSV ou Excel) et conversion au format de l'outil.

Étapes :
1. lire le fichier, trouver la ligne d'en-tête, enlever les lignes vides et les totaux ;
2. proposer une correspondance entre ses colonnes et les colonnes attendues :
   - par des synonymes connus (sans IA, toujours disponible),
   - ou par l'IA, qui ne voit que les en-têtes et 5 lignes d'exemple ;
3. l'utilisateur valide ou corrige la correspondance dans l'interface ;
4. le code transforme et vérifie les données (l'IA ne touche jamais aux chiffres).
"""

import json
import re
import unicodedata
import warnings

import pandas as pd

from src.ai_report import appeler_claude
from src.config import COLONNES_ATTENDUES

AUCUNE = "(aucune)"

# Colonnes indispensables : sans elles, le sell-through n'a pas de sens
COLONNES_OBLIGATOIRES = ["point_de_vente", "reference", "qte_vendue"]

# Libellés lisibles pour l'interface
LIBELLES = {
    "semaine": "Semaine / période", "point_de_vente": "Point de vente", "type_pdv": "Type de point de vente",
    "ville": "Ville", "reference": "Référence", "nom_produit": "Nom du produit", "categorie": "Catégorie",
    "couleur": "Couleur", "taille": "Taille", "prix_gros": "Prix de gros", "prix_public": "Prix public",
    "qte_livree": "Quantité livrée", "qte_vendue": "Quantité vendue", "stock_fin_semaine": "Stock",
}

# Noms fréquents dans les exports (comparés sans accents, ni majuscules, ni ponctuation)
SYNONYMES = {
    "semaine": ["semaine", "sem", "week", "wk", "periode", "period", "date", "mois"],
    "point_de_vente": ["point de vente", "pdv", "magasin", "boutique", "store", "door", "client",
                       "revendeur", "retailer", "compte", "account", "enseigne"],
    "type_pdv": ["type pdv", "type de point de vente", "canal", "channel", "type client", "circuit"],
    "ville": ["ville", "city", "localisation", "location"],
    "reference": ["reference", "ref", "sku", "code article", "article", "style", "code produit", "ean", "item"],
    "nom_produit": ["nom produit", "produit", "designation", "libelle", "description", "product", "nom"],
    "categorie": ["categorie", "category", "famille", "family", "rayon", "univers"],
    "couleur": ["couleur", "coloris", "color", "colour"],
    "taille": ["taille", "size", "pointure"],
    "prix_gros": ["prix de gros", "prix gros", "pa", "prix achat", "wholesale", "wholesale price", "pxa"],
    "prix_public": ["prix public", "pvc", "pv", "prix vente", "retail price", "rrp", "msrp", "prix de vente"],
    "qte_livree": ["qte livree", "quantite livree", "livre", "livraison", "livrees", "delivered", "shipped",
                   "sell in", "sellin", "receptions", "recu", "qte recue"],
    "qte_vendue": ["qte vendue", "quantite vendue", "vendu", "ventes", "ventes unites", "sold", "sales units",
                   "sell out", "sellout", "units sold", "vtes"],
    "stock_fin_semaine": ["stock", "stock fin", "stock final", "stock restant", "inventory", "on hand", "soh",
                          "stock magasin"],
}


def normaliser(texte) -> str:
    """'Qté Vendue (S)' -> 'qte vendue s' : minuscules, sans accents ni ponctuation."""
    texte = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", texte.lower()).strip()


# ---------------------------------------------------------------------------
# 1. Lecture du fichier brut
# ---------------------------------------------------------------------------
def _trouver_ligne_entete(brut: pd.DataFrame) -> int:
    """La ligne d'en-tête est, parmi les 15 premières, celle qui a le plus de cellules
    texte remplies (les titres et lignes vides au-dessus sont ignorés)."""
    meilleure_ligne, meilleur_score = 0, -1
    for numero in range(min(15, len(brut))):
        cellules = brut.iloc[numero].dropna()
        score = sum(isinstance(c, str) and not _ressemble_a_un_nombre(c) for c in cellules)
        if score > meilleur_score:
            meilleure_ligne, meilleur_score = numero, score
    return meilleure_ligne


def _ressemble_a_un_nombre(valeur) -> bool:
    return bool(re.fullmatch(r"[\d\s.,€%-]+", str(valeur).strip()))


def lire_fichier(fichier, nom_fichier: str) -> pd.DataFrame:
    """Lit un CSV (séparateur deviné) ou un Excel (première feuille) et le nettoie."""
    if nom_fichier.lower().endswith((".xlsx", ".xls")):
        brut = pd.read_excel(fichier, header=None, dtype=object)
    else:
        brut = pd.read_csv(fichier, header=None, dtype=str, sep=None, engine="python", encoding_errors="replace")

    brut = brut.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    ligne_entete = _trouver_ligne_entete(brut)
    entetes = [str(c).strip() if pd.notna(c) else f"Colonne {i + 1}" for i, c in enumerate(brut.iloc[ligne_entete])]
    donnees = brut.iloc[ligne_entete + 1:].copy()
    donnees.columns = _rendre_uniques(entetes)

    # Lignes de total / sous-total : un mot "total" dans une cellule texte
    est_total = donnees.apply(lambda ligne: any(isinstance(c, str) and "total" in normaliser(c) for c in ligne), axis=1)
    return donnees[~est_total].dropna(how="all").reset_index(drop=True)


def _rendre_uniques(noms: list[str]) -> list[str]:
    vus, resultat = {}, []
    for nom in noms:
        vus[nom] = vus.get(nom, 0) + 1
        resultat.append(nom if vus[nom] == 1 else f"{nom} ({vus[nom]})")
    return resultat


# ---------------------------------------------------------------------------
# 2. Proposition de correspondance
# ---------------------------------------------------------------------------
def proposer_correspondance_auto(colonnes_fichier: list[str]) -> dict[str, str]:
    """Correspondance par synonymes : nom exact d'abord, puis nom qui commence par un synonyme."""
    normalisees = {colonne: normaliser(colonne) for colonne in colonnes_fichier}
    correspondance, deja_prises = {}, set()
    for exact in (True, False):
        for cible in COLONNES_ATTENDUES:
            if cible in correspondance:
                continue
            candidats = [normaliser(cible)] + SYNONYMES[cible]
            for colonne, nom in normalisees.items():
                if colonne in deja_prises:
                    continue
                if (nom in candidats) if exact else any(nom.startswith(s + " ") for s in candidats):
                    correspondance[cible] = colonne
                    deja_prises.add(colonne)
                    break
    return correspondance


CONSIGNES_CORRESPONDANCE = """Tu aides à importer un export de ventes de mode (wholesale) dans un outil d'analyse.
On te donne les colonnes d'un fichier et quelques lignes d'exemple.
Pour chaque colonne cible, indique le nom EXACT de la colonne du fichier qui lui correspond,
ou une chaîne vide si aucune ne correspond. N'utilise jamais deux fois la même colonne du fichier.

Colonnes cibles :
- semaine : numéro de semaine ou période
- point_de_vente : magasin, client, revendeur
- type_pdv : type de point de vente (multimarque, grand magasin, e-tailer...)
- ville
- reference : code article / SKU / style
- nom_produit : désignation
- categorie : famille de produit
- couleur
- taille
- prix_gros : prix de vente au revendeur
- prix_public : prix de vente conseillé au consommateur
- qte_livree : unités livrées (sell-in)
- qte_vendue : unités vendues au consommateur (sell-out)
- stock_fin_semaine : stock restant"""


def proposer_correspondance_ia(donnees: pd.DataFrame) -> dict[str, str]:
    """Demande à Claude la correspondance. Seuls les en-têtes et 5 lignes sont envoyés."""
    apercu = donnees.head(5).astype(str).to_dict(orient="records")
    contenu = json.dumps({"colonnes": list(donnees.columns), "exemples": apercu}, ensure_ascii=False)
    schema = {
        "type": "object",
        "properties": {cible: {"type": "string"} for cible in COLONNES_ATTENDUES},
        "required": COLONNES_ATTENDUES,
        "additionalProperties": False,
    }
    texte = appeler_claude(CONSIGNES_CORRESPONDANCE, contenu, max_tokens=2000,
                           format_json={"type": "json_schema", "schema": schema})
    reponse = json.loads(texte)
    # Garde-fou : on ne retient que des colonnes qui existent vraiment, chacune une seule fois
    correspondance, deja_prises = {}, set()
    for cible in COLONNES_ATTENDUES:
        colonne = reponse.get(cible, "")
        if colonne in donnees.columns and colonne not in deja_prises:
            correspondance[cible] = colonne
            deja_prises.add(colonne)
    return correspondance


# ---------------------------------------------------------------------------
# 3. Transformation au format de l'outil
# ---------------------------------------------------------------------------
def nettoyer_nombre(serie: pd.Series) -> pd.Series:
    """'1 234,50 €' -> 1234.5 ; cellules vides ou illisibles -> 0."""
    def convertir(valeur):
        if pd.isna(valeur):
            return 0.0
        if isinstance(valeur, (int, float)):
            return float(valeur)
        texte = re.sub(r"[^\d,.\-]", "", str(valeur))
        if "," in texte and "." in texte:      # 1.234,50 -> 1234.50
            texte = texte.replace(".", "").replace(",", ".")
        else:
            texte = texte.replace(",", ".")
        try:
            return float(texte)
        except ValueError:
            return 0.0
    return serie.map(convertir)


def nettoyer_semaine(serie: pd.Series) -> pd.Series:
    """'S12', 'Semaine 3', 'W05' -> 12, 3, 5. Des dates -> 1, 2, 3... dans l'ordre chronologique."""
    nombres = serie.astype(str).str.extract(r"(\d+)\s*$")[0]
    with warnings.catch_warnings():  # pandas prévient qu'il devine le format des dates : c'est voulu
        warnings.simplefilter("ignore")
        dates = pd.to_datetime(serie, errors="coerce", dayfirst=True)
    if dates.notna().mean() > 0.8 and not serie.astype(str).str.fullmatch(r"\s*\d{1,2}\s*").all():
        return dates.rank(method="dense").fillna(1).astype(int)
    return pd.to_numeric(nombres, errors="coerce").fillna(1).astype(int)


def appliquer_correspondance(donnees: pd.DataFrame, correspondance: dict[str, str]) -> tuple[pd.DataFrame, list[str]]:
    """Construit un tableau au format attendu. Renvoie aussi la liste des hypothèses faites."""
    manquantes = [LIBELLES[c] for c in COLONNES_OBLIGATOIRES if c not in correspondance]
    if manquantes:
        raise ValueError(f"Colonnes indispensables non renseignées : {', '.join(manquantes)}.")
    if "qte_livree" not in correspondance and "stock_fin_semaine" not in correspondance:
        raise ValueError("Il faut au moins la quantité livrée ou le stock pour calculer un sell-through.")

    avertissements = []
    sortie = pd.DataFrame(index=donnees.index)
    for cible, colonne in correspondance.items():
        sortie[cible] = donnees[colonne]

    # Colonnes texte : valeurs par défaut si absentes
    valeurs_par_defaut = {"type_pdv": "non renseigné", "ville": "non renseignée", "categorie": "Non classé",
                          "couleur": "", "taille": "TU"}
    for cible, defaut in valeurs_par_defaut.items():
        if cible not in sortie:
            sortie[cible] = defaut
            avertissements.append(f"{LIBELLES[cible]} absente : valeur « {defaut or 'vide'} » utilisée.")
    for cible in ["point_de_vente", "reference", "type_pdv", "ville", "categorie", "couleur", "taille"]:
        sortie[cible] = sortie[cible].fillna("").astype(str).str.strip()
    sortie = sortie[(sortie["point_de_vente"] != "") & (sortie["reference"] != "")]
    if "nom_produit" not in sortie:
        sortie["nom_produit"] = sortie["reference"]
    sortie["nom_produit"] = sortie["nom_produit"].fillna("").astype(str).str.strip()

    # Semaine
    if "semaine" in sortie:
        sortie["semaine"] = nettoyer_semaine(sortie["semaine"])
    else:
        sortie["semaine"] = 1
        avertissements.append("Pas de colonne de période : tout le fichier est traité comme une seule période. "
                              "La couverture est alors exprimée en nombre de périodes.")

    # Nombres
    for cible in ["prix_gros", "prix_public", "qte_livree", "qte_vendue", "stock_fin_semaine"]:
        if cible in sortie:
            sortie[cible] = nettoyer_nombre(sortie[cible])
    consequences = {"prix_gros": "le CA de gros sera à 0", "prix_public": "le prix démarqué ne sera pas calculé"}
    for prix, consequence in consequences.items():
        if prix not in sortie:
            sortie[prix] = 0.0
            avertissements.append(f"{LIBELLES[prix]} absent : {consequence}.")

    # Plusieurs lignes pour le même SKU et la même semaine : on additionne
    cles = ["semaine", "point_de_vente", "reference", "taille"]
    quantites = [c for c in ["qte_livree", "qte_vendue", "stock_fin_semaine"] if c in sortie]
    autres = [c for c in COLONNES_ATTENDUES if c not in cles + quantites and c in sortie]
    sortie = (sortie.groupby(cles, as_index=False)
              .agg({**{c: "sum" for c in quantites}, **{c: "first" for c in autres}}))
    sortie = sortie.sort_values(cles).reset_index(drop=True)
    par_sku = sortie.groupby(["point_de_vente", "reference", "taille"])

    # Quantités manquantes, recalculées à partir des autres
    if "stock_fin_semaine" not in sortie:
        sortie["stock_fin_semaine"] = (par_sku["qte_livree"].cumsum() - par_sku["qte_vendue"].cumsum()).clip(lower=0)
        avertissements.append("Stock absent : recalculé comme livré cumulé - vendu cumulé.")
    if "qte_livree" not in sortie:
        # tout ce qui a été vendu ou reste en stock a forcément été livré : on le place à la 1re période
        stock_final = par_sku["stock_fin_semaine"].transform("last")
        vendu_total = par_sku["qte_vendue"].transform("sum")
        premiere = par_sku.cumcount() == 0
        sortie["qte_livree"] = (stock_final + vendu_total).where(premiere, 0)
        avertissements.append("Quantité livrée absente : estimée par vendu total + stock final, "
                              "comptée sur la première période.")

    for cible in ["qte_livree", "qte_vendue", "stock_fin_semaine", "prix_gros", "prix_public"]:
        if (sortie[cible] < 0).any():
            avertissements.append(f"Valeurs négatives dans « {LIBELLES[cible]} » (retours ?) ramenées à 0.")
            sortie[cible] = sortie[cible].clip(lower=0)

    if sortie.empty:
        raise ValueError("Aucune ligne exploitable après conversion.")
    return sortie[COLONNES_ATTENDUES], avertissements
