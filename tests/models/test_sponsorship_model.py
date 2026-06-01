import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from md_backend.models.db_models import (
    CompanyProfile,
    PartnershipStatusEnum,
    SchoolCompanyPartnership,
    SchoolProfile,
    SponsorshipRequest,
    SponsorshipRequestStatusEnum,
    UserProfile,
)
from md_backend.utils.database import AsyncSessionLocal, init_db


class TestSponsorshipModel:
    @pytest.mark.anyio
    async def test_create_sponsorship_request_success(self):
        await init_db()
        async with AsyncSessionLocal() as session:
            # Create school
            user = UserProfile(
                email=f"school_{uuid.uuid4()}@test.com",
                first_name="School",
                password="hashed",
            )
            session.add(user)
            await session.flush()

            school = SchoolProfile(user_id=user.id, is_private=False)
            session.add(school)
            await session.flush()

            # Create Request
            req = SponsorshipRequest(
                school_id=school.user_id,
                requested_spots=100,
                remaining_spots=100,
            )
            session.add(req)
            await session.commit()

            assert req.id is not None
            assert req.status == SponsorshipRequestStatusEnum.OPEN

    @pytest.mark.anyio
    async def test_create_partnership_success(self):
        await init_db()
        async with AsyncSessionLocal() as session:
            # Create school
            school_user = UserProfile(
                email=f"school_{uuid.uuid4()}@test.com",
                first_name="School",
                password="hashed",
            )
            session.add(school_user)

            # Create company
            company_user = UserProfile(
                email=f"company_{uuid.uuid4()}@test.com",
                first_name="Company",
                password="hashed",
            )
            session.add(company_user)
            await session.flush()

            school = SchoolProfile(user_id=school_user.id, is_private=False)
            session.add(school)
            company = CompanyProfile(user_id=company_user.id, spots=100)
            session.add(company)
            await session.flush()

            # Create Request
            req = SponsorshipRequest(
                school_id=school.user_id,
                requested_spots=100,
                remaining_spots=100,
            )
            session.add(req)
            await session.flush()

            # Create Partnership
            partnership = SchoolCompanyPartnership(
                school_id=school.user_id,
                company_id=company.user_id,
                request_id=req.id,
                granted_spots=50,
            )
            session.add(partnership)
            await session.commit()

            assert partnership.id is not None
            assert partnership.status == PartnershipStatusEnum.PENDING

    def test_profile_columns_removed(self):
        assert not hasattr(SchoolProfile, "requested_spots")
        assert not hasattr(CompanyProfile, "available_spots")
