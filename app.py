"""Sell-Through Analyzer : application Streamlit.

Lancer : streamlit run app.py
"""

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from datetime import date

from src.ai_report import (cle_api_disponible, construire_contexte, generer_rapport,
                            limite_rapports_par_jour)
from src.config import COUVERTURE_MAX, ParametresRegles
from src.data import charger_csv, generer_donnees
from src.export import construire_rapport_markdown, markdown_vers_pdf
from src.kpis import kpis_globaux, kpis_par, top_flop, ventes_hebdomadaires
from src.rules import generer_recommandations

DOSSIER_DATA = Path(__file__).parent / "data"

# Couleurs fixes par catégorie et par type de point de vente : une même catégorie
# garde la même couleur sur tous les graphiques, quels que soient les filtres
COULEURS_CATEGORIES = {"Vestes": "#2a78d6", "Polaires": "#eb6834", "Bottes": "#1baf7a", "Accessoires": "#eda100"}
COULEURS_TYPES = {"multimarque": "#2a78d6", "grand_magasin": "#eb6834", "e_tailer": "#1baf7a"}
LIBELLES_TYPES = {"multimarque": "Multimarque", "grand_magasin": "Grand magasin", "e_tailer": "E-tailer"}

st.set_page_config(page_title="Sell-Through Analyzer", page_icon="📦", layout="wide")


def titre(texte: str):
    """Sous-titre de section, plus discret que st.subheader."""
    st.markdown(f"#### {texte}")


# ---------------------------------------------------------------------------
# Chargement des données
# ---------------------------------------------------------------------------
@st.cache_resource
def compteur_rapports_ia() -> dict:
    """Compteur partagé par tous les visiteurs de l'app (remis à zéro chaque jour)."""
    return {"jour": date.today(), "nombre": 0}


@st.cache_data(show_spinner=False, max_entries=50)
def rapport_ia_en_cache(contexte: str) -> str:
    """Même contexte (mêmes filtres) = même note : pas de nouvel appel payant à l'API."""
    return generer_rapport(contexte)


@st.cache_data
def charger_jeu_exemple() -> pd.DataFrame:
    """Jeu fictif fourni ; régénéré s'il est absent."""
    chemin = DOSSIER_DATA / "sample_sales.csv"
    return charger_csv(chemin) if chemin.exists() else generer_donnees()


def mise_en_forme_graphique(figure, hauteur: int = 380):
    """Style commun : graphique sobre, légende en haut, pas de marges inutiles."""
    figure.update_layout(height=hauteur, margin=dict(l=10, r=45, t=30, b=10), barcornerradius=4,
                         legend=dict(orientation="h", yanchor="top", y=-0.28, x=0, title_text=""), bargap=0.25)
    figure.update_xaxes(showgrid=False)
    return figure


def graphique_sell_through(tableau: pd.DataFrame, colonne_nom: str, couleur: str | None = None,
                           couleurs: dict | None = None, hauteur: int = 380):
    """Barres horizontales de sell-through, de la meilleure à la moins bonne."""
    tableau = tableau.sort_values("sell_through")
    figure = px.bar(tableau, x="sell_through", y=colonne_nom, orientation="h", color=couleur,
                    color_discrete_map=couleurs, text=tableau["sell_through"].map("{:.0%}".format),
                    category_orders={couleur: list(couleurs)} if couleur else None,
                    custom_data=["qte_vendue", "qte_livree", "couverture_semaines"])
    figure.update_traces(
        textposition="outside", cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>Sell-through : %{x:.0%}<br>Vendues : %{customdata[0]} / livrées : "
                      "%{customdata[1]}<br>Couverture : %{customdata[2]} sem.<extra></extra>",
    )
    figure.update_xaxes(tickformat=".0%", range=[0, 1.22], title="")
    # ordre des barres = ordre du sell-through (sinon plotly regroupe par couleur)
    figure.update_yaxes(title="", categoryorder="array", categoryarray=list(tableau[colonne_nom]))
    return mise_en_forme_graphique(figure, hauteur)


