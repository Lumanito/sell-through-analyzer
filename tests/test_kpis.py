"""Tests des KPIs sur de petits cas calculables à la main.

Lancer : pytest
"""

import pandas as pd
import pytest

from src.config import COUVERTURE_MAX
from src.data import charger_csv, generer_donnees
from src.kpis import kpis_globaux, kpis_par, ruptures, ruptures_de_taille, top_flop


def ligne(semaine, pdv, reference, taille, livree, vendue, stock, prix_gros=50.0, categorie="Vestes"):
    """Construit une ligne de données au format attendu."""
    return {
        "semaine": semaine, "point_de_vente": pdv, "type_pdv": "multimarque", "ville": "Lyon",
        "reference": reference, "nom_produit": f"Produit {reference}", "categorie": categorie,
        "couleur": "Noir", "taille": taille, "prix_gros": prix_gros, "prix_public": prix_gros * 2.4,
        "qte_livree": livree, "qte_vendue": vendue, "stock_fin_semaine": stock,
    }


@pytest.fixture
def petit_jeu():
    """1 référence, 1 point de vente, 2 tailles, 4 semaines.

    Taille M : 10 livrées, 2 vendues par semaine -> 8 vendues, 2 en stock.
    Taille L : 10 livrées, 1 vendue par semaine  -> 4 vendues, 6 en stock.
    """
    lignes = []
    for semaine in range(1, 5):
        livree = 10 if semaine == 1 else 0
        lignes.append(ligne(semaine, "Boutique A", "R1", "M", livree, 2, 10 - 2 * semaine))
        lignes.append(ligne(semaine, "Boutique A", "R1", "L", livree, 1, 10 - semaine))
    return pd.DataFrame(lignes)


def test_sell_through(petit_jeu):
    resultat = kpis_par(petit_jeu, ["reference"]).iloc[0]
    assert resultat["qte_livree"] == 20
    assert resultat["qte_vendue"] == 12
    assert resultat["sell_through"] == pytest.approx(0.6)


def test_stock_actuel_prend_la_derniere_semaine(petit_jeu):
    resultat = kpis_par(petit_jeu, ["reference"]).iloc[0]
    assert resultat["stock_actuel"] == 2 + 6


def test_couverture_en_semaines(petit_jeu):
    # rythme = 3 unités / semaine, stock = 8 -> 8 / 3 = 2,7 semaines
    resultat = kpis_par(petit_jeu, ["reference"]).iloc[0]
    assert resultat["rythme_hebdo"] == pytest.approx(3.0)
    assert resultat["couverture_semaines"] == pytest.approx(2.7)


def test_couverture_sans_vente_et_sans_stock():
    lignes = [ligne(1, "A", "SANS_VENTE", "M", 5, 0, 5), ligne(1, "A", "VIDE", "M", 5, 5, 0)]
    resultat = kpis_par(pd.DataFrame(lignes), ["reference"]).set_index("reference")
    assert resultat.loc["SANS_VENTE", "couverture_semaines"] == COUVERTURE_MAX
    assert resultat.loc["VIDE", "couverture_semaines"] == 0


def test_ca_de_gros(petit_jeu):
    # 12 unités vendues x 50 EUR
    assert kpis_globaux(petit_jeu)["ca_gros"] == pytest.approx(600)


def test_rupture_de_taille():
    lignes = [ligne(1, "A", "R1", "M", 5, 5, 0), ligne(1, "A", "R1", "L", 5, 1, 4)]
    alertes = ruptures_de_taille(pd.DataFrame(lignes))
    assert len(alertes) == 1
    assert alertes.iloc[0]["tailles_en_rupture"] == "M"
    assert alertes.iloc[0]["stock_autres_tailles"] == 4


def test_rupture_totale_n_est_pas_une_rupture_de_taille():
    lignes = [ligne(1, "A", "R1", "M", 5, 5, 0), ligne(1, "A", "R1", "L", 5, 5, 0)]
    donnees = pd.DataFrame(lignes)
    assert ruptures_de_taille(donnees).empty
    assert len(ruptures(donnees)) == 1


def test_top_flop_ordre():
    lignes = [ligne(1, "A", ref, "M", 10, vendue, 10 - vendue) for ref, vendue in [("R1", 9), ("R2", 1), ("R3", 5)]]
    top, flop = top_flop(kpis_par(pd.DataFrame(lignes), ["reference"]), n=2)
    assert list(top["reference"]) == ["R1", "R3"]
    assert list(flop["reference"]) == ["R2", "R3"]


def test_donnees_generees_coherentes():
    """Le stock ne devient jamais négatif et suit livraisons - ventes."""
    donnees = generer_donnees()
    assert (donnees["stock_fin_semaine"] >= 0).all()
    cumul = donnees.sort_values("semaine").groupby(["point_de_vente", "reference", "taille"])
    stock_calcule = cumul["qte_livree"].cumsum() - cumul["qte_vendue"].cumsum()
    assert (stock_calcule == donnees.sort_values("semaine")["stock_fin_semaine"]).all()


def test_import_refuse_un_fichier_incomplet(tmp_path):
    fichier = tmp_path / "incomplet.csv"
    fichier.write_text("semaine,reference\n1,R1\n")
    with pytest.raises(ValueError, match="Colonnes manquantes"):
        charger_csv(fichier)
