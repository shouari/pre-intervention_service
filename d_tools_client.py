"""
d_tools_client.py — Fetch et parsing des Service Calls D-Tools Cloud.
"""
from __future__ import annotations

from datetime import datetime

import requests
from bs4 import BeautifulSoup

from config import TECHNICIAN_LIST

# ── Table de résolution resourceId → nom complet ─────────────────────────────
RESOURCE_ID_TO_NAME: dict[int, str] = {
    6985:  "Alexandre Langlois",
    7040:  "Christian Dion",
    7246:  "Charles Renaud",
    7359:  "Nicolas Levesque",
    8194:  "Janos Devai",
    8671:  "Steven Isidoro",
    8673:  "Daniel Dagenais",
    8687:  "Jean-Michel Gaudet",
    9345:  "Stephanie Simard",
    9349:  "Benjamin Jalbert-Lapare",
    9577:  "Blaise Cyr",
    9578:  "Simon Levesque",
    9580:  "Claude Tremblay",
    9742:  "Frederic Chabot",
    9743:  "Jérémy Arbour",
    9966:  "Eric Pilon",
    9971:  "Adlane Lamari",
    9973:  "Djilali Nait Abdesselam",
    10019: "Steve Rouleau",
    10407: "Pascal Ladouceur",
    10593: "Ghislain Lacasse",
    11840: "Salim Houari",
    12873: "Xavier Pigeon",
    12936: "Groupe SuperTECH",
    13969: "Michael Samaan",
    15950: "Matthieu Chizelle",
    15978: "Raiek Salim",
    18360: "Philippe Renaud",
    19578: "Gabriel Dery",
    21455: "Lounis Nait Abdesselam",
    21995: "Grégory Collas",
    25574: "Pascal Beauregard",
    6859:  "Francois Gravel",
    6966:  "Louis-Charles Halley",
}

_DTOOLS_API_URL = (
    "https://api.d-tools.cloud/Service/api/v1/ServiceCalls/GetServiceCalls"
)


# ── Helpers internes ─────────────────────────────────────────────────────────

def _build_headers(dt_token: str, auth_token: str, subscription_key: str) -> dict:
    return {
        "Accept":                    "application/json, text/plain, */*",
        "Authorization":             f"Bearer {auth_token}",
        "Content-Type":              "application/json; charset=UTF-8",
        "DTToken":                   dt_token,
        "Ocp-Apim-Subscription-Key": subscription_key,
        "Origin":                    "https://d-tools.cloud",
        "Referer":                   "https://d-tools.cloud/",
        "User-Agent":                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "X-DTools-Token":            "",
    }


def _post_dtools(
    headers: dict,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[dict], int, str]:
    """
    Effectue un POST sur l'endpoint GetServiceCalls.
    Retourne (items, total_count, error_message).
    """
    body = {
        "clientIds":          [],
        "serviceCallIds":     None,
        "serviceContractIds": [],
        "projectIds":         [],
        "priorityIds":        [],
        "stateIds":           [],
        "statusIds":          [],
        "resourceIds":        [],
        "fromCreatedOn":      "2020-01-01",
        "toCreatedOn":        "2030-12-31",
        "archived":           False,
        "includeTotalCount":  True,
        "search":             "",
        "fields":             None,
        "sort":               "createdOn",
        "page":               page,
        "pageSize":           page_size,
    }
    try:
        response = requests.post(_DTOOLS_API_URL, headers=headers, json=body, timeout=20)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.ConnectionError:
        return [], 0, "Impossible de joindre l'API D-Tools (ConnectionError)."
    except requests.exceptions.Timeout:
        return [], 0, "La requête vers D-Tools a expiré (Timeout 20 s)."
    except requests.exceptions.HTTPError as exc:
        return [], 0, f"Erreur HTTP {exc.response.status_code} : {exc.response.text[:300]}"
    except Exception as exc:
        return [], 0, str(exc)

    if isinstance(data, list):
        return data, len(data), ""

    if "serviceCalls" in data:
        items = data.get("serviceCalls") or []
        total = data.get("totalServiceCalls") or len(items)
    else:
        items = data.get("items") or data.get("value") or []
        total = data.get("totalCount") or data.get("total") or len(items)

    return items, total, ""


