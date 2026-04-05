"""Router file."""

# from md_backend.routes.another_router import another_router
# from md_backend.routes.another_router1 import another_router1
# from md_backend.routes.another_router2 import another_router2
from fastapi import APIRouter

from md_backend.routes.validate_router import validate_router
from md_backend.routes.login_router import login_router

router = APIRouter()

router.include_router(validate_router)
router.includer_router(login_router)
# router.include_router(another_router)
# router.include_router(another_router1)
# router.include_router(another_router2)
