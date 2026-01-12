"""
通用数据模型
"""
from typing import Generic, TypeVar, List, Optional
from pydantic import BaseModel, Field

T = TypeVar("T")


class Response(BaseModel, Generic[T]):
    """统一响应格式"""
    code: int = Field(default=200, description="状态码")
    message: str = Field(default="success", description="消息")
    data: Optional[T] = Field(default=None, description="数据")


class PageParams(BaseModel):
    """分页参数"""
    page: int = Field(1, ge=1, description="页码")
    page_size: int = Field(20, ge=1, le=100, description="每页数量")


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应"""
    items: List[T] = Field([], description="数据列表")
    total: int = Field(0, description="总数量")
    page: int = Field(1, description="当前页码")
    page_size: int = Field(20, description="每页数量")
    total_pages: int = Field(0, description="总页数")

    @classmethod
    def create(cls, items: List[T], total: int, page: int, page_size: int):
        """创建分页响应"""
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
