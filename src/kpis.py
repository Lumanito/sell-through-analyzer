"""Calcul des KPIs de sell-through.

Définitions (toutes calculées sur la période chargée) :
- sell-through %        = unités vendues / unités livrées
- rythme de vente       = ventes moyennes par semaine sur les 4 dernières semaines
- semaines de couverture = stock actuel / rythme de vente
- rupture               = stock actuel à 0
- CA de gros            = unités vendues x prix de gros
"""

import numpy as np
import pandas as pd

from src.config import COUVERTURE_MAX, NB_SEMAINES_RYTHME


def calculer_couverture(stock: pd.Series, rythme: pd.Series) -> pd.Series:
    """Semaines de couverture = stock / rythme hebdomadaire.

    Cas particuliers :
    - pas de stock -> 0 semaine
    - du stock mais aucune vente récente -> COUVERTURE_MAX (le stock ne s'écoule pas)
    """
    couverture = np.where(rythme > 0, stock / rythme.where(rythme > 0, 1), COUVERTURE_MAX)
    couverture = np.where(stock <= 0, 0.0, couverture)
    return pd.Series(np.minimum(couverture, COUVERTURE_MAX), index=stock.index).round(1)


def kpis_par(donnees: pd.DataFrame, niveau: list[str]) -> pd.DataFrame:
    """Agrège les ventes au niveau demandé (ex. ["categorie"] ou ["reference", "point_de_vente"]).

    Retourne une ligne par groupe avec : unités livrées, vendues, stock actuel,
    rythme de vente, sell-through, couverture et CA de gros.
    """
    derniere_semaine = donnees["semaine"].max()
    debut_fenetre = derniere_semaine - NB_SEMAINES_RYTHME + 1
    nb_semaines_fenetre = donnees.loc[donnees["semaine"] >= debut_fenetre, "semaine"].nunique()

    lignes = donnees.assign(
        ca_gros=donnees["qte_vendue"] * donnees["prix_gros"],
        # ventes comptées seulement si elles tombent dans les 4 dernières semaines
        ventes_recentes=donnees["qte_vendue"].where(donnees["semaine"] >= debut_fenetre, 0),
        # stock compté seulement à la dernière semaine (photo du stock actuel)
        stock_actuel=donnees["stock_fin_semaine"].where(donnees["semaine"] == derniere_semaine, 0),
    )

    agregations = {
        "qte_livree": ("qte_livree", "sum"),
        "qte_vendue": ("qte_vendue", "sum"),
        "stock_actuel": ("stock_actuel", "sum"),
        "ventes_recentes": ("ventes_recentes", "sum"),
        "ca_gros": ("ca_gros", "sum"),
    }
    if "reference" in niveau:  # le prix est le même pour toutes les lignes d'une référence
        agregations["prix_gros"] = ("prix_gros", "first")
        agregations["prix_public"] = ("prix_public", "first")

    resultat = lignes.groupby(niveau, as_index=False).agg(**agregations)
    resultat["rythme_hebdo"] = (resultat["ventes_recentes"] / max(nb_semaines_fenetre, 1)).round(2)
    resultat["sell_through"] = np.where(
        resultat["qte_livree"] > 0, resultat["qte_vendue"] / resultat["qte_livree"].where(resultat["qte_livree"] > 0, 1), 0.0
    ).round(3)
    resultat["couverture_semaines"] = calculer_couverture(resultat["stock_actuel"], resultat["rythme_hebdo"])
    return resultat.drop(columns="ventes_recentes")


def kpis_globaux(donnees: pd.DataFrame) -> dict:
    """Chiffres clés de tout le périmètre filtré."""
    total = kpis_par(donnees.assign(perimetre="total"), ["perimetre"]).iloc[0]
    par_ref_pdv = kpis_par(donnees, ["reference", "point_de_vente"])
    return {
        "derniere_semaine": int(donnees["semaine"].max()),
        "nb_references": int(donnees["reference"].nunique()),
        "nb_points_de_vente": int(donnees["point_de_vente"].nunique()),
        "ca_gros": float(total["ca_gros"]),
        "unites_livrees": int(total["qte_livree"]),
        "unites_vendues": int(total["qte_vendue"]),
        "stock_actuel": int(total["stock_actuel"]),
        "sell_through": float(total["sell_through"]),
        "couverture_semaines": float(total["couverture_semaines"]),
        "nb_ruptures": int((par_ref_pdv["stock_actuel"] == 0).sum()),
        "nb_couples_ref_pdv": int(len(par_ref_pdv)),
    }


def top_flop(kpis_references: pd.DataFrame, n: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Les n meilleures et n moins bonnes références selon le sell-through.

    À sell-through égal, on départage par le CA de gros (le plus gros CA d'abord).
    """
    tri = kpis_references.sort_values(["sell_through", "ca_gros"], ascending=[False, False])
    top = tri.head(n)
    flop = kpis_references.sort_values(["sell_through", "ca_gros"], ascending=[True, False]).head(n)
    return top.reset_index(drop=True), flop.reset_index(drop=True)


def ruptures(donnees: pd.DataFrame) -> pd.DataFrame:
    """Couples référence x point de vente dont toutes les tailles sont à zéro."""
    detail = kpis_par(donnees, ["reference", "nom_produit", "point_de_vente", "ville"])
    return detail[detail["stock_actuel"] == 0].reset_index(drop=True)


def ruptures_de_taille(donnees: pd.DataFrame) -> pd.DataFrame:
    """Tailles à zéro alors que d'autres tailles de la même référence restent en stock.

    C'est le signal d'une courbe de tailles mal calibrée : le client ne trouve
    pas sa taille alors que le point de vente a encore du stock.
    """
    detail = kpis_par(donnees, ["reference", "nom_produit", "point_de_vente", "ville", "taille"])
    stock_reference = detail.groupby(["reference", "point_de_vente"])["stock_actuel"].transform("sum")
    nb_tailles = detail.groupby(["reference", "point_de_vente"])["taille"].transform("count")
    en_rupture = detail[(detail["stock_actuel"] == 0) & (stock_reference > 0) & (nb_tailles > 1)]

    resume = (en_rupture.groupby(["reference", "nom_produit", "point_de_vente", "ville"], as_index=False)
              .agg(tailles_en_rupture=("taille", lambda tailles: ", ".join(sorted(tailles))),
                   nb_tailles_en_rupture=("taille", "count")))
    resume = resume.merge(
        detail.groupby(["reference", "point_de_vente"], as_index=False)["stock_actuel"].sum()
        .rename(columns={"stock_actuel": "stock_autres_tailles"}),
        on=["reference", "point_de_vente"],
    )
    return resume.sort_values(["nb_tailles_en_rupture", "stock_autres_tailles"],
                              ascending=[False, False]).reset_index(drop=True)


def ventes_hebdomadaires(donnees: pd.DataFrame, par: str = "categorie") -> pd.DataFrame:
    """Unités vendues par semaine, ventilées par catégorie (ou autre colonne)."""
    return donnees.groupby(["semaine", par], as_index=False)["qte_vendue"].sum()
