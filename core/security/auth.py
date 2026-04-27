"""认证与用户上下文占位模块。

当前阶段仍然不接真实 JWT / SSO，
但要把“用户上下文如何进入系统”这条链路正式化。

本模块的目标是：
1. 不再长期依赖固定 mock 用户；
2. 允许本地开发阶段通过 Header 模拟登录身份；
3. 为后续接真实 Bearer Token 解析保留稳定 UserContext 结构；
4. 让 request -> user_context -> service -> repository 这条链路从现在起就是显式的。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Request, status

from core.common import error_codes
from core.common.exceptions import AppException


@dataclass(slots=True)
class UserContext:
    """当前请求用户上下文。

    当前字段先保留最小集合：
    - user_id
    - username
    - display_name
    - roles

    后续可逐步扩展 department_id、access_scope、security_level 等字段。
    """

    # 用户 ID。后续可对应 users.id 或对外稳定 user_uuid。
    user_id: int

    # 登录用户名。
    username: str

    # 展示名。
    display_name: str

    # 当前用户角色集合。
    roles: list[str] = field(default_factory=list)

    # 当前用户所属部门编码。
    department_code: str | None = None

    # 当前用户权限集合。
    permissions: list[str] = field(default_factory=list)


def _parse_csv_header(header_value: str | None) -> list[str]:
    """解析逗号分隔 Header。

    业务原因：
    - 角色、权限这类上下文天然是多值集合；
    - 先约定逗号分隔格式，后续无论来自网关透传、JWT Claim 还是 SSO 映射，
      都可以统一归一化到 UserContext 中。
    """

    if not header_value:
        return []
    return [item.strip() for item in header_value.split(",") if item.strip()]


def build_local_mock_user_context() -> UserContext:
    """构造本地开发默认 mock 用户。

    这个兜底只用于本地开发与骨架联调，不代表正式生产认证方案。
    """

    return UserContext(
        user_id=1,
        username="mock_user",
        display_name="Mock User",
        roles=["employee"],
        department_code="local-dev",
        permissions=["chat:read", "chat:write"],
    )


def resolve_user_context_from_request(
    request: Request,
    *,
    allow_local_mock: bool,
) -> UserContext:
    """从请求中解析当前用户上下文。

    当前阶段的解析策略分两层：
    1. 如果请求带了 `Authorization: Bearer <token>`，认为调用方在显式声明“我要走认证链路”；
       这时系统会继续从自定义 Header 读取用户上下文占位字段；
    2. 如果没有任何认证相关头，并且当前允许本地 mock，则回退到本地开发用户。

    为什么暂时不真正解析 token：
    - 这一轮目标是把接口分层和上下文传递打稳；
    - 真实 JWT 验签、Key 管理、SSO 对接都属于下一阶段；
    - 但如果继续一直写死 `user_id=1`，后续再切认证会牵扯很多代码。
    """

    authorization = request.headers.get("Authorization")
    header_user_id = request.headers.get("X-User-Id")
    has_auth_context = any(
        [
            authorization,
            header_user_id,
            request.headers.get("X-Username"),
            request.headers.get("X-User-Roles"),
            request.headers.get("X-User-Permissions"),
        ]
    )

    if not has_auth_context and allow_local_mock:
        return build_local_mock_user_context()

    if authorization:
        if not authorization.startswith("Bearer "):
            raise AppException(
                error_code=error_codes.UNAUTHORIZED,
                message="认证头格式错误，必须使用 Bearer Token",
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"expected_scheme": "Bearer"},
            )
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise AppException(
                error_code=error_codes.UNAUTHORIZED,
                message="认证 Token 不能为空",
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={},
            )

    if not header_user_id:
        raise AppException(
            error_code=error_codes.INVALID_AUTH_CONTEXT,
            message="缺少 X-User-Id，无法构造用户上下文",
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"required_headers": ["X-User-Id"]},
        )

    try:
        user_id = int(header_user_id)
    except ValueError as exc:
        raise AppException(
            error_code=error_codes.INVALID_AUTH_CONTEXT,
            message="X-User-Id 必须是整数",
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"received_user_id": header_user_id},
        ) from exc

    username = request.headers.get("X-Username") or f"user_{user_id}"
    display_name = request.headers.get("X-Display-Name") or username
    roles = _parse_csv_header(request.headers.get("X-User-Roles")) or ["employee"]
    permissions = _parse_csv_header(request.headers.get("X-User-Permissions"))
    department_code = request.headers.get("X-Department-Code")

    return UserContext(
        user_id=user_id,
        username=username,
        display_name=display_name,
        roles=roles,
        department_code=department_code,
        permissions=permissions,
    )
