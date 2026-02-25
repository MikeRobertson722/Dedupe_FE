"""Direct API helpers for test setup, teardown, and verification."""
import requests

BASE_URL = "http://127.0.0.1:5000"


def api_get_stats() -> dict:
    r = requests.get(f"{BASE_URL}/api/stats")
    r.raise_for_status()
    return r.json()


def api_get_record(row_id: int) -> dict:
    r = requests.get(f"{BASE_URL}/api/record/{row_id}")
    r.raise_for_status()
    return r.json()


def api_update_field(row_id: int, field: str, value) -> dict:
    r = requests.post(f"{BASE_URL}/api/update", json={
        "row_id": row_id, "field": field, "value": value
    })
    r.raise_for_status()
    return r.json()


def api_get_recommendations() -> list:
    r = requests.get(f"{BASE_URL}/api/recommendations")
    r.raise_for_status()
    return r.json()


def api_reload_data() -> dict:
    r = requests.post(f"{BASE_URL}/api/reload")
    r.raise_for_status()
    return r.json()


def api_get_datasources() -> dict:
    r = requests.get(f"{BASE_URL}/api/datasources")
    r.raise_for_status()
    return r.json()


def api_search_replace(search, replace="", column="all",
                       case_sensitive=False, mode="find",
                       row_ids=None):
    payload = {"search": search, "replace": replace, "column": column,
               "case_sensitive": case_sensitive, "mode": mode}
    if row_ids is not None:
        payload["row_ids"] = row_ids
    r = requests.post(f"{BASE_URL}/api/search_replace", json=payload)
    r.raise_for_status()
    return r.json()
