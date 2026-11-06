from app.models import TerminologyCreate, TerminologyUpdate
from app.repositories import terminology
from app.routers._crud import make_crud_router

router = make_crud_router(
    prefix="/api/terminology",
    tag="terminology",
    repo=terminology,
    create_model=TerminologyCreate,
    update_model=TerminologyUpdate,
)
