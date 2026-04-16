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
    ]
    goal_lines = split_lines(mandat["intervention_goal"])
    lines += [f"- {g}" for g in goal_lines] if goal_lines else ["—"]
    lines.append("")

    lines += ["## 🔍 Problème rapporté", probleme.get("reported_issue") or "—", ""]

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
        lines += ["## 📁 Références utiles"] + [f"- {x}" for x in split_lines(technique["references_utiles"])] + [""]

    if reflexion["risks"]:
        lines += ["## ⚠️ Risques identifiés"] + [f"- {r}" for r in reflexion["risks"]] + [""]

    lines.append("## ✅ Vérifications prioritaires")
    lines += [f"- {item}" for item in reflexion["priority_checks"]] if reflexion["priority_checks"] else ["—"]
    lines.append("")

    lines.append("## 🔧 Plan d'action")
    lines += [f"{i}. {item}" for i, item in enumerate(reflexion["action_plan"], 1)] if reflexion["action_plan"] else ["—"]
    lines.append("")

    if reflexion["hypotheses"]:
        lines += ["## 💡 Hypothèses"] + [f"- {h}" for h in reflexion["hypotheses"]] + [""]

    if reflexion["tools_access_needed"]:
        lines += ["## 🧰 Outils / Stock"] + [f"- {item}" for item in reflexion["tools_access_needed"]] + [""]

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
    goal_lines = split_lines(mandat["intervention_goal"])
    if goal_lines:
        story.append(ListFlowable([ListItem(Paragraph(g, small)) for g in goal_lines], bulletType="bullet", leftIndent=14))
    else:
        story.append(Paragraph("—", body))
    story.append(Spacer(1, 8))

    def add_section(title: str, text: str) -> None:
        story.append(Paragraph(title, heading2))
        story.append(Paragraph((text or "—").replace("\n", "<br/>"), body))
        story.append(Spacer(1, 4))

    def add_bullets(title: str, items: List[str]) -> None:
        if not items:
            return
        story.append(Paragraph(title, heading2))
        story.append(ListFlowable([ListItem(Paragraph(item, small)) for item in items], bulletType="bullet", leftIndent=14))
        story.append(Spacer(1, 4))

    add_section("Problème rapporté", probleme.get("reported_issue", ""))

    history = technique.get("history_context", "")
    if clean_text(history):
        add_section("Contexte technique", history)

    story.append(Paragraph("Environnement technique", heading2))
    story.append(Paragraph(
        f"<b>Systèmes :</b> {', '.join(technique['systems_present']) if technique['systems_present'] else '—'}",
        body,
    ))
    if clean_text(technique["attempts_summary"]):
        story.append(Paragraph("<b>Tentatives :</b>", label))
        story.append(Paragraph(technique["attempts_summary"].replace("\n", "<br/>"), body))
    if clean_text(technique["site_constraints"]):
        story.append(Paragraph(f"<b>Contraintes :</b> {technique['site_constraints']}", body))
    story.append(Spacer(1, 6))

    add_bullets("Références utiles",        split_lines(technique["references_utiles"]))
    add_bullets("Risques identifiés",        reflexion["risks"])
    add_bullets("Vérifications prioritaires", reflexion["priority_checks"])
    add_bullets("Plan d'action",             reflexion["action_plan"])
    add_bullets("Hypothèses",               reflexion["hypotheses"])
    add_bullets("Outils / Stock",           reflexion["tools_access_needed"])

    doc.build(story)
    return buffer.getvalue()


def encode_pdf_base64(payload: Dict[str, Any]) -> Optional[str]:
    try:
        return base64.b64encode(generate_pdf(payload)).decode("utf-8")
    except Exception:
        return None
