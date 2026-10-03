from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import features
from app.db import get_db

router = APIRouter(prefix="/api/features", tags=["features"])


@router.get("")
def get_features(db: Session = Depends(get_db)) -> dict:
    return features.collect(db)