def tableau_kpis(tableau: pd.DataFrame, colonnes: list[str]):
    """Affiche un tableau de KPIs avec des colonnes lisibles."""
    st.dataframe(
        tableau[colonnes], hide_index=True, width="stretch",
        column_config={
            "sell_through": st.column_config.ProgressColumn("Sell-through", format="percent", min_value=0, max_value=1),
            "couverture_semaines": st.column_config.NumberColumn("Couverture (sem.)", format="%.1f"),
            "ca_gros": st.column_config.NumberColumn("CA de gros", format="%.0f €"),
            "ca_gros_potentiel": st.column_config.NumberColumn("CA de gros potentiel", format="%.0f €"),
            "valeur_stock_gros": st.column_config.NumberColumn("Stock (valeur gros)", format="%.0f €"),
            "prix_public": st.column_config.NumberColumn("Prix public", format="%.0f €"),
            "prix_public_demarque": st.column_config.NumberColumn("Prix démarqué", format="%.0f €"),
            "taux_demarque": st.column_config.NumberColumn("Démarque", format="percent"),
            "qte_livree": "Livrées", "qte_vendue": "Vendues", "stock_actuel": "Stock",
            "rythme_hebdo": st.column_config.NumberColumn("Ventes / sem.", format="%.1f"),
            "nom_produit": "Produit", "reference": "Réf.", "categorie": "Catégorie",
            "point_de_vente": "Point de vente", "type_pdv": "Type", "ville": "Ville",
            "qte_reassort": "Qté à réassortir", "recu_en_transfert": "Reçu en transfert",
            "quantite": "Quantité", "depuis": "Depuis", "vers": "Vers",
            "ville_depart": "Ville départ", "ville_arrivee": "Ville arrivée",
            "couverture_depart": "Couv. départ", "couverture_arrivee": "Couv. arrivée",
            "tailles_en_rupture": "Tailles épuisées", "nb_tailles_en_rupture": "Nb tailles",
            "stock_autres_tailles": "Stock autres tailles",
        },
    )


# ---------------------------------------------------------------------------
# Barre latérale : source des données, filtres, paramètres des règles
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Données")
    source = st.radio("Source", ["Jeu fictif Fjelda", "Importer mon CSV"], label_visibility="collapsed")
    if source == "Importer mon CSV":
        fichier = st.file_uploader("Fichier CSV au format du modèle", type="csv")
        st.download_button("Télécharger le modèle vide", (DOSSIER_DATA / "template.csv").read_bytes(),
                           file_name="modele_sell_through.csv", mime="text/csv")
        if fichier is None:
            st.info("Charge un fichier pour lancer l'analyse.")
            st.stop()
        try:
            donnees = charger_csv(fichier)
        except ValueError as erreur:
            st.error(str(erreur))
            st.stop()
    else:
        donnees = charger_jeu_exemple()

    st.header("Filtres")
    categories = st.multiselect("Catégorie", sorted(donnees["categorie"].unique()), placeholder="Toutes")
    types_pdv = st.multiselect("Type de point de vente", sorted(donnees["type_pdv"].unique()),
                               format_func=lambda t: LIBELLES_TYPES.get(t, t), placeholder="Tous")
    villes = st.multiselect("Ville", sorted(donnees["ville"].unique()), placeholder="Toutes")

    with st.expander("Seuils des règles"):
        defaut = ParametresRegles()
        parametres = ParametresRegles(
            sell_through_min_reassort=st.slider("Réassort : sell-through minimum", 0.3, 1.0,
                                                defaut.sell_through_min_reassort, 0.05),
            couverture_max_reassort=st.slider("Réassort : couverture maximum (sem.)", 1.0, 8.0,
                                              defaut.couverture_max_reassort, 0.5),
            couverture_cible=st.slider("Couverture cible après action (sem.)", 2.0, 12.0,
                                       defaut.couverture_cible, 1.0),
            couverture_surstock=st.slider("Transfert : surstock au-delà de (sem.)", 4.0, 30.0,
                                          defaut.couverture_surstock, 1.0),
            couverture_tension=st.slider("Transfert : tension en dessous de (sem.)", 0.5, 4.0,
                                         defaut.couverture_tension, 0.5),
            sell_through_max_demarque=st.slider("Démarque : sell-through maximum", 0.05, 0.6,
                                                defaut.sell_through_max_demarque, 0.05),
        )

