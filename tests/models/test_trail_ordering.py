"""Explicit ordering columns on sub-paths and their items."""

from md_backend.models.db_models import SubPath, SubPathItem


def test_sub_path_has_order_column():
    col = SubPath.__table__.c["order"]
    assert col.nullable is False


def test_sub_path_item_has_order_column():
    col = SubPathItem.__table__.c["order"]
    assert col.nullable is False
