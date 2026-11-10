"""Paramètres de l'outil : format des données et seuils des règles.

Tous les seuils sont regroupés ici pour être faciles à lire et à modifier.
L'application permet aussi de les changer depuis la barre latérale.
"""

from dataclasses import dataclass

# Colonnes attendues dans le CSV (une ligne = 1 SKU x 1 point de vente x 1 semaine)
COLONNES_ATTENDUES = [
    "semaine",            # numéro de semaine depuis la mise en place (1, 2, ...)
    "point_de_vente",     # nom du revendeur
    "type_pdv",           # multimarque, grand_magasin ou e_tailer
    "ville",
    "reference",          # code de la référence (modèle + couleur)
    "nom_produit",
    "categorie",          # Vestes, Bottes, Polaires, Accessoires
    "couleur",
    "taille",
    "prix_gros",          # prix de vente au revendeur (EUR HT)
    "prix_public",        # prix de vente conseillé au consommateur (EUR TTC)
    "qte_livree",         # unités livrées pendant la semaine
    "qte_vendue",         # unités vendues pendant la semaine
    "stock_fin_semaine",  # unités restantes en fin de semaine
]

COLONNES_NUMERIQUES = [
    "semaine", "prix_gros", "prix_public", "qte_livree", "qte_vendue", "stock_fin_semaine",
]

# Nombre de semaines récentes utilisées pour calculer le rythme de vente
NB_SEMAINES_RYTHME = 4

# Valeur affichée quand un stock ne se vend plus du tout (couverture "infinie")
COUVERTURE_MAX = 99.0


@dataclass
class ParametresRegles:
    """Seuils des règles de recommandation (valeurs par défaut modifiables)."""

    # Réassort : la référence se vend bien et il reste peu de semaines de stock
    sell_through_min_reassort: float = 0.65
    couverture_max_reassort: float = 3.0
    couverture_cible: float = 6.0          # nombre de semaines de stock visé après action

    # Transfert : un point de vente a trop de stock, un autre en manque
    couverture_surstock: float = 10.0
    couverture_tension: float = 2.0
    quantite_min_transfert: int = 3        # en dessous, le coût logistique ne vaut pas le coup

    # Démarque : la référence ne se vend pas après plusieurs semaines en magasin
    semaines_min_demarque: int = 8
    sell_through_max_demarque: float = 0.30
    couverture_min_demarque: float = 12.0
    taux_demarque: float = 0.20
    sell_through_demarque_forte: float = 0.15
    taux_demarque_forte: float = 0.30