# Application des filtres (liste vide = pas de filtre)
filtre = pd.Series(True, index=donnees.index)
if categories:
    filtre &= donnees["categorie"].isin(categories)
if types_pdv:
    filtre &= donnees["type_pdv"].isin(types_pdv)
if villes:
    filtre &= donnees["ville"].isin(villes)
donnees_filtrees = donnees[filtre]

if donnees_filtrees.empty:
    st.warning("Aucune donnée pour cette combinaison de filtres.")
    st.stop()

description_filtres = " / ".join(
    ", ".join(valeurs) for valeurs in [categories, [LIBELLES_TYPES.get(t, t) for t in types_pdv], villes] if valeurs
) or "tout le réseau"

# ---------------------------------------------------------------------------
# Calculs
# ---------------------------------------------------------------------------
globaux = kpis_globaux(donnees_filtrees)
kpis_references = kpis_par(donnees_filtrees, ["reference", "nom_produit", "categorie"])
kpis_categories = kpis_par(donnees_filtrees, ["categorie"])
kpis_points_de_vente = kpis_par(donnees_filtrees, ["point_de_vente", "type_pdv", "ville"])
recommandations = generer_recommandations(donnees_filtrees, parametres)

# ---------------------------------------------------------------------------
# En-tête et chiffres clés
# ---------------------------------------------------------------------------
st.title("Sell-Through Analyzer")
st.caption(f"Collection automne-hiver · semaine {globaux['derniere_semaine']} · {description_filtres} · "
           f"{globaux['nb_references']} références, {globaux['nb_points_de_vente']} points de vente. "
           + ("**Données fictives** (marque et revendeurs inventés)." if source == "Jeu fictif Fjelda" else ""))

colonnes = st.columns(5)
colonnes[0].metric("CA de gros", f"{globaux['ca_gros'] / 1000:,.0f} k€".replace(",", " "),
                   help=f"{globaux['ca_gros']:,.0f} € : unités vendues x prix de gros".replace(",", " "))
colonnes[1].metric("Sell-through", f"{globaux['sell_through']:.0%}",
                   help="Unités vendues / unités livrées")
colonnes[2].metric("Vendues", f"{globaux['unites_vendues']:,}".replace(",", " "),
                   help=f"sur {globaux['unites_livrees']} livrées")
colonnes[3].metric("Couverture", f"{globaux['couverture_semaines']:.1f}".replace(".", ","),
                   help="En semaines : stock restant / ventes moyennes des 4 dernières semaines")
colonnes[4].metric("Ruptures", f"{globaux['nb_ruptures']}",
                   help=f"Couples référence x point de vente sans stock, sur {globaux['nb_couples_ref_pdv']}")

onglets = st.tabs(["Vue d'ensemble", "Références", "Points de vente", "Recommandations", "Rapport"])

# --- Vue d'ensemble ---------------------------------------------------------
with onglets[0]:
    gauche, droite = st.columns(2)
    with gauche:
        titre("Sell-through par catégorie")
        st.plotly_chart(graphique_sell_through(kpis_categories, "categorie", "categorie", COULEURS_CATEGORIES)
                        .update_layout(showlegend=False), width="stretch", key="graph_categories")
    with droite:
        titre("Ventes hebdomadaires")
        hebdo = ventes_hebdomadaires(donnees_filtrees, "categorie")
        figure = px.line(hebdo, x="semaine", y="qte_vendue", color="categorie", markers=True,
                         color_discrete_map=COULEURS_CATEGORIES,
                         labels={"semaine": "Semaine", "qte_vendue": "Unités vendues", "categorie": "Catégorie"})
        figure.update_traces(line_width=2, marker_size=7)
        figure.update_layout(hovermode="x unified")
        st.plotly_chart(mise_en_forme_graphique(figure), width="stretch", key="graph_hebdo")

    titre("CA de gros par type de point de vente")
    kpis_types = kpis_par(donnees_filtrees, ["type_pdv"]).assign(
        libelle=lambda t: t["type_pdv"].map(LIBELLES_TYPES)).sort_values("ca_gros")
    figure = px.bar(kpis_types, x="ca_gros", y="libelle", orientation="h", color="type_pdv",
                    color_discrete_map=COULEURS_TYPES,
                    text=kpis_types["ca_gros"].map(lambda v: f"{v:,.0f} €".replace(",", " ")),
                    labels={"ca_gros": "CA de gros (€)", "libelle": ""})
    figure.update_traces(textposition="outside", cliponaxis=False,
                         hovertemplate="<b>%{y}</b><br>CA de gros : %{x:,.0f} €<extra></extra>")
    st.plotly_chart(mise_en_forme_graphique(figure, 240).update_layout(showlegend=False),
                    width="stretch", key="graph_types")

