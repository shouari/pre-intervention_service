"""
app.py — Point d'entrée de l'application Streamlit.
Architecture modulaire : config | database | utils | state | ai_engine | pdf_engine | dispatch
"""
from __future__ import annotations

import json
from datetime import datetime

# ── Chargement .env ────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import streamlit as st

# ── Modules internes ───────────────────────────────────────
from config import SYSTEM_OPTIONS, TECHNICIAN_LIST, TECH_EMAIL_MAP
from database import (
    DB_PATH, init_db,
    list_pre_interventions, get_pre_intervention,
    get_real_intervention, save_pre_intervention,
    get_dispatch_for_day,
)
from utils import clean_text, split_lines, safe_filename, format_french_date, completion_score
from state import (
    init_state, apply_injection_buffers, build_payload,
    load_historical_data_callback, reset_main_form_state_callback,
    save_real_intervention_callback, save_pre_intervention_callback,
)
from ai_engine import run_ai_analysis, OPENAI_AVAILABLE
from pdf_engine import generate_pdf, report_markdown, REPORTLAB_AVAILABLE
from dispatch import build_dispatch_email, send_dispatch_emails


# =========================================================
# CONFIGURATION
# =========================================================
st.set_page_config(
    page_title="Pré-interventions — Groupe CS",
    page_icon="🛠️",
    layout="wide",
)

