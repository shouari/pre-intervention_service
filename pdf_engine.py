"""
pdf_engine.py — Génération PDF et rendu Markdown de la fiche d'intervention.
"""
from __future__ import annotations

import base64
import io
from typing import Any, Dict, List, Optional

from utils import clean_text, split_lines

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable, ListFlowable, ListItem, Paragraph,
        SimpleDocTemplate, Spacer, Table, TableStyle,
    )
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


# ─── Markdown ──────────────────────────────────────────────

def markdown_to_reportlab(text: str) -> str:
    """Traduit quelques balises Markdown simples en tags ReportLab (Paragraph)."""
    import re
    if not text:
        return "—"
    # Escaper les caractères spéciaux HTML que Paragraph pourrait mal interpréter
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Rétablir les tags qu'on veut utiliser
    text = text.replace("&lt;br/&gt;", "<br/>").replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>").replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")

    # Bold **text**
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    # Italic *text*
    text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
    # Bullets - item
    text = re.sub(r"^(\s*)-\s+", r"\1• ", text, flags=re.MULTILINE)
    # Line breaks
    text = text.replace("\n", "<br/>")
    return text


def report_markdown(payload: Dict[str, Any]) -> str:
    mandat    = payload["mandat"]
    probleme  = payload["probleme"]
    technique = payload["technique"]
    reflexion = payload["reflexion"]

    def row(icon: str, label: str, val: str) -> str:
        return f"| {icon} **{label}** | {val or '—'} |"

    lines: List[str] = [
        "# Fiche d'intervention", "",
        "## 📋 Mandat", "",
        "|  |  |", "|---|---|",
        row("🏢", "Client",      mandat["client_name"]),
        row("🏷️", "Appel #",    mandat.get("service_call", "")),
        row("📍", "Adresse",     mandat["address"]),
        row("👤", "Contact",     mandat["contact_name"]),
        row("📞", "Téléphone",   mandat["contact_phone"]),
        row("📅", "Date / heure", mandat["scheduled_datetime"]),
        row("🔧", "Technicien",  mandat["assigned_technician"]),
        "",
        "**🎯 Objectif :**",
        mandat["intervention_goal"] or "—",
        "",
        "## 🔍 Problème rapporté",
        probleme.get("reported_issue") or "—",
        "",
    ]

    history = technique.get("history_context") or ""
    if clean_text(history):
        lines += ["**Contexte technique**", history, ""]

    lines.append("## ⚙️ Environnement technique")
    lines.append(f"**Systèmes** : {', '.join(technique['systems_present']) if technique['systems_present'] else '—'}")
    if clean_text(technique["attempts_summary"]):
        lines += ["", "**Tentatives et résultats**", technique["attempts_summary"]]
    if clean_text(technique["site_constraints"]):
        lines += ["", f"**Contraintes** : {technique['site_constraints']}"]
    lines.append("")

    if clean_text(technique["references_utiles"]):
        lines += ["## 📁 Références utiles", technique["references_utiles"], ""]

    if clean_text(reflexion.get("risks")):
        lines += ["## ⚠️ Risques identifiés", reflexion["risks"], ""]

    lines.append("## ✅ Vérifications prioritaires")
    lines.append(reflexion.get("priority_checks") or "—")
    lines.append("")

    lines.append("## 🔧 Plan d'action")
    lines.append(reflexion.get("action_plan") or "—")
    lines.append("")

    if clean_text(reflexion.get("hypotheses")):
        lines += ["## 💡 Hypothèses", reflexion["hypotheses"], ""]

    if clean_text(reflexion.get("tools_access_needed")):
        lines += ["## 🧰 Outils / Stock", reflexion["tools_access_needed"], ""]

    return "\n".join(lines)


# ─── PDF ───────────────────────────────────────────────────

def generate_pdf(payload: Dict[str, Any]) -> bytes:
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("ReportLab n'est pas installé (pip install reportlab).")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
    )

    styles   = getSampleStyleSheet()
    heading2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11, spaceAfter=3, spaceBefore=10)
    body     = ParagraphStyle("body", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13, spaceAfter=4)
    small    = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11, spaceAfter=2)
    label    = ParagraphStyle("label", parent=body, fontName="Helvetica-Bold", fontSize=9.5)

    mandat    = payload["mandat"]
    probleme  = payload["probleme"]
    technique = payload["technique"]
    reflexion = payload["reflexion"]

    story = [
        Paragraph("Fiche d'intervention", styles["Title"]),
        Spacer(1, 4),
        HRFlowable(width="100%", thickness=1, color="#cccccc"),
        Spacer(1, 6),
    ]

    mandat_rows = [
        ["Client",      mandat["client_name"] or "—"],
        ["Appel #",     mandat.get("service_call", "") or "—"],
        ["Adresse",     mandat["address"] or "—"],
        ["Contact",     mandat["contact_name"] or "—"],
        ["Téléphone",   mandat["contact_phone"] or "—"],
        ["Date / heure", mandat["scheduled_datetime"] or "—"],
        ["Technicien",  mandat["assigned_technician"] or "—"],
    ]
    tbl = Table(
        [[Paragraph(f"<b>{r[0]}</b>", body), Paragraph(r[1], body)] for r in mandat_rows],
        colWidths=[42 * mm, None], hAlign="LEFT",
    )
    tbl.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS",(0, 0), (-1, -1), [colors.HexColor("#f5f5f5"), colors.white]),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("LINEBELOW",    (0, -1), (-1, -1), 0.5, colors.HexColor("#dddddd")),
    ]))
    story += [tbl, Spacer(1, 5), Paragraph("<b>Objectif :</b>", body)]
    story.append(Paragraph(markdown_to_reportlab(mandat["intervention_goal"]), body))
    story.append(Spacer(1, 8))

    def add_markdown_section(title: str, text: str) -> None:
        if not clean_text(text):
            return
        story.append(Paragraph(title, heading2))
        story.append(Paragraph(markdown_to_reportlab(text), body))
        story.append(Spacer(1, 4))

    add_markdown_section("Problème rapporté", probleme.get("reported_issue", ""))
    add_markdown_section("Contexte technique", technique.get("history_context", ""))

    story.append(Paragraph("Environnement technique", heading2))
    story.append(Paragraph(
        f"<b>Systèmes :</b> {', '.join(technique['systems_present']) if technique['systems_present'] else '—'}",
        body,
    ))
    if clean_text(technique["attempts_summary"]):
        story.append(Paragraph("<b>Tentatives :</b>", label))
        story.append(Paragraph(markdown_to_reportlab(technique["attempts_summary"]), body))
    if clean_text(technique["site_constraints"]):
        story.append(Paragraph(markdown_to_reportlab(f"**Contraintes :** {technique['site_constraints']}"), body))
    story.append(Spacer(1, 6))

    add_markdown_section("Références utiles",        technique["references_utiles"])
    add_markdown_section("Risques identifiés",        reflexion["risks"])
    add_markdown_section("Vérifications prioritaires", reflexion["priority_checks"])
    add_markdown_section("Plan d'action",             reflexion["action_plan"])
    add_markdown_section("Hypothèses",               reflexion["hypotheses"])
    add_markdown_section("Outils / Stock",           reflexion["tools_access_needed"])

    doc.build(story)
    return buffer.getvalue()


def encode_pdf_base64(payload: Dict[str, Any]) -> Optional[str]:
    try:
        return base64.b64encode(generate_pdf(payload)).decode("utf-8")
    except Exception:
        return None
