import os
from typing import Optional
import requests

IIIF_TEMPLATE = "https://www.vads.ac.uk/iiif/2/{alias}:{item_id}/full/full/0/default.jpg"
THUMBNAIL_TEMPLATE = "https://vads.ac.uk/digital/api/singleitem/collection/{alias}/id/{item_id}/thumbnail"


def download_image(
    session: requests.Session,
    alias: str,
    item_id: int,
    images_dir: str,
    image_url: Optional[str] = None,
) -> Optional[str]:
    dest_dir = os.path.join(images_dir, alias)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, f"{item_id}.jpg")

    if os.path.exists(dest_path):
        return dest_path

    urls_to_try = []
    if image_url:
        urls_to_try.append(image_url)
    urls_to_try.append(IIIF_TEMPLATE.format(alias=alias, item_id=item_id))
    urls_to_try.append(THUMBNAIL_TEMPLATE.format(alias=alias, item_id=item_id))

    for url in urls_to_try:
        try:
            resp = session.get(url, timeout=60, verify=False, stream=True)
            if resp.status_code == 200 and "image" in resp.headers.get("Content-Type", ""):
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                return dest_path
        except requests.RequestException:
            continue

    return None
