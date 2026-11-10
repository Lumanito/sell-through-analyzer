"""Recommandations par règles simples (sans IA).

Ordre de priorité métier :
1. Transférer d'abord le stock qui dort ailleurs dans le réseau (pas de nouvelle production).
2. Réassortir ensuite seulement le besoin restant.
3. Proposer une démarque sur les références qui ne se vendent pas à l'échelle du réseau.
4. Signaler les ruptures de taille (courbe de tailles à corriger).
"""

import math

import pandas as pd

from src.config import ParametresRegles
from src.kpis import kpis_par, ruptures_de_taille

NIVEAU_REFERENCE_PDV = ["reference", "nom_produit", "categorie", "point_de_vente", "type_pdv", "ville"]


def besoin_pour_cible(rythme_hebdo: float, stock: float, couverture_cible: float) -> int:
    """Unités à ajouter pour atteindre la couverture cible (0 si le stock suffit)."""
    return max(0, math.ceil(rythme_hebdo * couverture_cible - stock))


def excedent_au_dela_cible(rythme_hebdo: float, stock: float, couverture_cible: float) -> int:
    """Unités au-delà de la couverture cible, donc transférables sans créer de rupture."""
    return max(0, math.floor(stock - rythme_hebdo * couverture_cible))


def proposer_transferts(kpis_ref_pdv: pd.DataFrame, parametres: ParametresRegles) -> pd.DataFrame:
    """Pour chaque référence, déplace le stock des points de vente en surstock
    vers ceux en tension.

    - donneur  : couverture > couverture_surstock
    - receveur : couverture < couverture_tension et la référence s'y vend encore
    - quantité : min(excédent du donneur, besoin du receveur)
    Les receveurs qui vendent le plus vite sont servis en premier.
    """
    transferts = []
    for reference, groupe in kpis_ref_pdv.groupby("reference"):
        donneurs = groupe[groupe["couverture_semaines"] > parametres.couverture_surstock].copy()
        receveurs = groupe[(groupe["couverture_semaines"] < parametres.couverture_tension)
                           & (groupe["rythme_hebdo"] > 0)].copy()
        if donneurs.empty or receveurs.empty:
            continue

        donneurs["disponible"] = [excedent_au_dela_cible(r, s, parametres.couverture_cible)
                                  for r, s in zip(donneurs["rythme_hebdo"], donneurs["stock_actuel"])]
        receveurs["besoin"] = [besoin_pour_cible(r, s, parametres.couverture_cible)
                               for r, s in zip(receveurs["rythme_hebdo"], receveurs["stock_actuel"])]
        donneurs = donneurs.sort_values("disponible", ascending=False)
        receveurs = receveurs.sort_values("rythme_hebdo", ascending=False)

        for _, receveur in receveurs.iterrows():
            besoin_restant = receveur["besoin"]
            for index_donneur, donneur in donneurs.iterrows():
                quantite = min(besoin_restant, donneurs.at[index_donneur, "disponible"])
                if quantite < parametres.quantite_min_transfert:
                    continue
                transferts.append({
                    "reference": reference,
                    "nom_produit": receveur["nom_produit"],
                    "depuis": donneur["point_de_vente"],
                    "ville_depart": donneur["ville"],
                    "couverture_depart": donneur["couverture_semaines"],
                    "vers": receveur["point_de_vente"],
                    "ville_arrivee": receveur["ville"],
                    "couverture_arrivee": receveur["couverture_semaines"],
                    "quantite": int(quantite),
                })
                donneurs.at[index_donneur, "disponible"] -= quantite
                besoin_restant -= quantite
                if besoin_restant < parametres.quantite_min_transfert:
                    break

    colonnes = ["reference", "nom_produit", "depuis", "ville_depart", "couverture_depart",
                "vers", "ville_arrivee", "couverture_arrivee", "quantite"]
    return pd.DataFrame(transferts, columns=colonnes)


