from io import BytesIO

from PIL import Image

from scripts.seed_dev import ids
from tests.integration.conftest import auth


def test_photo_is_validated_private_and_removable(api):
    image = BytesIO()
    Image.new("RGB", (4, 3)).save(image, "PNG")
    url = "/api/me/profile-photos"
    assert api.post(url, files={"file": ("bad.png", b"invalid", "image/png")}).status_code == 422
    response = api.post(url, files={"file": ("test.png", image.getvalue(), "image/png")})
    assert response.status_code == 201
    photo_id = response.json()["photo_id"]
    private_url = f"{url}/{photo_id}"
    assert api.get(private_url).headers["content-type"] == "image/jpeg"
    assert api.get(private_url, headers=auth("other")).status_code == 404
    data = {"photo_id": photo_id}
    headers = {"If-Match": '"1"'}
    assert (
        api.patch(
            f"/api/seniors/{ids('other')[1]}", json=data, headers={**headers, **auth("other")}
        ).status_code
        == 422
    )
    path = f"/api/seniors/{ids('owner')[1]}"
    assert api.patch(path, json=data, headers=headers).json()["photo_id"] == photo_id
    cleared = api.patch(path, json={"photo_id": None}, headers={"If-Match": '"2"'}).json()
    assert cleared["photo_id"] is None and cleared["avatar_key"] == "default"
