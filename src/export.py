"""Export du rapport en Markdown et en PDF."""

from datetime import date

import pandas as pd
from fpdf import FPDF


def _euros(montant: float) -> str:
    """Formate un montant : 12345.6 -> '12 346 EUR'."""
    return f"{montant:,.0f} EUR".replace(",", " ")


def construire_rapport_markdown(globaux: dict, recommandations: dict[str, pd.DataFrame],
                                texte_ia: str | None, filtres: str) -> str:
    """Assemble le rapport complet : chiffres clés, actions par règles, synthèse IA."""
    lignes = [
        "# Rapport sell-through - collection Fjelda",
        f"Généré le {date.today():%d/%m/%Y} - semaine {globaux['derniere_semaine']} - périmètre : {filtres}",
        "Données fictives, à des fins de démonstration.",
        "",
        "## Chiffres clés",
        f"- CA de gros réalisé : **{_euros(globaux['ca_gros'])}**",
        f"- Sell-through global : **{globaux['sell_through']:.0%}** "
        f"({globaux['unites_vendues']} unités vendues sur {globaux['unites_livrees']} livrées)",
        f"- Stock restant chez les revendeurs : {globaux['stock_actuel']} unités, "
        f"soit {globaux['couverture_semaines']:.1f} semaines de couverture",
        f"- Ruptures : {globaux['nb_ruptures']} couples référence x point de vente sur {globaux['nb_couples_ref_pdv']}",
        "",
    ]

    if texte_ia:
        # les titres "## ..." de l'IA deviennent des sous-titres "### ..." de cette section
        texte_ia_decale = "\n".join("#" + l if l.startswith("#") else l for l in texte_ia.splitlines())
        lignes += ["## Synthèse IA", "", texte_ia_decale, ""]

    reassorts = recommandations["reassorts"]
    lignes += ["## Réassorts proposés (règles)"]
    if reassorts.empty:
        lignes.append("- Aucun réassort nécessaire.")
    else:
        lignes.append(f"{len(reassorts)} réassorts, {int(reassorts['qte_reassort'].sum())} unités, "
                      f"{_euros(reassorts['ca_gros_potentiel'].sum())} de CA de gros potentiel. Les 10 principaux :")
        for r in reassorts.head(10).itertuples():
            lignes.append(f"- {r.nom_produit} chez {r.point_de_vente} : {r.qte_reassort} unités "
                          f"(sell-through {r.sell_through:.0%}, {r.couverture_semaines} sem. de stock)")
    lignes.append("")

    transferts = recommandations["transferts"]
    lignes += ["## Transferts de stock proposés"]
    if transferts.empty:
        lignes.append("- Aucun transfert pertinent.")
    for t in transferts.sort_values("quantite", ascending=False).head(10).itertuples():
        lignes.append(f"- {t.nom_produit} : {t.quantite} unités de {t.depuis} ({t.ville_depart}) "
                      f"vers {t.vers} ({t.ville_arrivee})")
    lignes.append("")

    demarques = recommandations["demarques"]
    lignes += ["## Démarques à envisager"]
    if demarques.empty:
        lignes.append("- Aucune démarque proposée.")
    for d in demarques.itertuples():
        lignes.append(f"- {d.nom_produit} : -{d.taux_demarque:.0%} (sell-through {d.sell_through:.0%}, "
                      f"{d.stock_actuel} unités en stock, {_euros(d.valeur_stock_gros)} au prix de gros)")
    lignes.append("")

    alertes = recommandations["ruptures_taille"]
    lignes += ["## Ruptures de taille", f"{len(alertes)} cas où une taille manque alors que d'autres restent en stock."]
    for a in alertes.head(5).itertuples():
        lignes.append(f"- {a.nom_produit} chez {a.point_de_vente} : tailles {a.tailles_en_rupture} épuisées")
    return "\n".join(lignes)


def _texte_pdf(texte: str) -> str:
    """Les polices intégrées du PDF ne gèrent que l'alphabet latin de base :
    on remplace les quelques caractères typographiques qui poseraient problème."""
    remplacements = {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                     "…": "...", "€": "EUR", "•": "-", "≥": ">=", "≤": "<=", "→": "->", " ": " "}
    for caractere, remplacement in remplacements.items():
        texte = texte.replace(caractere, remplacement)
    return texte.encode("latin-1", errors="replace").decode("latin-1")


def markdown_vers_pdf(markdown: str) -> bytes:
    """Convertit le Markdown simple du rapport (titres, puces, gras) en PDF."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(18, 18, 18)

    for ligne in markdown.splitlines():
        ligne = _texte_pdf(ligne.rstrip())
        if ligne.startswith("# "):
            pdf.set_font("Helvetica", "B", 17)
            pdf.multi_cell(0, 9, ligne[2:], new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif ligne.startswith("## "):
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(42, 120, 214)
            pdf.multi_cell(0, 7, ligne[3:], new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
        elif ligne.startswith("### "):
            pdf.set_font("Helvetica", "B", 11)
            pdf.multi_cell(0, 6, ligne[4:], new_x="LMARGIN", new_y="NEXT")
        elif not ligne.strip():
            pdf.ln(2)
        else:
            pdf.set_font("Helvetica", "", 10)
            est_puce = ligne.lstrip().startswith(("- ", "* "))
            if est_puce:
                # la puce est dessinée dans une petite cellule, le texte à côté
                pdf.set_x(pdf.l_margin + 3)
                pdf.cell(4, 5.5, "-")
                ligne = ligne.lstrip()[2:]
            pdf.multi_cell(0, 5.5, ligne, markdown=True, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
