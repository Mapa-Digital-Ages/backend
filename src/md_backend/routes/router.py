"""Router file."""

# from md_backend.routes.another_router import another_router
# from md_backend.routes.another_router1 import another_router1
# from md_backend.routes.another_router2 import another_router2
from fastapi import APIRouter

from md_backend.routes.admin_router import admin_router
from md_backend.routes.login_router import login_router
from md_backend.routes.register_router import register_router
from md_backend.routes.setup_router import setup_router
from md_backend.routes.validate_router import validate_router
from md_backend.routes.student_router import student_router

router = APIRouter()

router.include_router(validate_router)
router.include_router(login_router)
router.include_router(register_router)
router.include_router(setup_router)
router.include_router(admin_router)
router.include_router(student_router)
# router.include_router(another_router)
# router.include_router(another_router1)
# router.include_router(another_router2)
