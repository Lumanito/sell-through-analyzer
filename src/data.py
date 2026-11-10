"""Données : génération d'un jeu fictif réaliste et import d'un CSV utilisateur.

La marque "Fjelda" et tous les points de vente sont inventés.
Lancer `python -m src.data` régénère data/sample_sales.csv et data/template.csv.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from src.config import COLONNES_ATTENDUES, COLONNES_NUMERIQUES

DOSSIER_DATA = Path(__file__).resolve().parent.parent / "data"
NB_SEMAINES = 12

# ---------------------------------------------------------------------------
# 1. Catalogue de la collection : (catégorie, modèle, couleurs, prix de gros)
# ---------------------------------------------------------------------------
MODELES = [
    ("Vestes", "Veste Storm", ["Noir", "Olive", "Marine"], 95),
    ("Vestes", "Veste Ridge", ["Noir", "Sable"], 110),
    ("Vestes", "Parka Arctic", ["Noir", "Kaki"], 145),
    ("Vestes", "Coupe-vent Trail", ["Bleu", "Rouge"], 60),
    ("Vestes", "Doudoune Fjord", ["Noir", "Marine", "Ecru"], 120),
    ("Bottes", "Boot Tind", ["Marron", "Noir"], 80),
    ("Bottes", "Chelsea Vik", ["Noir", "Cognac"], 70),
    ("Bottes", "Boot Lumi", ["Blanc", "Gris"], 75),
    ("Bottes", "Trek Pro", ["Marron", "Gris"], 90),
    ("Polaires", "Polaire Sherpa", ["Ecru", "Marron", "Vert"], 45),
    ("Polaires", "Zip Fleece", ["Noir", "Marine", "Orange"], 38),
    ("Polaires", "Gilet Polar", ["Gris", "Kaki"], 35),
    ("Polaires", "Hoodie Fleece", ["Bordeaux", "Gris"], 42),
    ("Accessoires", "Bonnet Laine", ["Noir", "Rouge", "Ecru"], 12),
    ("Accessoires", "Echarpe Merino", ["Gris", "Bordeaux"], 18),
    ("Accessoires", "Gants Touch", ["Noir", "Gris"], 14),
    ("Accessoires", "Sac a dos 20L", ["Noir", "Kaki"], 40),
    ("Accessoires", "Tour de cou", ["Orange"], 9),
]

# Tailles proposées et répartition des quantités commandées par taille
TAILLES = {
    "Vestes": {"S": 0.22, "M": 0.33, "L": 0.30, "XL": 0.15},
    "Polaires": {"S": 0.22, "M": 0.33, "L": 0.30, "XL": 0.15},
    "Bottes": {"40": 0.12, "41": 0.20, "42": 0.28, "43": 0.25, "44": 0.15},
    "Accessoires": {"TU": 1.0},
}
# Demande réelle par taille : légèrement plus concentrée sur M et L que la commande,
# ce qui crée des ruptures sur les tailles centrales (cas fréquent en vrai)
DEMANDE_TAILLES = {
    "Vestes": {"S": 0.16, "M": 0.38, "L": 0.33, "XL": 0.13},
    "Polaires": {"S": 0.16, "M": 0.38, "L": 0.33, "XL": 0.13},
    "Bottes": {"40": 0.10, "41": 0.20, "42": 0.30, "43": 0.26, "44": 0.14},
    "Accessoires": {"TU": 1.0},
}

# Rythme de vente de base (unités / semaine / référence pour un point de vente moyen)
RYTHME_CATEGORIE = {"Vestes": 1.3, "Bottes": 1.0, "Polaires": 1.5, "Accessoires": 2.0}

# Références volontairement très bonnes ou très mauvaises (pour des cas lisibles)
BEST_SELLERS = {"Veste Storm Olive", "Doudoune Fjord Noir", "Polaire Sherpa Ecru",
                "Boot Tind Marron", "Bonnet Laine Ecru"}
REFERENCES_QUI_STAGNENT = {"Coupe-vent Trail Rouge", "Hoodie Fleece Bordeaux",
                           "Boot Lumi Blanc", "Sac a dos 20L Kaki", "Tour de cou Orange"}

# ---------------------------------------------------------------------------
# 2. Réseau de distribution : (nom, type, ville)
# ---------------------------------------------------------------------------
POINTS_DE_VENTE = [
    ("Alti Sports", "multimarque", "Annecy"),
    ("Le Refuge", "multimarque", "Grenoble"),
    ("Cimes & Co", "multimarque", "Annecy"),
    ("Comptoir du Nord", "multimarque", "Lille"),
    ("Maison Garonne", "multimarque", "Bordeaux"),
    ("Atelier Presqu'ile", "multimarque", "Lyon"),
    ("La Boussole", "multimarque", "Nantes"),
    ("Vieux Port Outdoor", "multimarque", "Marseille"),
    ("Le Vestiaire", "multimarque", "Paris"),
    ("Sentiers", "multimarque", "Grenoble"),
    ("Bivouac", "multimarque", "Lyon"),
    ("Rive Gauche Store", "multimarque", "Paris"),
    ("Le Grand Bazar", "grand_magasin", "Paris"),
    ("Maison Centrale", "grand_magasin", "Lyon"),
    ("Les Halles Dorees", "grand_magasin", "Bordeaux"),
    ("Le Printanier", "grand_magasin", "Lille"),
    ("Galerie Canebiere", "grand_magasin", "Marseille"),
    ("Grand Magasin de l'Erdre", "grand_magasin", "Nantes"),
    ("Le Grand Bazar Rive Droite", "grand_magasin", "Paris"),
    ("Outdoor Express", "e_tailer", "En ligne"),
    ("Modalia", "e_tailer", "En ligne"),
    ("TrailShop", "e_tailer", "En ligne"),
    ("Nordik Online", "e_tailer", "En ligne"),
    ("SummitStore", "e_tailer", "En ligne"),
    ("Urbania", "e_tailer", "En ligne"),
]

# Volume moyen par type de point de vente et nombre de références achetées
VOLUME_TYPE = {"multimarque": 0.8, "grand_magasin": 1.5, "e_tailer": 1.9}
NB_REFERENCES_TYPE = {"multimarque": (16, 24), "grand_magasin": (24, 32), "e_tailer": (30, 40)}
VILLES_MONTAGNE = {"Annecy", "Grenoble"}  # clientèle outdoor : ventes plus fortes


def _prix_public(prix_gros: float) -> float:
    """Prix public conseillé : coefficient d'environ 2,4, arrondi à 9 EUR près."""
    return float(round(prix_gros * 2.4 / 10) * 10 - 1)