# --- Références -------------------------------------------------------------
with onglets[1]:
    top, flop = top_flop(kpis_references, n=10)
    gauche, droite = st.columns(2)
    with gauche:
        titre("Top 10 : ce qui se vend")
        st.plotly_chart(graphique_sell_through(top, "nom_produit", "categorie", COULEURS_CATEGORIES, 420),
                        width="stretch", key="graph_top")
    with droite:
        titre("Flop 10 : ce qui stagne")
        st.plotly_chart(graphique_sell_through(flop, "nom_produit", "categorie", COULEURS_CATEGORIES, 420),
                        width="stretch", key="graph_flop")
    titre("Toutes les références")
    tableau_kpis(kpis_references.sort_values("sell_through", ascending=False),
                 ["reference", "nom_produit", "categorie", "qte_livree", "qte_vendue", "stock_actuel",
                  "sell_through", "rythme_hebdo", "couverture_semaines", "ca_gros"])
    st.caption(f"Une couverture de {COUVERTURE_MAX:.0f} semaines signifie qu'il reste du stock "
               "mais aucune vente sur les 4 dernières semaines.")

# --- Points de vente --------------------------------------------------------
with onglets[2]:
    titre("Sell-through par point de vente")
    graphique = graphique_sell_through(
        kpis_points_de_vente.assign(type_pdv=lambda t: t["type_pdv"]), "point_de_vente", "type_pdv",
        COULEURS_TYPES, max(380, 24 * len(kpis_points_de_vente)))
    graphique.for_each_trace(lambda trace: trace.update(name=LIBELLES_TYPES.get(trace.name, trace.name)))
    st.plotly_chart(graphique, width="stretch", key="graph_pdv")
    tableau_kpis(kpis_points_de_vente.sort_values("sell_through", ascending=False),
                 ["point_de_vente", "type_pdv", "ville", "qte_livree", "qte_vendue", "stock_actuel",
                  "sell_through", "couverture_semaines", "ca_gros"])

