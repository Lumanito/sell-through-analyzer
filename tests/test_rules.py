"""Tests des règles de recommandation sur des cas simples."""

import pandas as pd

from src.config import ParametresRegles
from src.rules import besoin_pour_cible, proposer_reassorts, proposer_transferts


def kpi(pdv, sell_through, couverture, stock, rythme, reference="R1"):
    """Ligne de KPIs au niveau référence x point de vente."""
    return {"reference": reference, "nom_produit": "Veste test", "categorie": "Vestes",
            "point_de_vente": pdv, "type_pdv": "multimarque", "ville": "Lyon",
            "sell_through": sell_through, "couverture_semaines": couverture,
            "stock_actuel": stock, "rythme_hebdo": rythme, "prix_gros": 100.0}


def test_besoin_pour_cible():
    # 2 unités / semaine x 6 semaines = 12, il en reste 3 -> 9 à ajouter
    assert besoin_pour_cible(2, 3, 6) == 9
    assert besoin_pour_cible(1, 20, 6) == 0


def test_transfert_du_surstock_vers_la_tension():
    kpis = pd.DataFrame([
        kpi("Surstock", 0.2, 40.0, 20, 0.5),   # garde 3 (0,5 x 6), peut donner 17
        kpi("Tension", 0.9, 0.5, 1, 2.0),      # a besoin de 11 pour 6 semaines
    ])
    transferts = proposer_transferts(kpis, ParametresRegles())
    assert len(transferts) == 1
    assert transferts.iloc[0]["depuis"] == "Surstock"
    assert transferts.iloc[0]["quantite"] == 11


def test_reassort_deduit_les_transferts():
    kpis = pd.DataFrame([kpi("Tension", 0.9, 0.5, 1, 2.0)])
    transferts = pd.DataFrame([{"reference": "R1", "vers": "Tension", "quantite": 5}])
    reassorts = proposer_reassorts(kpis, transferts, ParametresRegles())
    assert reassorts.iloc[0]["qte_reassort"] == 11 - 5


def test_pas_de_reassort_si_la_reference_se_vend_mal():
    kpis = pd.DataFrame([kpi("Boutique", 0.3, 1.0, 1, 1.0)])
    reassorts = proposer_reassorts(kpis, pd.DataFrame(columns=["reference", "vers", "quantite"]), ParametresRegles())
    assert reassorts.empty


def test_limite_ia_desactivee_par_defaut(monkeypatch):
    from src.ai_report import limite_rapports_par_jour
    monkeypatch.delenv("LIMITE_RAPPORTS_IA_PAR_JOUR", raising=False)
    assert limite_rapports_par_jour() == 0
    monkeypatch.setenv("LIMITE_RAPPORTS_IA_PAR_JOUR", "pas un nombre")
    assert limite_rapports_par_jour() == 0
