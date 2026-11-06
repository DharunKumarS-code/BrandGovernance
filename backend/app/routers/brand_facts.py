from app.models import BrandFactCreate, BrandFactUpdate
from app.repositories import brand_facts
from app.routers._crud import make_crud_router

router = make_crud_router(
    prefix="/api/brand-facts",
    tag="brand-facts",
    repo=brand_facts,
    create_model=BrandFactCreate,
    update_model=BrandFactUpdate,
)
