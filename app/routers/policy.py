from fastapi import APIRouter, Request

from app.errors import require
from app.schemas import PolicyFacts

router = APIRouter(prefix="/api/policy", tags=["Policy"])


@router.get("/order-support", response_model=PolicyFacts)
def policy(request: Request):
    return require(request, "policies", "order-support", "POLICY_NOT_FOUND")