def proposer_reassorts(kpis_ref_pdv: pd.DataFrame, transferts: pd.DataFrame,
                       parametres: ParametresRegles) -> pd.DataFrame:
    """Réassort si la référence se vend bien et qu'il reste peu de stock.

    - condition : sell-through >= seuil ET couverture < seuil ET ventes récentes > 0
    - quantité  : besoin pour atteindre la couverture cible - unités déjà reçues en transfert
    """
    candidats = kpis_ref_pdv[
        (kpis_ref_pdv["sell_through"] >= parametres.sell_through_min_reassort)
        & (kpis_ref_pdv["couverture_semaines"] < parametres.couverture_max_reassort)
        & (kpis_ref_pdv["rythme_hebdo"] > 0)
    ].copy()

    recu_en_transfert = (transferts.groupby(["reference", "vers"])["quantite"].sum()
                         if not transferts.empty else pd.Series(dtype=float))
    candidats["recu_en_transfert"] = [
        int(recu_en_transfert.get((ref, pdv), 0))
        for ref, pdv in zip(candidats["reference"], candidats["point_de_vente"])
    ]
    candidats["qte_reassort"] = [
        max(0, besoin_pour_cible(r, s, parametres.couverture_cible) - recu)
        for r, s, recu in zip(candidats["rythme_hebdo"], candidats["stock_actuel"], candidats["recu_en_transfert"])
    ]
    candidats = candidats[candidats["qte_reassort"] > 0]
    candidats["ca_gros_potentiel"] = candidats["qte_reassort"] * candidats["prix_gros"]

    colonnes = ["reference", "nom_produit", "point_de_vente", "ville", "sell_through",
                "couverture_semaines", "stock_actuel", "rythme_hebdo", "recu_en_transfert",
                "qte_reassort", "ca_gros_potentiel"]
    return candidats[colonnes].sort_values("ca_gros_potentiel", ascending=False).reset_index(drop=True)


def proposer_demarques(donnees: pd.DataFrame, parametres: ParametresRegles) -> pd.DataFrame:
    """Démarque sur les références qui stagnent à l'échelle de tout le réseau.

    - condition : au moins N semaines en magasin, sell-through < seuil, couverture > seuil
    - taux      : taux standard, ou taux fort si le sell-through est très bas
    """
    if donnees["semaine"].nunique() < parametres.semaines_min_demarque:
        return pd.DataFrame()  # trop tôt dans la saison pour conclure

    kpis_ref = kpis_par(donnees, ["reference", "nom_produit", "categorie"])
    candidats = kpis_ref[
        (kpis_ref["sell_through"] < parametres.sell_through_max_demarque)
        & (kpis_ref["couverture_semaines"] > parametres.couverture_min_demarque)
    ].copy()
    candidats["taux_demarque"] = [
        parametres.taux_demarque_forte if st < parametres.sell_through_demarque_forte else parametres.taux_demarque
        for st in candidats["sell_through"]
    ]
    candidats["prix_public_demarque"] = (candidats["prix_public"] * (1 - candidats["taux_demarque"])).round(0)
    candidats["valeur_stock_gros"] = candidats["stock_actuel"] * candidats["prix_gros"]

    colonnes = ["reference", "nom_produit", "categorie", "sell_through", "couverture_semaines",
                "stock_actuel", "valeur_stock_gros", "prix_public", "taux_demarque", "prix_public_demarque"]
    return candidats[colonnes].sort_values("valeur_stock_gros", ascending=False).reset_index(drop=True)


def generer_recommandations(donnees: pd.DataFrame, parametres: ParametresRegles) -> dict[str, pd.DataFrame]:
    """Point d'entrée : calcule les quatre listes d'actions."""
    kpis_ref_pdv = kpis_par(donnees, NIVEAU_REFERENCE_PDV)
    transferts = proposer_transferts(kpis_ref_pdv, parametres)
    return {
        "transferts": transferts,
        "reassorts": proposer_reassorts(kpis_ref_pdv, transferts, parametres),
        "demarques": proposer_demarques(donnees, parametres),
        "ruptures_taille": ruptures_de_taille(donnees),
    }