def _fetch_all_sc(
    dt_token: str,
    auth_token: str,
    subscription_key: str,
) -> tuple[list[dict], str]:
    """
    Charge tous les SC via pagination automatique (pageSize=100, max 50 pages).
    Retourne (all_items, "") ou ([], error_message).
    """
    headers = _build_headers(dt_token, auth_token, subscription_key)
    page = 1
    all_items: list[dict] = []
    while True:
        items, total, err = _post_dtools(headers, page=page, page_size=100)
        if err:
            return [], err
        all_items.extend(items)
        if len(all_items) >= total or len(items) < 100:
            break
        page += 1
        if page > 50:
            break
    return all_items, ""


# ── Fonction publique 1 : fetch_service_call ─────────────────────────────────

def fetch_service_call(
    sc_number: str,
    dt_token: str,
    auth_token: str,
    subscription_key: str,
) -> tuple[dict | None, str]:
    """
    Charge tous les SC via _fetch_all_sc, retourne celui dont
    number == sc_number (insensible à la casse).
    """
    all_items, err = _fetch_all_sc(dt_token, auth_token, subscription_key)
    if err:
        return None, err
    sc_number_clean = sc_number.strip().upper()
    for sc in all_items:
        if (sc.get("number") or "").strip().upper() == sc_number_clean:
            return sc, ""
    return None, f"Aucun SC trouvé avec le numéro '{sc_number}' ({len(all_items)} SC chargés)."


# ── Fonction publique 2 : fetch_service_calls_for_date ───────────────────────

def fetch_service_calls_for_date(
    target_date: str,
    dt_token: str,
    auth_token: str,
    subscription_key: str,
) -> tuple[list[dict], str]:
    """
    Charge tous les SC via _fetch_all_sc, retourne ceux dont
    scheduledDateTime est non-null et commence par target_date ("YYYY-MM-DD").
    Retourne (filtered_list, "") ou ([], error_message).
    """
    all_items, err = _fetch_all_sc(dt_token, auth_token, subscription_key)
    if err:
        return [], err
    filtered = [
        sc for sc in all_items
        if sc.get("scheduledDateTime")
        and str(sc["scheduledDateTime"]).startswith(target_date)
    ]
    return filtered, ""


# ── Fonction 3 : parse_sc_list_to_dispatch ───────────────────────────────────

def parse_sc_list_to_dispatch(sc_list: list[dict]) -> list[dict]:
    """
    Convertit une liste de SC D-Tools en liste de dicts prêts pour
    save_pre_intervention (via build_payload).
    """
    result = []
    for sc in sc_list:
        fields = parse_sc_to_payload_fields(sc)
        result.append({
            "client_name":         fields["client_name"] or "",
            "service_call":        fields["service_call"] or "",
            "address":             fields["address"] or "",
            "contact_phone":       fields.get("contact_phone"),
            "scheduled_datetime":  fields["scheduled_datetime"],
            "reported_issue":      fields["reported_issue"] or "",
            "history_context":     fields["history_context"] or "",
            "attempts_summary":    fields["attempts_summary"] or "",
            "assigned_technician": fields["assigned_technician"],
            "dt_id":               sc.get("id"),
        })
    return result


# ── Helpers HTML ─────────────────────────────────────────────────────────────

def _parse_html_paragraphs(html: str | None) -> list[str]:
    """Retourne la liste des textes <p> non-vides d'un fragment HTML."""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    return [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]