# CSS global épuré
st.markdown("""
<style>
.report-card {
    background: white; color: #111;
    border-radius: 12px; padding: 20px 24px;
    border: 1px solid rgba(0,0,0,.08);
    box-shadow: 0 2px 12px rgba(0,0,0,.05);
    font-size: 0.9em;
}
.badge-green  { color: #16a34a; font-weight: 600; }
.badge-orange { color: #ea580c; font-weight: 600; }
.badge-red    { color: #dc2626; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


# =========================================================
# INIT
# =========================================================
init_db()
init_state()
apply_injection_buffers()


# =========================================================
# TOP BAR
# =========================================================
st.title("🛠️ Préparation d'appel de service")
st.caption("Préparer · Briefer · Générer · Capitaliser")

if st.session_state.get("_success_msg"):
    st.success(st.session_state._success_msg)
    st.session_state._success_msg = ""

score  = completion_score()
status = "Brouillon"
if score >= 85:
    status = "Prêt pour PDF"
elif score >= 55:
    status = "En cours"
st.session_state.status = status

c_score, c_status, c_bar, c_new = st.columns([1, 1.4, 3.5, 1.2])
c_score.metric("Complétion", f"{score}%")
c_status.metric("Statut", status)
c_bar.progress(score / 100)
c_new.button("🆕 Nouveau dossier", use_container_width=True, on_click=reset_main_form_state_callback)

if st.session_state.current_pre_intervention_id:
    st.caption(f"📂 Dossier courant : **#{st.session_state.current_pre_intervention_id}**")

st.divider()

# =========================================================
# TABS
# =========================================================
tab_prep, tab_tech, tab_hist, tab_recon, tab_dispatch = st.tabs([
    "🗂️ Préparateur",
    "📋 Technicien",
    "🗃️ Historique",
    "🔁 Retour terrain",
    "🚗 Dispatch",
])


# ─────────────────────────────────────────────────────────
# ONGLET PRÉPARATEUR
# ─────────────────────────────────────────────────────────
with tab_prep:
    left, right = st.columns([1.1, 0.9], gap="large")

    with left:
        # ── 1) Mandat ──────────────────────────────────────
        with st.expander("1) Mandat", expanded=True):
            a, b = st.columns(2)
            with a:
                st.text_input("Client *", key="client_name", placeholder="Nom du client")
                st.text_input("Contact", key="contact_name", placeholder="Prénom Nom")
                st.multiselect("Techniciens assignés", TECHNICIAN_LIST, key="assigned_technician")
            with b:
                st.text_input("Adresse *", key="address")
                st.text_input("Téléphone", key="contact_phone")
                st.datetime_input("Date / heure prévue", key="scheduled_datetime",
                                  value=st.session_state.scheduled_datetime)
                st.text_input("Appel de service #", key="service_call")
            st.text_area(
                "Objectif de l'intervention *", key="intervention_goal",
                placeholder="Ex. Remplacer le routeur défectueux et remettre le réseau en service",
                height=80,
            )

        # ── 2) Problème ────────────────────────────────────
        with st.expander("2) Problème", expanded=True):
            st.text_area(
                "Problème rapporté *", key="reported_issue",
                placeholder="Description telle que rapportée par le client — sans interprétation.",
                height=120,
            )
            st.text_area(
                "Contexte technique (optionnel)", key="history_context",
                placeholder="Ex: réseau Unifi, ampli Denon, problème apparu après changement routeur",
                height=90,
            )

        # ── 3) Environnement technique ─────────────────────
        with st.expander("3) Environnement technique", expanded=True):
            st.multiselect("Systèmes présents *", SYSTEM_OPTIONS, key="systems_present")
            if "Autre" in st.session_state.systems_present:
                st.text_input("Préciser le système 'Autre'", key="other_system")
            st.text_area(
                "Tentatives et résultats", key="attempts_summary",
                placeholder="Qu'est-ce qui a déjà été essayé et quel résultat ?",
                height=100,
            )
            st.text_input(
                "Contraintes sur place", key="site_constraints",
                placeholder="Accès difficile, horaires, présence client requise…",
            )

        # ── 4) Références (optionnel) ──────────────────────
        with st.expander("4) Références et documents", expanded=False):
            st.text_area(
                "Chemins / références utiles", key="references_utiles",
                placeholder="Un chemin NAS, lien, référence — une par ligne",
                height=90,
            )
            uploaded = st.file_uploader(
                "Documents de travail (facultatif)",
                type=["pdf", "txt", "docx", "json"],
                accept_multiple_files=True,
            )
            st.session_state.work_docs = uploaded or []
            for f in st.session_state.work_docs:
                st.caption(f"📎 {f.name}")

        # ── 5) Réflexion structured ────────────────────────
        with st.expander("5) Réflexion structurée", expanded=True):
            st.text_area(
                "Hypothèses (une par ligne)", key="hypotheses",
                placeholder="Panne d'alimentation du switch\nConfig VLAN incorrecte\nFirmware obsolète…",
                height=90,
            )
            st.text_area(
                "Vérifications prioritaires (une par ligne)", key="priority_checks",
                placeholder="Vérifier les voyants du switch\nPing gateway depuis le rack…",
                height=100,
            )
            st.text_area(
                "Plan d'action (une par ligne)", key="action_plan",
                placeholder="Redémarrer l'équipement en ordre\nComparer la config vs backup…",
                height=100,
            )
            st.text_area(
                "Risques identifiés (une par ligne)", key="risks_text",
                placeholder="IP inconnues\nDocumentation incomplète\nAccès incertain…",
                height=80,
            )
            st.text_area(
                "Outils / Stock à ramasser", key="tools_access_needed",
                placeholder="Laptop + câble console\nAccès UniFi Controller\nCode alarme client…",
                height=80,
            )

        # ── 6) Assistance IA ───────────────────────────────
        with st.expander("6) Assistance IA 🤖", expanded=False):
            st.caption("L'analyse IA est non-confidentielle et ne remplace pas le jugement humain.")
            from utils import extract_text_from_uploaded_files
            doc_text = extract_text_from_uploaded_files(st.session_state.work_docs)

            if st.button("🤖 Analyser avec IA", use_container_width=True, type="primary"):
                with st.spinner("Analyse en cours…"):
                    try:
                        payload_for_ai = build_payload()
                        result = run_ai_analysis(payload_for_ai, doc_text)
                        st.session_state.ai_summary             = result.get("summary", "")
                        st.session_state.ai_hypotheses          = result.get("hypotheses", [])
                        st.session_state.ai_priority_checks     = result.get("priority_checks", [])
                        st.session_state.ai_action_plan         = "\n".join(result.get("action_plan", []))
                        st.session_state.ai_risks               = result.get("risks", [])
                        st.session_state.ai_tools_access_needed = result.get("tools_or_access_needed", [])
                        st.session_state.ai_missing_information = result.get("missing_information", [])
                        st.session_state.ai_raw_json            = json.dumps(result, ensure_ascii=False, indent=2)
                        st.success("✅ Analyse IA générée avec succès.")
                    except Exception as e:
                        st.error(f"Analyse IA impossible : {e}")

            if st.session_state.ai_raw_json:
                st.divider()
                ai1, ai2 = st.columns(2)
                with ai1:
                    if st.session_state.ai_hypotheses:
                        st.markdown("**💡 Hypothèses**")
                        for item in st.session_state.ai_hypotheses:
                            st.markdown(f"- {item}")
                    if st.session_state.ai_risks:
                        st.markdown("**⚠️ Points de vigilance**")
                        for item in st.session_state.ai_risks:
                            st.markdown(f"- {item}")
                with ai2:
                    if st.session_state.ai_action_plan:
                        st.markdown("**🔧 Plan d'action suggéré**")
                        for i, item in enumerate(split_lines(st.session_state.ai_action_plan), 1):
                            st.markdown(f"{i}. {item}")
                    if st.session_state.ai_tools_access_needed:
                        st.markdown("**🧰 Outils requis**")
                        for item in st.session_state.ai_tools_access_needed:
                            st.markdown(f"- {item}")
                    if st.session_state.ai_priority_checks:
                        st.markdown("**📚 Sources / références**")
                        for item in st.session_state.ai_priority_checks:
                            st.markdown(f"- {item}")

                st.divider()
                st.caption("Insérer les suggestions IA dans les champs :")
                if st.button("↳ Tout insérer dans les champs", use_container_width=True):
                    def merge(existing: str, new_items: list) -> str:
                        ex = clean_text(existing)
                        ni = "\n".join(new_items)
                        return (ex + "\n" + ni).strip() if ex else ni

                    st.session_state["_buf_hypotheses"]         = merge(st.session_state.hypotheses, st.session_state.ai_hypotheses)
                    st.session_state["_buf_priority_checks"]    = merge(st.session_state.priority_checks, st.session_state.ai_priority_checks)
                    st.session_state["_buf_action_plan"]        = merge(st.session_state.action_plan, split_lines(st.session_state.ai_action_plan))
                    st.session_state["_buf_risks_text"]         = merge(st.session_state.risks_text, st.session_state.ai_risks)
                    st.session_state["_buf_tools_access_needed"]= merge(st.session_state.tools_access_needed, st.session_state.ai_tools_access_needed)
                    st.rerun()

                with st.expander("Voir le JSON IA brut"):
                    st.code(st.session_state.ai_raw_json, language="json")

    # ── Colonne droite : aperçu + persistance ───────────────
    with right:
        st.subheader("Aperçu de la fiche")
        payload = build_payload()
        st.markdown('<div class="report-card">', unsafe_allow_html=True)
        st.markdown(report_markdown(payload))
        st.markdown('</div>', unsafe_allow_html=True)

        st.divider()
        cs1, cs2 = st.columns(2)
        if cs1.button("💾 Sauvegarder", use_container_width=True, type="primary",
                      key="save_btn_prep"):
            pre_id = save_pre_intervention(payload, st.session_state.current_pre_intervention_id)
            st.session_state.current_pre_intervention_id = pre_id
            st.success(f"✅ Dossier sauvegardé (#{pre_id})")

        if REPORTLAB_AVAILABLE:
            try:
                pdf_bytes = generate_pdf(payload)
                cs2.download_button(
                    "📄 Télécharger PDF", data=pdf_bytes,
                    file_name=f"{datetime.now().strftime('%Y-%m-%d')}_{safe_filename(st.session_state.client_name or 'client')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            except Exception as e:
                cs2.error(f"PDF : {e}")
        else:
            cs2.warning("ReportLab non installé.")


# ─────────────────────────────────────────────────────────
# ONGLET TECHNICIEN
# ─────────────────────────────────────────────────────────
with tab_tech:
    payload    = build_payload()
    score_now  = payload["meta"]["completion_score"]
    sc         = clean_text(st.session_state.service_call)
    client_val = clean_text(st.session_state.client_name) or "client"
    base_name  = f"{datetime.now().strftime('%Y-%m-%d')}_{safe_filename(client_val)}" + (f"_{safe_filename(sc)}" if sc else "")

    # Badge de statut
    if score_now >= 85:
        badge = '<span class="badge-green">✅ Fiche prête pour l\'intervention</span>'
    elif score_now >= 40:
        badge = f'<span class="badge-orange">📝 En cours ({score_now}% complétée)</span>'
    else:
        badge = '<span class="badge-red">⚠️ Fiche incomplète — remplissez les champs obligatoires</span>'
    st.markdown(badge, unsafe_allow_html=True)

    # Boutons de téléchargement en haut
    dl1, dl2, dl3 = st.columns(3)
    with dl1:
        if REPORTLAB_AVAILABLE:
            try:
                pdf_bytes = generate_pdf(payload)
                st.download_button(
                    "📄 Télécharger PDF", data=pdf_bytes,
                    file_name=f"{base_name}.pdf",
                    mime="application/pdf",
                    use_container_width=True, type="primary",
                )
            except Exception as e:
                st.error(f"PDF : {e}")
        else:
            st.warning("ReportLab non installé.")
    with dl2:
        json_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button(
            "📦 Télécharger JSON", data=json_bytes,
            file_name=f"{base_name}.json",
            mime="application/json",
            use_container_width=True,
        )
    with dl3:
        if st.button("💾 Sauvegarder en DB", use_container_width=True):
            pre_id = save_pre_intervention(payload, st.session_state.current_pre_intervention_id)
            st.session_state.current_pre_intervention_id = pre_id
            st.success(f"✅ Dossier sauvegardé (#{pre_id})")

    st.divider()
    st.markdown('<div class="report-card">', unsafe_allow_html=True)
    st.markdown(report_markdown(payload))
    st.markdown('</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────
# ONGLET HISTORIQUE
# ─────────────────────────────────────────────────────────
with tab_hist:
    st.subheader("Historique des pré-interventions")

    top1, top2, top3 = st.columns([3, 1, 1])
    with top1:
        search = st.text_input("🔍 Recherche client / appel / technicien", key="history_search")
    with top2:
        filter_date = st.date_input("Filtrer par date", value=None, label_visibility="collapsed")
    with top3:
        st.caption(f"DB : {DB_PATH.name}")

    rows = list_pre_interventions(search)
    # Filtre date côté Python
    if filter_date:
        date_str_filter = filter_date.strftime("%Y-%m-%d")
        rows = [r for r in rows if (r["scheduled_datetime"] or "").startswith(date_str_filter)]

    if not rows:
        st.info("Aucune pré-intervention enregistrée pour ce filtre.")
    else:
        for row in rows:
            has_retour = bool(get_real_intervention(int(row["id"])))
            with st.container(border=True):
                c1, c2, c3, c4, c5, c6 = st.columns([2.2, 1.2, 1.2, 0.9, 0.7, 0.9])
                c1.markdown(f"**#{row['id']} — {row['client_name'] or '—'}**")
                c1.caption(f"Appel: {row['service_call'] or '—'} | Tech: {row['assigned_technician'] or '—'}")
                c2.write(row["scheduled_datetime"] or "—")
                c3.write(row["status"] or "—")
                c4.write(f"{row['completion_score'] or 0}%")
                c5.write("✅" if has_retour else "—")
                c6.button("Charger", key=f"load_{row['id']}",
                          on_click=load_historical_data_callback, args=(int(row["id"]),))


# ─────────────────────────────────────────────────────────
# ONGLET RETOUR TERRAIN
# ─────────────────────────────────────────────────────────
with tab_recon:
    st.subheader("Retour terrain")
    current_id = st.session_state.current_pre_intervention_id

    if not current_id:
        st.info("📂 Charge une pré-intervention depuis l'onglet **Historique** pour saisir le retour terrain.")
    else:
        pre_row = get_pre_intervention(current_id)
        if pre_row:
            st.caption(f"#{current_id} — {pre_row['client_name'] or '—'} | Appel: {pre_row['service_call'] or '—'}")

        st.divider()
        col_prob, col_work = st.columns(2, gap="large")

        with col_prob:
            st.markdown("### 🔍 Problèmes rencontrés")
            st.text_area(
                "Cause(s) réelle(s) du problème", key="real_root_cause", height=300,
                placeholder="Ex: Câble HDMI défectueux derrière le mur. Ampli en mode protection suite à une surtension.",
            )

        with col_work:
            st.markdown("### 🔧 Travaux effectués")
            st.text_area(
                "Ce qui a été fait sur place", key="real_work_done", height=300,
                placeholder="Ex: Remplacement du câble HDMI. Reset de l'ampli. Test de tous les inputs. Client informé.",
            )

        st.divider()
        st.button(
            "💾 Sauvegarder le retour terrain",
            use_container_width=True, type="primary",
            on_click=save_real_intervention_callback,
        )

        # Aperçu du dernier retour sauvegardé
        existing = get_real_intervention(current_id)
        if existing and (existing.get("real_root_cause") or existing.get("work_done")):
            st.divider()
            st.markdown("### 📋 Dernier retour sauvegardé")
            p1, p2 = st.columns(2)
            with p1:
                st.markdown("**Problèmes rencontrés**")
                st.markdown(existing.get("real_root_cause") or "—")
            with p2:
                st.markdown("**Travaux effectués**")
                st.markdown(existing.get("work_done") or "—")


# ─────────────────────────────────────────────────────────
# ONGLET DISPATCH
# ─────────────────────────────────────────────────────────
with tab_dispatch:
    st.subheader("Dispatch quotidien")

    c_date, c_send_all = st.columns([2, 1], gap="medium")
    with c_date:
        dispatch_date = st.date_input("Sélectionner la date", value=datetime.today().date())

    date_str      = dispatch_date.strftime("%Y-%m-%d")
    dispatch_data = get_dispatch_for_day(date_str)

    with c_send_all:
        st.write("")
        st.write("")
        do_send_all = st.button(
            "📧 Envoyer à TOUS", use_container_width=True, type="primary",
            disabled=not bool(dispatch_data),
        )

    if not dispatch_data:
        st.warning(f"Aucun appel de service planifié pour le {format_french_date(date_str)}.")
    else:
        if do_send_all:
            tech_emails_ui = {
                t: st.session_state.get(f"email_input_{t}", TECH_EMAIL_MAP.get(t, ""))
                for t in dispatch_data
            }
            tech_emails_cc = {
                t: st.session_state.get(f"cc_input_{t}", "service@groupecs.com")
                for t in dispatch_data
            }
            with st.spinner("Envoi des emails via Brevo…"):
                results = send_dispatch_emails(dispatch_data, date_str, tech_emails_ui, tech_emails_cc)
            for res in results:
                if res["status"] == "success":
                    st.success(f"✅ **{res['tech']}** : {res['message']}")
                elif res["status"] == "skipped":
                    st.warning(f"⏭️ **{res['tech']}** ignoré : {res['message']}")
                else:
                    st.error(f"❌ **{res['tech']}** : {res['message']}")
            st.divider()

        for tech_full, calls in dispatch_data.items():
            first_name = tech_full.split()[0] if tech_full else "Inconnu"
            st.markdown(f"### {first_name} ({len(calls)} appel{'s' if len(calls) > 1 else ''})")

            c1, c2 = st.columns(2)
            with c1:
                email_val = st.text_input(
                    "Courriel destinataire",
                    value=TECH_EMAIL_MAP.get(tech_full, ""),
                    key=f"email_input_{tech_full}",
                    placeholder="jean@domaine.com",
                )
            with c2:
                cc_val = st.text_input(
                    "En copie (CC)",
                    value="service@groupecs.com",
                    key=f"cc_input_{tech_full}",
                    placeholder="Séparer par virgules pour plusieurs",
                )

            email_text = build_dispatch_email(tech_full, calls, date_str)
            st.text_area("Contenu email", value=email_text, height=230, key=f"email_{tech_full}")

            c_dl, c_send = st.columns(2)
            c_dl.download_button(
                "📥 Télécharger .txt", data=email_text,
                file_name=f"dispatch_{safe_filename(tech_full)}_{date_str}.txt",
                mime="text/plain",
                key=f"dl_{tech_full}", use_container_width=True,
            )
            if c_send.button("📧 Envoyer à ce technicien", key=f"send_{tech_full}", use_container_width=True):
                with st.spinner(f"Envoi à {first_name}…"):
                    res = send_dispatch_emails({tech_full: calls}, date_str, {tech_full: email_val}, {tech_full: cc_val})
                    r = res[0] if res else {}
                    if r.get("status") == "success":
                        st.success(f"✅ Email envoyé à {first_name}.")
                    elif r.get("status") == "skipped":
                        st.warning(f"⏭️ {first_name} ignoré : {r.get('message')}")
                    else:
                        st.error(f"❌ Erreur pour {first_name} : {r.get('message', '?')}")
            st.divider()
