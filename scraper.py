import time
import requests

BASE = "https://vads.ac.uk/digital"


def search_collection(
    session: requests.Session,
    alias: str,
    page: int = 1,
    maxrecs: int = 10,
    delay: float = 0.3,
) -> tuple[list[dict], int]:
    url = (
        f"{BASE}/api/search/collection/{alias}"
        f"/searchterm/0/field/nosort/mode/all/conn/and/order/nosort/ad/asc"
        f"/page/{page}/maxrecs/{maxrecs}"
    )
    resp = session.get(url, timeout=30, verify=False)
    resp.raise_for_status()
    data = resp.json()
    time.sleep(delay)
    items = data.get("items") or []
    total = int(data.get("totalResults", 0))
    return items, total


def fetch_item(
    session: requests.Session,
    alias: str,
    item_id: int,
    delay: float = 0.3,
) -> dict:
    url = f"{BASE}/api/singleitem/collection/{alias}/id/{item_id}"
    resp = session.get(url, timeout=30, verify=False)
    resp.raise_for_status()
    data = resp.json()
    time.sleep(delay)
    return data
