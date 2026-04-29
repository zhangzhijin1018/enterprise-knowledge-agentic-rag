"""DataMaskingService 测试。"""

from __future__ import annotations

from core.analytics.data_masking import DataMaskingService


def test_data_masking_service_masks_sensitive_fields_without_permission() -> None:
    """缺少敏感字段权限时，应对命中的敏感字段做最小脱敏。"""

    service = DataMaskingService()

    result = service.apply(
        rows=[
            {"station": "哈密电站", "total_value": 1200.0},
        ],
        columns=["station", "total_value"],
        visible_fields=["station", "total_value"],
        sensitive_fields=["station"],
        masked_fields=["station"],
        user_permissions=["analytics:query"],
    )

    assert result.masked_fields == ["station"]
    assert result.rows[0]["station"] != "哈密电站"
    assert "***" in result.rows[0]["station"]


def test_data_masking_service_keeps_sensitive_fields_when_permission_exists() -> None:
    """拥有敏感字段查看权限时，不应再额外脱敏。"""

    service = DataMaskingService()

    result = service.apply(
        rows=[
            {"station": "哈密电站", "total_value": 1200.0},
        ],
        columns=["station", "total_value"],
        visible_fields=["station", "total_value"],
        sensitive_fields=["station"],
        masked_fields=["station"],
        user_permissions=["analytics:query", "analytics:field:station:view_sensitive"],
    )

    assert result.masked_fields == []
    assert result.rows[0]["station"] == "哈密电站"
