from datetime import timedelta
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import verify_password, create_access_token, get_current_user, get_password_hash
from ..config import get_settings

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=schemas.Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/register", response_model=schemas.User)
async def register(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.username == user_in.username).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )

    db_user = db.query(models.User).filter(models.User.email == user_in.email).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    user = models.User(
        username=user_in.username,
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password)
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


@router.get("/me", response_model=schemas.User)
async def read_current_user(current_user: models.User = Depends(get_current_user)):
    return current_user


@router.get("/users", response_model=List[schemas.User])
async def list_users(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """列出可被添加为项目协作者的活跃用户。"""
    users = db.query(models.User).filter(models.User.is_active == True).all()
    return users


@router.put("/me", response_model=schemas.User)
async def update_current_user(
    user_in: schemas.UserUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if user_in.email:
        existing = db.query(models.User).filter(models.User.email == user_in.email).first()
        if existing and existing.id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        current_user.email = user_in.email

    if user_in.full_name:
        current_user.full_name = user_in.full_name

    if user_in.password:
        current_user.hashed_password = get_password_hash(user_in.password)

    db.commit()
    db.refresh(current_user)

    return current_user
