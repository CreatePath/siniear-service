from io import BytesIO
from uuid import UUID

from fastapi import APIRouter, Response, UploadFile
from PIL import Image, ImageOps
from pydantic import BaseModel
from sqlalchemy import select

from app.api.dependencies import Database
from app.core.errors import API_ERRORS, DomainError
from app.db.models.identity import MediaAsset, User
from app.modules.auth.dependencies import Member
from app.modules.auth.service import unauthorized

router = APIRouter(tags=["seniors"], responses=API_ERRORS)
MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 12_000_000


class PhotoCreated(BaseModel):
    photo_id: UUID


def normalize_photo(file):
    raw = file.read(MAX_BYTES + 1)
    try:
        if len(raw) > MAX_BYTES:
            raise ValueError
        with Image.open(BytesIO(raw), formats=["JPEG", "PNG"]) as source:
            if source.width * source.height > MAX_PIXELS or getattr(source, "is_animated", False):
                raise ValueError
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((2048, 2048))
            image.info.clear()
            buf = BytesIO()
            image.save(buf, format="JPEG", quality=85)
            return buf.getvalue()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise DomainError(422, "VALIDATION_ERROR", "사진 형식이나 크기를 확인해 주세요.") from None


@router.post("/me/profile-photos", status_code=201)
def upload(file: UploadFile, account: Member, session: Database) -> PhotoCreated:
    content = normalize_photo(file.file)
    with session.begin():
        if not session.scalar(
            select(User.id)
            .where(User.id == account.user_id, User.withdrawn_at.is_(None))
            .with_for_update(read=True)
        ):
            raise unauthorized()
        asset = MediaAsset(owner_user_id=account.user_id, purpose="profile_photo", content=content)
        session.add(asset)
        session.flush()
        return PhotoCreated(photo_id=asset.id)


@router.get("/me/profile-photos/{photo_id}", response_class=Response)
def read_photo(photo_id: UUID, account: Member, session: Database):
    with session.begin():
        content = session.scalar(
            select(MediaAsset.content).where(
                MediaAsset.id == photo_id,
                MediaAsset.owner_user_id == account.user_id,
                MediaAsset.purpose == "profile_photo",
            )
        )
        if content is None:
            raise DomainError(404, "PHOTO_NOT_FOUND", "사진을 찾을 수 없습니다.")
        return Response(
            content, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"}
        )
