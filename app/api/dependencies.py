from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import Principal, get_principal

Database = Annotated[Session, Depends(get_session)]
Actor = Annotated[Principal, Depends(get_principal)]
