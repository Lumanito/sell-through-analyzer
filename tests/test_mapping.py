"""Tests de l'import de fichiers imparfaits (sans appel à l'IA)."""

import pandas as pd
import pytest

from src.kpis import kpis_par
from src.mapping import (appliquer_correspondance, lire_fichier, nettoyer_nombre, nettoyer_semaine,
                         proposer_correspondance_auto)


@pytest.fixture
def excel_imparfait(tmp_path):
    """Un export typique : titre au-dessus, en-têtes en français, ligne de total,
    nombres au format français, semaines écrites 'S1', pas de colonne stock."""
    lignes = [
        ["Export ventes AH26", None, None, None, None, None],
        [None, None, None, None, None, None],
        ["Magasin", "Code article", "Désignation", "Semaine", "Qté livrée", "Ventes (unités)"],
        ["Boutique A", "R1", "Veste", "S1", "10", "2"],
        ["Boutique A", "R1", "Veste", "S2", "0", "3"],
        ["Boutique B", "R1", "Veste", "S1", "1 000", "1,0"],
        ["TOTAL", None, None, None, "1 010", "6"],
    ]
    chemin = tmp_path / "export.xlsx"
    pd.DataFrame(lignes).to_excel(chemin, header=False, index=False)
    return chemin


def test_lecture_trouve_l_entete_et_enleve_le_total(excel_imparfait):
    donnees = lire_fichier(excel_imparfait, "export.xlsx")
    assert list(donnees.columns) == ["Magasin", "Code article", "Désignation", "Semaine", "Qté livrée", "Ventes (unités)"]
    assert len(donnees) == 3


def test_correspondance_par_synonymes(excel_imparfait):
    donnees = lire_fichier(excel_imparfait, "export.xlsx")
    correspondance = proposer_correspondance_auto(list(donnees.columns))
    assert correspondance["point_de_vente"] == "Magasin"
    assert correspondance["reference"] == "Code article"
    assert correspondance["nom_produit"] == "Désignation"
    assert correspondance["qte_livree"] == "Qté livrée"
    assert correspondance["qte_vendue"] == "Ventes (unités)"
    assert "stock_fin_semaine" not in correspondance


def test_conversion_complete(excel_imparfait):
    donnees = lire_fichier(excel_imparfait, "export.xlsx")
    resultat, avertissements = appliquer_correspondance(donnees, proposer_correspondance_auto(list(donnees.columns)))
    boutique_a = resultat[resultat["point_de_vente"] == "Boutique A"].sort_values("semaine")
    assert list(boutique_a["semaine"]) == [1, 2]
    assert list(boutique_a["stock_fin_semaine"]) == [8, 5]      # stock recalculé : 10-2, puis 8-3
    assert resultat.loc[resultat["point_de_vente"] == "Boutique B", "qte_livree"].iloc[0] == 1000
    assert any("Stock absent" in a for a in avertissements)
    # le résultat passe dans le calcul des KPIs
    assert kpis_par(resultat, ["reference"]).iloc[0]["qte_vendue"] == 6


def test_livre_recalcule_depuis_le_stock():
    donnees = pd.DataFrame({"Store": ["A", "A"], "SKU": ["R1", "R1"], "Week": ["W1", "W2"],
                            "Units sold": [2, 3], "Stock": [8, 5]})
    resultat, _ = appliquer_correspondance(donnees, proposer_correspondance_auto(list(donnees.columns)))
    assert resultat["qte_livree"].tolist() == [10, 0]            # 2 + 3 vendues + 5 en stock = 10 livrées


def test_colonne_obligatoire_manquante():
    donnees = pd.DataFrame({"Magasin": ["A"], "Stock": [3]})
    with pytest.raises(ValueError, match="indispensables"):
        appliquer_correspondance(donnees, proposer_correspondance_auto(list(donnees.columns)))


def test_nettoyage_des_valeurs():
    assert nettoyer_nombre(pd.Series(["1 234,50 €", "1.234,5", "12", None, "n/a"])).tolist() == [1234.5, 1234.5, 12, 0, 0]
    assert nettoyer_semaine(pd.Series(["S1", "Semaine 12", "W05"])).tolist() == [1, 12, 5]
    assert nettoyer_semaine(pd.Series(["07/09/2026", "14/09/2026", "07/09/2026"])).tolist() == [1, 2, 1]
