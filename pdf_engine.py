"""
pdf_engine.py — Génération PDF et rendu Markdown de la fiche d'intervention.
"""
from __future__ import annotations

import base64
import io
import re
from typing import Any, Dict, List, Optional

from utils import clean_text

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


# ─── Inline helpers ────────────────────────────────────────

# Characters outside Helvetica's WinAnsi encoding — replace before rendering.
_CHAR_MAP = {
    "\u2192": "->",    # →
    "\u2190": "<-",    # ←
    "\u21d2": "=>",    # ⇒
    "\u2713": "(OK)",  # ✓
    "\u2717": "(X)",   # ✗
    "\u2014": "--",    # em dash fallback (actually supported, but just in case)
}

def _sanitize(text: str) -> str:
    for ch, rep in _CHAR_MAP.items():
        text = text.replace(ch, rep)
    return text

def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _inline(text: str) -> str:
    """Inline Markdown → ReportLab XML. Input must already be HTML-escaped."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+)`", r'<font face="Courier" color="#4A5568">\1</font>', text)
    return text

def _fmt(text: str) -> str:
    """Sanitize → HTML-escape → apply inline Markdown. Ready for Paragraph XML."""
    return _inline(_escape(_sanitize(text)))


# ─── Block Markdown → flowables ───────────────────────────
#
# S (styles dict) keys required:
#   body, bullet, numbered, sub_detail, h2, h3, blockquote, code_block, cw

def md_to_flowables(text: str, S: dict) -> List[Any]:
    """Parse a Markdown string into a list of ReportLab flowables."""
    if not text or not text.strip():
        return [Paragraph("—", S["body"])]

    result: List[Any] = []
    lines = text.split("\n")
    i = 0

    while i < len(lines):
        raw = lines[i]
        s   = raw.strip()

        # ── Fenced code block ```…```
        if s.startswith("```"):
            code_lines: List[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # consume closing ```
            code_esc = _escape("\n".join(code_lines)).replace("\n", "<br/>")
            box = Table(
                [[Paragraph(code_esc or " ", S["code_block"])]],
                colWidths=[S["cw"]],
            )
            box.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), HexColor("#EEF0F3")),
                ("LINEBEFORE",    (0, 0), (0,  -1), 2, HexColor("#9AAABB")),
                ("LEFTPADDING",   (0, 0), (-1, -1), 10),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
                ("TOPPADDING",    (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]))
            result.append(box)
            continue

        # ── Headings # / ## / ###
        m = re.match(r"^(#{1,3})\s+(.*)", s)
        if m:
            style = S["h3"] if len(m.group(1)) == 3 else S["h2"]
            result.append(Paragraph(_fmt(m.group(2)), style))
            i += 1
            continue

        # ── Horizontal rule ---  ___  ***
        if re.match(r"^(-{3,}|_{3,}|\*{3,})$", s):
            result.append(HRFlowable(width="100%", thickness=0.5,
                                     color=HexColor("#EAEDF0"), spaceAfter=4))
            i += 1
            continue

        # ── Markdown table  | col | col |
        if s.startswith("|"):
            table_lines: List[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            # Drop separator rows (|---|---|)
            parsed_rows: List[List[str]] = []
            for tl in table_lines:
                cells = [c.strip() for c in tl.strip("|").split("|")]
                if all(re.match(r"^:?-+:?$", c) for c in cells if c):
                    continue
                parsed_rows.append(cells)
            if parsed_rows:
                num_cols = max(len(r) for r in parsed_rows)
                col_w = S["cw"] / num_cols
                hdr_p = ParagraphStyle(
                    "md_th", fontName="Helvetica-Bold", fontSize=9,
                    leading=13, textColor=colors.white,
                )
                cell_p = ParagraphStyle(
                    "md_td", fontName="Helvetica", fontSize=9,
                    leading=13, textColor=HexColor("#1A2533"),
                )
                tbl_data: List[List[Any]] = []
                for r_idx, row in enumerate(parsed_rows):
                    padded = (row + [""] * num_cols)[:num_cols]
                    p_style = hdr_p if r_idx == 0 else cell_p
                    tbl_data.append([Paragraph(_fmt(c), p_style) for c in padded])
                md_tbl = Table(tbl_data, colWidths=[col_w] * num_cols)
                md_tbl.setStyle(TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, 0),  HexColor("#0D1B2A")),
                    ("ROWBACKGROUNDS",(0, 1), (-1, -1), [HexColor("#F7F8FA"), colors.white]),
                    ("GRID",          (0, 0), (-1, -1), 0.5, HexColor("#CACED5")),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
                    ("TOPPADDING",    (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ]))
                result.append(md_tbl)
                result.append(Spacer(1, 4))
            continue

        # ── Blockquote >
        if s.startswith("> "):
            result.append(Paragraph(_fmt(s[2:]), S["blockquote"]))
            i += 1
            continue

        # ── Unordered list  - item  or  * item
        if re.match(r"^[-*]\s+", s):
            while i < len(lines):
                s2 = lines[i].strip()
                m2 = re.match(r"^[-*]\s+(.*)", s2)
                if m2:
                    result.append(Paragraph(
                        f'<font color="#E8312A">\u2022</font> {_fmt(m2.group(1))}',
                        S["bullet"],
                    ))
                    i += 1
                elif not s2:
                    i += 1
                    break
                else:
                    break
            continue

        # ── Numbered list  1.  or  1)
        if re.match(r"^\d+[.)]\s+", s):
            n = 1
            while i < len(lines):
                s2 = lines[i].strip()
                m2 = re.match(r"^\d+[.)]\s+(.*)", s2)
                if m2:
                    result.append(Paragraph(
                        f'<font color="#E8312A"><b>{n}.</b></font> {_fmt(m2.group(1))}',
                        S["numbered"],
                    ))
                    n += 1
                    i += 1
                elif not s2:
                    i += 1
                    break
                else:
                    break
            continue

        # ── Indented continuation (≥2 leading spaces) — AI sub-detail lines
        if len(raw) > len(s) and raw[:2] == "  " and s:
            result.append(Paragraph(_fmt(s), S["sub_detail"]))
            i += 1
            continue

        # ── Empty line → small spacer
        if not s:
            result.append(Spacer(1, 4))
            i += 1
            continue

        # ── Body paragraph — collect consecutive plain lines
        para: List[str] = []
        while i < len(lines):
            s2 = lines[i].strip()
            if not s2:
                break
            if (re.match(r"^#{1,3}\s+", s2) or
                    re.match(r"^[-*]\s+", s2) or
                    re.match(r"^\d+[.)]\s+", s2) or
                    s2.startswith("> ") or
                    s2.startswith("|") or
                    s2.startswith("```") or
                    re.match(r"^(-{3,}|_{3,}|\*{3,})$", s2)):
                break
            para.append(_fmt(s2))
            i += 1
        if para:
            result.append(Paragraph("<br/>".join(para), S["body"]))

    return result or [Paragraph("—", S["body"])]


# ─── Legacy single-paragraph helper ───────────────────────
# Used only inside generate_pdf where a single Paragraph string is needed.

def markdown_to_reportlab(text: str) -> str:
    if not text:
        return "—"
    return _inline(_escape(_sanitize(text))).replace("\n", "<br/>")


# ─── Streamlit preview ─────────────────────────────────────

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
        row("🏢", "Client",       mandat["client_name"]),
        row("🏷️", "Appel #",     mandat.get("service_call", "")),
        row("📍", "Adresse",      mandat["address"]),
        row("👤", "Contact",      mandat["contact_name"]),
        row("📞", "Téléphone",    mandat["contact_phone"]),
        row("📅", "Date / heure", mandat["scheduled_datetime"]),
        row("🔧", "Technicien",   mandat["assigned_technician"]),
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

    lines += ["## ✅ Vérifications prioritaires", reflexion.get("priority_checks") or "—", ""]
    lines += ["## 🔧 Plan d'action",              reflexion.get("action_plan")     or "—", ""]

    if clean_text(reflexion.get("hypotheses")):
        lines += ["## 💡 Hypothèses", reflexion["hypotheses"], ""]
    if clean_text(reflexion.get("tools_access_needed")):
        lines += ["## 🧰 Outils / Stock", reflexion["tools_access_needed"], ""]

    return "\n".join(lines)


# ─── PDF generation ────────────────────────────────────────

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
    T_MARGIN = 30 * mm
    B_MARGIN = 22 * mm
    CW = A4[0] - L_MARGIN - R_MARGIN

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=L_MARGIN, rightMargin=R_MARGIN,
        topMargin=T_MARGIN, bottomMargin=B_MARGIN,
    )

    # ── Base type styles ──────────────────────────────────────
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

    # ── Markdown styles (passed into md_to_flowables) ─────────
    md_styles: dict = {
        "cw": CW,
        "body": body,
        "bullet": ParagraphStyle(
            "cs_bullet", fontName="Helvetica", fontSize=9.5,
            leading=14, leftIndent=18, firstLineIndent=-13,
            spaceAfter=2, textColor=HexColor("#1A2533"),
        ),
        "numbered": ParagraphStyle(
            "cs_numbered", fontName="Helvetica", fontSize=9.5,
            leading=14, leftIndent=22, firstLineIndent=-16,
            spaceAfter=2, textColor=HexColor("#1A2533"),
        ),
        "sub_detail": ParagraphStyle(
            "cs_sub", fontName="Helvetica", fontSize=8.5,
            leading=12, leftIndent=20, spaceAfter=3,
            textColor=HexColor("#556678"),
        ),
        "h2": ParagraphStyle(
            "cs_md_h2", fontName="Helvetica-Bold", fontSize=11,
            leading=15, spaceBefore=8, spaceAfter=4, textColor=NAVY,
        ),
        "h3": ParagraphStyle(
            "cs_md_h3", fontName="Helvetica-Bold", fontSize=10,
            leading=14, spaceBefore=6, spaceAfter=3,
            textColor=HexColor("#1A3050"),
        ),
        "blockquote": ParagraphStyle(
            "cs_bq", fontName="Helvetica-Oblique", fontSize=9,
            leading=13, leftIndent=14, spaceAfter=3,
            textColor=HexColor("#556678"),
        ),
        "code_block": ParagraphStyle(
            "cs_code", fontName="Courier", fontSize=8.5,
            leading=13, textColor=HexColor("#2D3748"),
        ),
    }

    mandat    = payload["mandat"]
    probleme  = payload["probleme"]
    technique = payload["technique"]
    reflexion = payload["reflexion"]

    # ── Per-page chrome ───────────────────────────────────────
    def draw_chrome(canvas, doc):
        canvas.saveState()
        w, h = A4

        canvas.setFillColor(NAVY)
        canvas.rect(0, h - 22 * mm, w, 22 * mm, fill=1, stroke=0)
        canvas.setFillColor(RED)
        canvas.rect(0, h - 22 * mm, w, 1.5, fill=1, stroke=0)

        canvas.setFont("Helvetica-Bold", 10)
        canvas.setFillColor(WHITE)
        canvas.drawString(L_MARGIN, h - 11 * mm, "GROUPE CS")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(HexColor("#8A99AA"))
        canvas.drawString(L_MARGIN, h - 16.5 * mm, "Fiche de pré-intervention")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(HexColor("#C8D5E4"))
        canvas.drawRightString(w - R_MARGIN, h - 13.5 * mm, f"Page {doc.page}")

        canvas.setFillColor(LGRAY)
        canvas.rect(0, 0, w, 14 * mm, fill=1, stroke=0)
        canvas.setFillColor(MGRAY)
        canvas.rect(0, 14 * mm, w, 0.5, fill=1, stroke=0)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(DGRAY)
        canvas.drawString(L_MARGIN, 5 * mm, "Groupe CS — Document confidentiel")
        canvas.drawRightString(w - R_MARGIN, 5 * mm, f"Page {doc.page}")

        canvas.restoreState()

    # ── Layout helpers ────────────────────────────────────────
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

    def add_section(title: str, text: str) -> None:
        if not clean_text(text):
            return
        inner = md_to_flowables(text, md_styles)
        # Keep header + first two items together so titles never orphan at page bottom
        story.append(KeepTogether([section_header(title), Spacer(1, 5)] + inner[:2]))
        if len(inner) > 2:
            story.extend(inner[2:])
        story.append(Spacer(1, 8))

    story: List[Any] = []

    # ── Document title ────────────────────────────────────────
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
        ("Adresse",      mandat.get("address")             or ""),
        ("Contact",      mandat.get("contact_name")        or ""),
        ("Téléphone",    mandat.get("contact_phone")       or ""),
        ("Date / heure", mandat.get("scheduled_datetime")  or ""),
        ("Technicien",   mandat.get("assigned_technician") or ""),
    ]
    mandat_rows = [(k, v) for k, v in mandat_rows if clean_text(str(v))]

    if mandat_rows:
        tbl = Table(
            [[Paragraph(f"<b>{k}</b>", lbl_style), Paragraph(str(v), body)]
             for k, v in mandat_rows],
            colWidths=[38 * mm, CW - 38 * mm], hAlign="LEFT",
        )
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

    # ── Objectif box (full Markdown support) ──────────────────
    goal = clean_text(mandat.get("intervention_goal") or "")
    if goal:
        obj_lbl_style = ParagraphStyle(
            "cs_obj_lbl", fontName="Helvetica-Bold", fontSize=8.5,
            leading=12, textColor=RED, spaceAfter=4,
        )
        # Use slightly larger body for the objective box
        obj_md = {**md_styles, "body": ParagraphStyle(
            "cs_obj_body", fontName="Helvetica", fontSize=10,
            leading=15, textColor=NAVY,
        )}
        goal_items = md_to_flowables(goal, obj_md)
        # Strip leading/trailing spacers before boxing
        while goal_items and isinstance(goal_items[0], Spacer):
            goal_items.pop(0)
        while goal_items and isinstance(goal_items[-1], Spacer):
            goal_items.pop()

        all_rows = [[Paragraph("OBJECTIF", obj_lbl_style)]] + [[f] for f in goal_items]
        obj_tbl = Table(all_rows, colWidths=[CW])
        obj_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1),       HexColor("#FDF3F2")),
            ("LINEBEFORE",    (0, 0), (0,  -1),  3,   RED),
            ("LEFTPADDING",   (0, 0), (-1, -1),  12),
            ("RIGHTPADDING",  (0, 0), (-1, -1),  12),
            ("TOPPADDING",    (0, 0), (-1, -1),  4),
            ("BOTTOMPADDING", (0, 0), (-1, -1),  4),
            ("TOPPADDING",    (0, 0), (-1, 0),   10),   # first row: extra top
            ("BOTTOMPADDING", (0, -1), (-1, -1), 10),   # last row: extra bottom
        ]))
        story.append(obj_tbl)
        story.append(Spacer(1, 12))

    # ── Content sections ──────────────────────────────────────
    add_section("Problème rapporté",  probleme.get("reported_issue", ""))
    add_section("Contexte technique", technique.get("history_context", ""))

    systems     = technique.get("systems_present") or []
    attempts    = technique.get("attempts_summary") or ""
    constraints = technique.get("site_constraints") or ""

    if systems or clean_text(attempts) or clean_text(constraints):
        env: List[Any] = [section_header("Environnement technique"), Spacer(1, 5)]
        if systems:
            env.append(Paragraph(
                f"<b>Systèmes :</b> {', '.join(systems)}", body))
        if clean_text(attempts):
            env.append(Paragraph("<b>Tentatives et résultats :</b>", body_bold))
            env.extend(md_to_flowables(attempts, md_styles))
        if clean_text(constraints):
            env.append(Paragraph(f"<b>Contraintes :</b> {_fmt(constraints)}", body))
        env.append(Spacer(1, 8))
        story.append(KeepTogether(env[:4]))
        if len(env) > 4:
            story.extend(env[4:])

    add_section("Références utiles",          technique.get("references_utiles", ""))
    add_section("Risques identifiés",          reflexion.get("risks", ""))
    add_section("Vérifications prioritaires",  reflexion.get("priority_checks", ""))
    add_section("Plan d'action",               reflexion.get("action_plan", ""))
    add_section("Hypothèses",                 reflexion.get("hypotheses", ""))
    add_section("Outils / Stock à ramasser",  reflexion.get("tools_access_needed", ""))

    doc.build(story, onFirstPage=draw_chrome, onLaterPages=draw_chrome)
    return buffer.getvalue()


def encode_pdf_base64(payload: Dict[str, Any]) -> Optional[str]:
    try:
        return base64.b64encode(generate_pdf(payload)).decode("utf-8")
    except Exception:
        return None
