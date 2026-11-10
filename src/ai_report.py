"""Synthèse IA : transforme les KPIs agrégés en note au directeur commercial.

Seuls des chiffres agrégés et les recommandations sont envoyés à l'API Claude,
jamais le fichier de ventes brut (confidentialité + coût réduit).
La clé API est lue dans le fichier .env (variable ANTHROPIC_API_KEY).
"""

import json
import os

import anthropic
import pandas as pd
from dotenv import load_dotenv

from src.kpis import kpis_globaux, kpis_par, top_flop

load_dotenv()  # charge les variables du fichier .env s'il existe

MODELE_PAR_DEFAUT = "claude-opus-5-5"

CONSIGNES = """Tu es analyste wholesale senior dans une marque de mode outdoor / lifestyle.
Tu reçois les KPIs de sell-through d'une collection chez ses revendeurs
(multimarques, grands magasins, e-tailers) et les recommandations calculées par des règles.

Rédige en français une note au directeur commercial, en Markdown, avec exactement ces sections :
## Constats
3 à 5 puces, chiffrées, sur ce qui se vend, ce qui stagne et où.
## 5 actions prioritaires
Liste numérotée de 5 actions concrètes (réassort, transfert, démarque, courbe de tailles,
discussion avec un compte), chacune avec la référence ou le point de vente concerné,
la quantité ou le montant, et l'impact attendu.
## Risques et points de vigilance
3 puces.

Règles : n'utilise que les chiffres fournis, n'invente aucune donnée, pas de tableau,
reste sous 450 mots, ton professionnel et direct."""


def cle_api_disponible() -> bool:
    """Vrai si une clé API est configurée (fichier .env ou variable d'environnement)."""
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def _lignes(tableau: pd.DataFrame, colonnes: list[str], n: int) -> list[dict]:
    """Convertit les n premières lignes d'un tableau en liste de dictionnaires."""
    if tableau.empty:
        return []
    return tableau[colonnes].head(n).round(2).to_dict(orient="records")


def construire_contexte(donnees: pd.DataFrame, recommandations: dict[str, pd.DataFrame]) -> str:
    """Résumé chiffré (quelques milliers de caractères) envoyé au modèle."""
    kpis_ref = kpis_par(donnees, ["reference", "nom_produit", "categorie"])
    top, flop = top_flop(kpis_ref, n=5)
    colonnes_ref = ["nom_produit", "categorie", "sell_through", "couverture_semaines", "stock_actuel", "ca_gros"]
    colonnes_agregat = ["sell_through", "couverture_semaines", "ca_gros", "stock_actuel"]

    resume = {
        "chiffres_globaux": kpis_globaux(donnees),
        "par_categorie": _lignes(kpis_par(donnees, ["categorie"]), ["categorie"] + colonnes_agregat, 10),
        "par_type_point_de_vente": _lignes(kpis_par(donnees, ["type_pdv"]), ["type_pdv"] + colonnes_agregat, 10),
        "top_5_references": _lignes(top, colonnes_ref, 5),
        "flop_5_references": _lignes(flop, colonnes_ref, 5),
        "reassorts": {
            "nombre": len(recommandations["reassorts"]),
            "unites_totales": int(recommandations["reassorts"]["qte_reassort"].sum()) if not recommandations["reassorts"].empty else 0,
            "principaux": _lignes(recommandations["reassorts"],
                                  ["nom_produit", "point_de_vente", "sell_through", "qte_reassort", "ca_gros_potentiel"], 8),
        },
        "transferts": {
            "nombre": len(recommandations["transferts"]),
            "principaux": _lignes(recommandations["transferts"].sort_values("quantite", ascending=False)
                                  if not recommandations["transferts"].empty else recommandations["transferts"],
                                  ["nom_produit", "depuis", "vers", "quantite"], 6),
        },
        "demarques": _lignes(recommandations["demarques"],
                             ["nom_produit", "sell_through", "stock_actuel", "valeur_stock_gros", "taux_demarque"], 6),
        "ruptures_de_taille": {
            "nombre": len(recommandations["ruptures_taille"]),
            "exemples": _lignes(recommandations["ruptures_taille"],
                                ["nom_produit", "point_de_vente", "tailles_en_rupture"], 5),
        },
    }
    return json.dumps(resume, ensure_ascii=False, indent=1, default=str)


def generer_rapport(contexte: str, modele: str | None = None) -> str:
    """Appelle l'API Claude et renvoie la note en Markdown.

    Lève une RuntimeError avec un message lisible en cas de problème
    (clé invalide, quota, réseau...).
    """
    if not cle_api_disponible():
        raise RuntimeError("Aucune clé API : ajoute ANTHROPIC_API_KEY dans le fichier .env.")

    client = anthropic.Anthropic()  # lit ANTHROPIC_API_KEY automatiquement
    try:
        reponse = client.beta.messages.create(
            model=modele or os.getenv("CLAUDE_MODEL", MODELE_PAR_DEFAUT),
            max_tokens=4000,
            system=CONSIGNES,
            messages=[{"role": "user", "content": f"KPIs de la collection (JSON) :\n{contexte}"}],
            output_config={"effort": "medium"},
            # Si le modèle refuse la demande, l'API la relance sur un autre modèle
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as erreur:
        raise RuntimeError("Clé API refusée : vérifie ANTHROPIC_API_KEY dans le fichier .env.") from erreur
    except anthropic.RateLimitError as erreur:
        raise RuntimeError("Limite d'utilisation de l'API atteinte, réessaie dans une minute.") from erreur
    except anthropic.APIConnectionError as erreur:
        raise RuntimeError("Impossible de joindre l'API Claude : vérifie ta connexion internet.") from erreur
    except anthropic.APIStatusError as erreur:
        raise RuntimeError(f"Erreur de l'API Claude ({erreur.status_code}) : {erreur.message}") from erreur

    if reponse.stop_reason == "refusal":
        raise RuntimeError("Le modèle a refusé de générer ce rapport.")
    texte = "".join(bloc.text for bloc in reponse.content if bloc.type == "text")
    return texte.strip()
