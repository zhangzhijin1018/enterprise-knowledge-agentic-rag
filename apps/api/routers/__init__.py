"""API 业务路由包。"""

from apps.api.routers.analytics import router as analytics_router
from apps.api.routers.analytics_exports import router as analytics_exports_router
from apps.api.routers.analytics_reviews import router as analytics_reviews_router
from apps.api.routers.chat import router as chat_router
from apps.api.routers.clarifications import router as clarifications_router
from apps.api.routers.contracts import router as contracts_router
from apps.api.routers.contract_review import router as contract_review_router
from apps.api.routers.conversations import router as conversations_router
from apps.api.routers.documents import router as documents_router
from apps.api.routers.rag import router as rag_router
from apps.api.routers.retrieval import router as retrieval_router
from apps.api.routers.reviews import router as reviews_router

__all__ = [
    "analytics_router",
    "analytics_exports_router",
    "analytics_reviews_router",
    "chat_router",
    "conversations_router",
    "clarifications_router",
    "contracts_router",
    "contract_review_router",
    "documents_router",
    "rag_router",
    "retrieval_router",
    "reviews_router",
]
