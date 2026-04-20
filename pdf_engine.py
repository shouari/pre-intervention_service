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
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable, KeepTogether, Paragraph,
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
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("&lt;br/&gt;", "<br/>").replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>").replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
    text = re.sub(r"^(\s*)-\s+", r"\1• ", text, flags=re.MULTILINE)
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

    # Brand palette
    NAVY  = HexColor("#0D1B2A")
    RED   = HexColor("#E8312A")
    LGRAY = HexColor("#F7F8FA")
    MGRAY = HexColor("#EAEDF0")
    DGRAY = HexColor("#9AAABB")
    WHITE = colors.white

    L_MARGIN = R_MARGIN = 18 * mm
    T_MARGIN = 30 * mm   # room for header band
    B_MARGIN = 22 * mm   # room for footer
    CW = A4[0] - L_MARGIN - R_MARGIN  # content width

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=L_MARGIN, rightMargin=R_MARGIN,
        topMargin=T_MARGIN,  bottomMargin=B_MARGIN,
    )

    # ── Typography ────────────────────────────────────────────
    body = ParagraphStyle(
        "cs_body", fontName="Helvetica", fontSize=9.5,
        leading=14, spaceAfter=3, textColor=HexColor("#1A2533"),
    )
    body_bold = ParagraphStyle(
        "cs_body_bold", fontName="Helvetica-Bold", fontSize=9.5,
        leading=14, spaceAfter=3, textColor=HexColor("#1A2533"),
    )
    title_style = ParagraphStyle(
        "cs_title", fontName="Helvetica-Bold", fontSize=20,
        leading=24, textColor=NAVY, spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "cs_subtitle", fontName="Helvetica", fontSize=10,
        leading=14, textColor=DGRAY, spaceAfter=6,
    )
    section_style = ParagraphStyle(
        "cs_section", fontName="Helvetica-Bold", fontSize=10,
        leading=14, textColor=NAVY,
    )
    lbl_style = ParagraphStyle(
        "cs_lbl", fontName="Helvetica-Bold", fontSize=9.5,
        leading=14, textColor=NAVY,
    )

    mandat    = payload["mandat"]
    probleme  = payload["probleme"]
    technique = payload["technique"]
    reflexion = payload["reflexion"]

    # ── Per-page chrome (header band + footer) ────────────────
    def draw_chrome(canvas, doc):
        canvas.saveState()
        w, h = A4

        # Header: dark band
        canvas.setFillColor(NAVY)
        canvas.rect(0, h - 22 * mm, w, 22 * mm, fill=1, stroke=0)
        # Red accent line at bottom of header
        canvas.setFillColor(RED)
        canvas.rect(0, h - 22 * mm, w, 1.5, fill=1, stroke=0)
        # Header: company name
        canvas.setFont("Helvetica-Bold", 10)
        canvas.setFillColor(WHITE)
        canvas.drawString(L_MARGIN, h - 11 * mm, "GROUPE CS")
        # Header: document type
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(HexColor("#8A99AA"))
        canvas.drawString(L_MARGIN, h - 16.5 * mm, "Fiche de pré-intervention")
        # Header: page number (right)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(HexColor("#C8D5E4"))
        canvas.drawRightString(w - R_MARGIN, h - 13.5 * mm, f"Page {doc.page}")

        # Footer: light band
        canvas.setFillColor(LGRAY)
        canvas.rect(0, 0, w, 14 * mm, fill=1, stroke=0)
        canvas.setFillColor(MGRAY)
        canvas.rect(0, 14 * mm, w, 0.5, fill=1, stroke=0)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(DGRAY)
        canvas.drawString(L_MARGIN, 5 * mm, "Groupe CS — Document confidentiel")
        canvas.drawRightString(w - R_MARGIN, 5 * mm, f"Page {doc.page}")

        canvas.restoreState()

    # ── Helpers ───────────────────────────────────────────────
    def section_header(title: str) -> Table:
        t = Table([[Paragraph(title, section_style)]], colWidths=[CW])
        t.setStyle(TableStyle([
            ("LINEBEFORE",    (0, 0), (0, -1), 3,   RED),
            ("BACKGROUND",    (0, 0), (-1, -1),      LGRAY),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return t

    bullet_style = ParagraphStyle(
        "cs_bullet", fontName="Helvetica", fontSize=9.5,
        leading=14, leftIndent=14, firstLineIndent=-10,
        spaceAfter=2, textColor=HexColor("#1A2533"),
    )

    def bullet_list(text: str) -> List[Paragraph]:
        lines = split_lines(text)
        return [
            Paragraph(
                f'<font color="#E8312A">\u2022</font> {markdown_to_reportlab(ln.lstrip("•- "))}',
                bullet_style,
            )
            for ln in lines
        ]

    def add_section(title: str, text: str, as_bullets: bool = True) -> None:
        if not clean_text(text):
            return
        lines = split_lines(text)
        block: List[Any] = [section_header(title), Spacer(1, 5)]
        if as_bullets and len(lines) > 1:
            block.extend(bullet_list(text))
        else:
            block.append(Paragraph(markdown_to_reportlab(text), body))
        block.append(Spacer(1, 8))
        story.append(KeepTogether(block))

    story: List[Any] = []

    # ── Document title block ──────────────────────────────────
    client_name = mandat.get("client_name") or "—"
    sc          = mandat.get("service_call") or ""
    dt          = mandat.get("scheduled_datetime") or ""
    dt_display  = dt[:16] if len(dt) >= 10 else dt

    story.append(Paragraph(client_name, title_style))
    sub_parts = []
    if sc:
        sub_parts.append(f"Appel #{sc}")
    if dt_display:
        sub_parts.append(dt_display)
    if sub_parts:
        story.append(Paragraph("  ·  ".join(sub_parts), subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1, color=MGRAY, spaceAfter=6))
    story.append(Spacer(1, 4))

    # ── Mandat info table ─────────────────────────────────────
    mandat_rows = [
        ("Adresse",      mandat.get("address")              or ""),
        ("Contact",      mandat.get("contact_name")         or ""),
        ("Téléphone",    mandat.get("contact_phone")        or ""),
        ("Date / heure", mandat.get("scheduled_datetime")   or ""),
        ("Technicien",   mandat.get("assigned_technician")  or ""),
    ]
    mandat_rows = [(k, v) for k, v in mandat_rows if clean_text(str(v))]

    if mandat_rows:
        tbl_data = [
            [Paragraph(f"<b>{k}</b>", lbl_style), Paragraph(str(v), body)]
            for k, v in mandat_rows
        ]
        tbl = Table(tbl_data, colWidths=[38 * mm, CW - 38 * mm], hAlign="LEFT")
        tbl.setStyle(TableStyle([
            ("VALIGN",         (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LGRAY, WHITE]),
            ("LEFTPADDING",    (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 8),
            ("TOPPADDING",     (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
            ("LINEBEFORE",     (0, 0), (0,  -1), 2, NAVY),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 8))

    # ── Objectif (highlighted box) ────────────────────────────
    goal = clean_text(mandat.get("intervention_goal") or "")
    if goal:
        obj_style = ParagraphStyle(
            "cs_obj", fontName="Helvetica", fontSize=10,
            leading=15, textColor=NAVY,
        )
        obj_tbl = Table(
            [[Paragraph(f"<b>Objectif</b><br/>{markdown_to_reportlab(goal)}", obj_style)]],
            colWidths=[CW],
        )
        obj_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1),      HexColor("#FDF3F2")),
            ("LINEBEFORE",    (0, 0), (0,  -1), 3,   RED),
            ("LEFTPADDING",   (0, 0), (-1, -1), 12),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
            ("TOPPADDING",    (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(obj_tbl)
        story.append(Spacer(1, 12))

    # ── Problème + contexte ───────────────────────────────────
    add_section("Problème rapporté",   probleme.get("reported_issue", ""),    as_bullets=False)
    add_section("Contexte technique",  technique.get("history_context", ""),  as_bullets=False)

    # ── Environnement technique ───────────────────────────────
    systems     = technique.get("systems_present") or []
    attempts    = technique.get("attempts_summary") or ""
    constraints = technique.get("site_constraints") or ""

    if systems or clean_text(attempts) or clean_text(constraints):
        env: List[Any] = [section_header("Environnement technique"), Spacer(1, 5)]
        if systems:
            env.append(Paragraph(f"<b>Systèmes :</b> {', '.join(systems)}", body))
        if clean_text(attempts):
            env.append(Paragraph("<b>Tentatives et résultats :</b>", body_bold))
            bl = bullet_list(attempts)
            if bl:
                env.extend(bl)
            else:
                env.append(Paragraph(markdown_to_reportlab(attempts), body))
        if clean_text(constraints):
            env.append(Paragraph(f"<b>Contraintes :</b> {constraints}", body))
        env.append(Spacer(1, 8))
        story.append(KeepTogether(env))

    # ── Remaining sections ────────────────────────────────────
    add_section("Références utiles",          technique.get("references_utiles", ""),    as_bullets=True)
    add_section("Risques identifiés",          reflexion.get("risks", ""),               as_bullets=True)
    add_section("Vérifications prioritaires",  reflexion.get("priority_checks", ""),    as_bullets=True)
    add_section("Plan d'action",               reflexion.get("action_plan", ""),         as_bullets=True)
    add_section("Hypothèses",                 reflexion.get("hypotheses", ""),           as_bullets=True)
    add_section("Outils / Stock à ramasser",  reflexion.get("tools_access_needed", ""),  as_bullets=True)

    doc.build(story, onFirstPage=draw_chrome, onLaterPages=draw_chrome)
    return buffer.getvalue()


def encode_pdf_base64(payload: Dict[str, Any]) -> Optional[str]:
    try:
        return base64.b64encode(generate_pdf(payload)).decode("utf-8")
    except Exception:
        return None