def _extract_text_from_html(html: str | None) -> str:
    """Retourne le texte brut de tous les <p> non-vides, joints par \\n."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return "\n".join(p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True))


# ── Marqueurs du formulaire structuré ────────────────────────────────────────

STRUCTURE_MARKERS = [
    "Téléphone :", "Systèmes :", "Marques :", "Depuis :",
    "Comportement :", "Impact :", "Accès :", "Priorité :",
    "Problème :", "Résumé :",
]


# ── Fonction 2 : parse_sc_to_payload_fields ──────────────────────────────────

def parse_sc_to_payload_fields(sc: dict) -> dict:
    """
    Mappe un SC D-Tools vers les champs du payload pré-intervention.

    Retourne un dict — toutes les clés présentes, valeur None si champ absent/vide.

    Mapping :
      client_name         ← sc["client"]
      service_call        ← sc["number"]
      address             ← "{city}, {zipCode}" si les deux présents et non-vides
      scheduled_datetime  ← sc["scheduledDateTime"] parsé en datetime (ou None)
      reported_issue      ← premier <p> non-vide de sc["issueReported"]
      history_context     ← paragraphes suivants joints par "\\n\\n" (ou None)
      attempts_summary    ← tous les <p> non-vides de sc["nextStep"] joints (ou None)
      assigned_technician ← ids dans RESOURCE_ID_TO_NAME filtrés sur TECHNICIAN_LIST
    """
    # ── client_name ───────────────────────────────────────────
    client_name = sc.get("client")
    client_name = client_name.strip() if client_name else None

    # ── service_call ──────────────────────────────────────────
    service_call = sc.get("number")
    service_call = service_call.strip() if service_call else None

    # ── address ───────────────────────────────────────────────
    city     = (sc.get("city")    or "").strip()
    zip_code = (sc.get("zipCode") or "").strip()
    address  = f"{city}, {zip_code}" if city and zip_code else None

    # ── scheduled_datetime ────────────────────────────────────
    raw_dt = sc.get("scheduledDateTime")
    scheduled_datetime: datetime | None = None
    if raw_dt:
        try:
            scheduled_datetime = datetime.fromisoformat(str(raw_dt))
        except (ValueError, TypeError):
            scheduled_datetime = None

    # ── reported_issue / history_context / contact_phone ─────
    raw_text      = _extract_text_from_html(sc.get("issueReported"))
    is_structured = sum(1 for m in STRUCTURE_MARKERS if m in raw_text) >= 2

    if is_structured:
        lines = [ln.strip() for ln in raw_text.split("\n") if ln.strip()]

        def _get_marker(marker: str) -> str:
            for i, line in enumerate(lines):
                if line.startswith(marker):
                    value = line[len(marker):].strip()
                    if value:
                        return value
                    for j in range(i + 1, len(lines)):
                        if lines[j]:
                            return lines[j]
            return ""

        def _get_summary() -> str:
            for i, line in enumerate(lines):
                if line.startswith("Résumé :"):
                    value = line[len("Résumé :"):].strip()
                    rest  = lines[i + 1:] if i + 1 < len(lines) else []
                    parts = ([value] if value else []) + rest
                    return "\n".join(parts)
            return ""

        phone_raw    = _get_marker("Téléphone :")
        systems_raw  = _get_marker("Systèmes :")
        brands_raw   = _get_marker("Marques :")
        since_raw    = _get_marker("Depuis :")
        behavior_raw = _get_marker("Comportement :")
        impact_raw   = _get_marker("Impact :")
        access_raw   = _get_marker("Accès :")
        priority_raw = _get_marker("Priorité :")
        problem_raw  = _get_marker("Problème :")
        summary_raw  = _get_summary()

        reported_issue = problem_raw or summary_raw or raw_text[:200]

        meta_lines: list[str] = []
        if systems_raw:   meta_lines.append(f"Systèmes : {systems_raw}")
        if brands_raw:    meta_lines.append(f"Marques : {brands_raw}")
        if since_raw:     meta_lines.append(f"Depuis : {since_raw}")
        if behavior_raw:  meta_lines.append(f"Comportement : {behavior_raw}")
        if impact_raw:    meta_lines.append(f"Impact : {impact_raw}")
        if access_raw:    meta_lines.append(f"Accès : {access_raw}")
        if priority_raw:  meta_lines.append(f"Priorité : {priority_raw}")
        history_context = "\n".join(meta_lines) if meta_lines else None
        contact_phone   = phone_raw or None
    else:
        paragraphs      = _parse_html_paragraphs(sc.get("issueReported"))
        reported_issue  = paragraphs[0] if paragraphs else None
        remaining       = paragraphs[1:]
        history_context = "\n\n".join(remaining) if remaining else None
        contact_phone   = None

    # ── attempts_summary ──────────────────────────────────────
    next_step_paras  = _parse_html_paragraphs(sc.get("nextStep"))
    attempts_summary = "\n\n".join(next_step_paras) if next_step_paras else None

    # ── assigned_technician ───────────────────────────────────
    resource_ids = sc.get("resourceIds") or []
    assigned_technician: list[str] = []
    for rid in resource_ids:
        name = RESOURCE_ID_TO_NAME.get(int(rid))
        if name and name in TECHNICIAN_LIST:
            assigned_technician.append(name)

    return {
        "client_name":         client_name,
        "service_call":        service_call,
        "address":             address,
        "contact_phone":       contact_phone,
        "scheduled_datetime":  scheduled_datetime,
        "reported_issue":      reported_issue,
        "history_context":     history_context,
        "attempts_summary":    attempts_summary,
        "assigned_technician": assigned_technician,
    }