# --- Recommandations --------------------------------------------------------
with onglets[3]:
    reassorts = recommandations["reassorts"]
    transferts = recommandations["transferts"]
    demarques = recommandations["demarques"]
    alertes_taille = recommandations["ruptures_taille"]

    resume = st.columns(4)
    resume[0].metric("Réassorts", len(reassorts),
                     f"{int(reassorts['qte_reassort'].sum()) if not reassorts.empty else 0} unités", delta_color="off", delta_arrow="off")
    resume[1].metric("Transferts", len(transferts),
                     f"{int(transferts['quantite'].sum()) if not transferts.empty else 0} unités", delta_color="off", delta_arrow="off")
    resume[2].metric("Démarques", len(demarques))
    resume[3].metric("Ruptures de taille", len(alertes_taille))

    def section(intitule: str, explication: str, tableau: pd.DataFrame, nom_fichier: str):
        """Bloc d'une recommandation : règle appliquée, tableau, export CSV."""
        titre(intitule)
        st.caption(explication)
        if tableau.empty:
            st.info("Aucune action proposée avec les seuils actuels.")
            return
        tableau_kpis(tableau, list(tableau.columns))
        st.download_button(f"Exporter ({len(tableau)} lignes, CSV)", tableau.to_csv(index=False).encode("utf-8"),
                           file_name=nom_fichier, mime="text/csv", key=nom_fichier)

    section("1. Transferts entre points de vente",
            f"Un point de vente à plus de {parametres.couverture_surstock:.0f} semaines de stock cède son excédent "
            f"à un point de vente sous {parametres.couverture_tension:.1f} semaines. Priorité avant tout réassort.",
            transferts, "transferts.csv")
    section("2. Réassorts",
            f"Sell-through ≥ {parametres.sell_through_min_reassort:.0%} et couverture < "
            f"{parametres.couverture_max_reassort:.1f} semaines. Quantité = de quoi tenir "
            f"{parametres.couverture_cible:.0f} semaines, moins les unités reçues en transfert.",
            reassorts, "reassorts.csv")
    section("3. Démarques à envisager",
            f"Après {parametres.semaines_min_demarque} semaines : sell-through réseau < "
            f"{parametres.sell_through_max_demarque:.0%} et plus de {parametres.couverture_min_demarque:.0f} semaines "
            f"de stock. -{parametres.taux_demarque:.0%}, ou -{parametres.taux_demarque_forte:.0%} sous "
            f"{parametres.sell_through_demarque_forte:.0%} de sell-through.",
            demarques, "demarques.csv")
    section("4. Ruptures de taille",
            "Une ou plusieurs tailles épuisées alors que la référence reste en stock dans d'autres tailles : "
            "courbe de tailles à revoir au prochain achat.",
            alertes_taille, "ruptures_taille.csv")

# --- Rapport ----------------------------------------------------------------
with onglets[4]:
    titre("Note au directeur commercial")
    if "texte_ia" not in st.session_state:
        st.session_state.texte_ia = None

    compteur = compteur_rapports_ia()
    if compteur["jour"] != date.today():  # nouveau jour : on repart de zéro
        compteur.update(jour=date.today(), nombre=0)
    limite = limite_rapports_par_jour()

    if cle_api_disponible() and limite == 0:
        st.info("Synthèse IA désactivée sur cette version de démonstration. "
                "Le rapport ci-dessous reste exportable avec les recommandations par règles.")
    elif cle_api_disponible():
        restants = max(0, limite - compteur["nombre"])
        st.caption("Seuls les KPIs agrégés et les recommandations sont envoyés à Claude, jamais les données brutes. "
                   f"Synthèses restantes aujourd'hui : {restants}.")
        if st.button("Générer la synthèse IA", type="primary", disabled=restants == 0):
            # nouvelle vérification au clic : un autre visiteur a pu utiliser la dernière synthèse entre-temps
            if compteur["nombre"] >= limite:
                st.warning("Limite de synthèses IA atteinte pour aujourd'hui.")
                st.stop()
            compteur["nombre"] += 1  # compté avant l'appel : un double-clic ne contourne pas la limite
            with st.spinner("Rédaction de la note en cours..."):
                try:
                    st.session_state.texte_ia = rapport_ia_en_cache(
                        construire_contexte(donnees_filtrees, recommandations))
                except RuntimeError as erreur:
                    st.error(str(erreur))
    else:
        st.info("Synthèse IA désactivée : aucune clé API trouvée. Ajoute ANTHROPIC_API_KEY dans un fichier .env "
                "(voir .env.example). Le rapport ci-dessous reste exportable avec les recommandations par règles.")

    if st.session_state.texte_ia:
        with st.container(border=True):
            st.markdown(st.session_state.texte_ia)

    rapport = construire_rapport_markdown(globaux, recommandations, st.session_state.texte_ia, description_filtres)
    export_md, export_pdf = st.columns(2)
    export_md.download_button("Télécharger en Markdown", rapport.encode("utf-8"),
                              file_name="rapport_sell_through.md", mime="text/markdown",
                              width="stretch")
    export_pdf.download_button("Télécharger en PDF", markdown_vers_pdf(rapport),
                               file_name="rapport_sell_through.pdf", mime="application/pdf",
                               width="stretch")
    with st.expander("Aperçu du rapport complet"):
        st.markdown(rapport)