def _saisonnalite(categorie: str, semaine: int) -> float:
    """Multiplicateur de demande : la collection automne-hiver accélère avec le froid.

    Semaine 1 = début septembre, semaine 12 = fin novembre. Un coup de froid
    en semaine 9 fait grimper toutes les ventes.
    """
    progression = (semaine - 1) / (NB_SEMAINES - 1)       # de 0 à 1
    pente = {"Vestes": 0.7, "Polaires": 0.6, "Bottes": 0.8, "Accessoires": 1.1}[categorie]
    multiplicateur = 0.65 + pente * progression
    if semaine == 9:
        multiplicateur *= 1.25
    return multiplicateur


def construire_catalogue() -> pd.DataFrame:
    """Une ligne par référence (modèle + couleur), avec son attractivité réelle."""
    generateur = np.random.default_rng(7)
    lignes = []
    for numero_modele, (categorie, modele, couleurs, prix_gros) in enumerate(MODELES, start=1):
        for numero_couleur, couleur in enumerate(couleurs, start=1):
            nom = f"{modele} {couleur}"
            attractivite = float(generateur.lognormal(0, 0.3))
            if nom in BEST_SELLERS:
                attractivite = 2.3
            elif nom in REFERENCES_QUI_STAGNENT:
                attractivite = 0.22
            lignes.append({
                "reference": f"FJ-{categorie[:3].upper()}-{numero_modele:02d}{numero_couleur}",
                "nom_produit": nom,
                "categorie": categorie,
                "couleur": couleur,
                "prix_gros": float(prix_gros),
                "prix_public": _prix_public(prix_gros),
                "attractivite": attractivite,
            })
    return pd.DataFrame(lignes)


