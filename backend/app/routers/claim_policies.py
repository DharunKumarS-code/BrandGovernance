from app.models import ClaimPolicyCreate, ClaimPolicyUpdate
from app.repositories import claim_policies
from app.routers._crud import make_crud_router

router = make_crud_router(
    prefix="/api/claim-policies",
    tag="claim-policies",
    repo=claim_policies,
    create_model=ClaimPolicyCreate,
    update_model=ClaimPolicyUpdate,
)
