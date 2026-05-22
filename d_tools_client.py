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


# ── Fonction 1 : fetch_service_call ──────────────────────────────────────────

def fetch_service_call(
    sc_number: str,
    dt_token: str,
    auth_token: str,
    subscription_key: str,
) -> tuple[dict | None, str]:
    """
    Appelle GET https://api.d-tools.cloud/Service/api/v1/ServiceCalls/GetServiceCalls

    Headers :
        DTToken: <dt_token>
        Authorization: Bearer <auth_token>
        Ocp-Apim-Subscription-Key: <subscription_key>

    Timeout : 10 s.
    Filtre la liste pour trouver l'entrée dont number == sc_number (ex: "SC-1058").

    Retourne :
        (sc_dict, "")              si trouvé
        (None, message_erreur)     sinon
    """
    headers = {
        "DTToken": dt_token,
        "Authorization": f"Bearer {auth_token}",
        "Ocp-Apim-Subscription-Key": subscription_key,
    }

    try:
        response = requests.get(_DTOOLS_API_URL, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.ConnectionError:
        return None, "Impossible de joindre l'API D-Tools (ConnectionError)."
    except requests.exceptions.Timeout:
        return None, "La requête vers D-Tools a expiré (Timeout 10 s)."
    except requests.exceptions.HTTPError as exc:
        return None, f"Erreur HTTP {exc.response.status_code} : {exc.response.text[:200]}"
    except Exception as exc:  # noqa: BLE001
        return None, f"Erreur inattendue lors de la requête : {exc}"

    # La réponse peut être une liste directe ou un dict enveloppant
    if isinstance(data, dict):
        items = data.get("value") or data.get("items") or data.get("data") or []
    elif isinstance(data, list):
        items = data
    else:
        return None, "Format de réponse inattendu (ni liste ni dict)."

    try:
        for sc in items:
            if sc.get("number", "").strip() == sc_number.strip():
                return sc, ""
    except (KeyError, IndexError, TypeError) as exc:
        return None, f"Erreur lors du parcours des résultats : {exc}"

    return None, f"Aucun Service Call trouvé avec le numéro « {sc_number} »."


# ── Aide interne : parsing HTML ───────────────────────────────────────────────

def _parse_html_paragraphs(html: str | None) -> list[str]:
    """Retourne la liste des textes <p> non-vides d'un fragment HTML."""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    return [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]


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

    # ── reported_issue / history_context ─────────────────────
    paragraphs      = _parse_html_paragraphs(sc.get("issueReported"))
    reported_issue  = paragraphs[0] if paragraphs else None
    remaining       = paragraphs[1:]
    history_context = "\n\n".join(remaining) if remaining else None

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
        "scheduled_datetime":  scheduled_datetime,
        "reported_issue":      reported_issue,
        "history_context":     history_context,
        "attempts_summary":    attempts_summary,
        "assigned_technician": assigned_technician,
    }