def generer_donnees(graine: int = 42) -> pd.DataFrame:
    """Simule 12 semaines de ventes pour toute la collection et tout le réseau.

    Logique : chaque point de vente achète une partie de la collection, reçoit
    sa livraison en semaine 1, puis vend selon l'attractivité de la référence,
    la taille, la saison et son propre volume. Les best-sellers reçoivent un
    réassort partiel en semaine 7. Les ventes ne peuvent pas dépasser le stock.
    """
    generateur = np.random.default_rng(graine)
    catalogue = construire_catalogue()

    # --- Lignes de base : un SKU (référence x taille) présent dans un point de vente
    lignes_sku = []
    for nom_pdv, type_pdv, ville in POINTS_DE_VENTE:
        volume = VOLUME_TYPE[type_pdv] * generateur.lognormal(0, 0.2)
        if ville in VILLES_MONTAGNE:
            volume *= 1.3
        mini, maxi = NB_REFERENCES_TYPE[type_pdv]
        nb_refs = generateur.integers(mini, maxi + 1)
        refs_achetees = catalogue.sample(n=min(nb_refs, len(catalogue)), random_state=generateur.integers(1e9))

        for produit in refs_achetees.itertuples():
            rythme_ref = RYTHME_CATEGORIE[produit.categorie] * volume
            for taille, part_commande in TAILLES[produit.categorie].items():
                part_demande = DEMANDE_TAILLES[produit.categorie][taille]
                # L'acheteur commande pour ~12 semaines à un rythme "moyen" (il ne
                # connaît pas encore l'attractivité réelle de la référence)
                commande = max(1, round(rythme_ref * part_commande * NB_SEMAINES * 0.85))
                lignes_sku.append({
                    "point_de_vente": nom_pdv, "type_pdv": type_pdv, "ville": ville,
                    "reference": produit.reference, "nom_produit": produit.nom_produit,
                    "categorie": produit.categorie, "couleur": produit.couleur, "taille": taille,
                    "prix_gros": produit.prix_gros, "prix_public": produit.prix_public,
                    "commande_initiale": commande,
                    # demande hebdomadaire moyenne réelle (avant saisonnalité)
                    "demande_base": rythme_ref * part_demande * produit.attractivite * 0.55,
                    "best_seller": produit.nom_produit in BEST_SELLERS,
                })
    sku = pd.DataFrame(lignes_sku)

    # --- Simulation semaine par semaine (calcul vectorisé sur tous les SKU)
    stock = np.zeros(len(sku), dtype=int)
    semaines = []
    for semaine in range(1, NB_SEMAINES + 1):
        livraison = np.zeros(len(sku), dtype=int)
        if semaine == 1:
            livraison = sku["commande_initiale"].to_numpy()
        elif semaine == 7:
            # Réassort des best-sellers en rupture, une fois sur deux, à 40 % de la commande
            eligible = sku["best_seller"].to_numpy() & (stock <= 1) & (generateur.random(len(sku)) < 0.5)
            livraison = np.where(eligible, np.ceil(sku["commande_initiale"].to_numpy() * 0.4), 0).astype(int)
        stock = stock + livraison

        saison = sku["categorie"].map(lambda cat: _saisonnalite(cat, semaine)).to_numpy()
        demande = generateur.poisson(sku["demande_base"].to_numpy() * saison)
        ventes = np.minimum(demande, stock)
        stock = stock - ventes

        semaines.append(sku.assign(semaine=semaine, qte_livree=livraison,
                                   qte_vendue=ventes, stock_fin_semaine=stock))

    donnees = pd.concat(semaines, ignore_index=True)
    return donnees[COLONNES_ATTENDUES].sort_values(
        ["semaine", "point_de_vente", "reference", "taille"]).reset_index(drop=True)


def charger_csv(fichier) -> pd.DataFrame:
    """Lit un CSV utilisateur et vérifie qu'il respecte le format attendu.

    Lève une ValueError avec un message clair si une colonne manque ou si
    une valeur numérique est invalide.
    """
    donnees = pd.read_csv(fichier, dtype={"taille": str})
    colonnes_manquantes = [col for col in COLONNES_ATTENDUES if col not in donnees.columns]
    if colonnes_manquantes:
        raise ValueError(f"Colonnes manquantes dans le fichier : {', '.join(colonnes_manquantes)}")
    if donnees.empty:
        raise ValueError("Le fichier ne contient aucune ligne de données.")

    for colonne in COLONNES_NUMERIQUES:
        donnees[colonne] = pd.to_numeric(donnees[colonne], errors="coerce")
        if donnees[colonne].isna().any():
            raise ValueError(f"La colonne '{colonne}' contient des valeurs vides ou non numériques.")
        if (donnees[colonne] < 0).any():
            raise ValueError(f"La colonne '{colonne}' contient des valeurs négatives.")
    return donnees[COLONNES_ATTENDUES]


def creer_modele_vide(chemin: Path) -> None:
    """Écrit un CSV avec uniquement les en-têtes, à remplir par l'utilisateur."""
    pd.DataFrame(columns=COLONNES_ATTENDUES).to_csv(chemin, index=False)


if __name__ == "__main__":
    DOSSIER_DATA.mkdir(exist_ok=True)
    jeu = generer_donnees()
    jeu.to_csv(DOSSIER_DATA / "sample_sales.csv", index=False)
    creer_modele_vide(DOSSIER_DATA / "template.csv")
    print(f"{len(jeu)} lignes générées dans {DOSSIER_DATA / 'sample_sales.csv'}")
