"""
兑换码管理 API - 管理后台
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional
from datetime import datetime
import secrets
import string
import logging

from admin_database_user import (
    get_user_db, ExchangeCode, WebUser
)
from admin_utils.auth import get_current_admin
from pydantic import BaseModel, Field
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

# 简化版响应模型，避免 Generic 序列化问题
T = TypeVar("T")

class ApiResponse(BaseModel):
    """统一响应格式"""
    code: int = 200
    message: str = "success"
    data: Optional[dict] = None

router = APIRouter()


def generate_exchange_code(length: int = 16) -> str:
    """生成兑换码"""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def get_exchange_code_type_name(code_type: int) -> str:
    """获取兑换码类型名称"""
    type_names = {
        1: "激活试用",
        2: "按天续期",
        3: "按月续期",
        4: "充值余额"
    }
    return type_names.get(code_type, "未知")


def get_exchange_code_status_name(status: int) -> str:
    """获取兑换码状态名称"""
    status_names = {
        -1: "已禁用",
        0: "未使用",
        1: "已使用"
    }
    return status_names.get(status, "未知")


@router.get("/exchange-codes")
async def get_exchange_codes(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[int] = Query(None, description="状态筛选：-1禁用 0未使用 1已使用"),
    type: Optional[int] = Query(None, description="类型筛选：1激活试用 2按天续期 3按月续期 4充值积分"),
    search: Optional[str] = Query(None, description="搜索兑换码"),
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取兑换码列表"""
    query = db.query(ExchangeCode)

    # 状态筛选
    if status is not None:
        query = query.filter(ExchangeCode.status == status)

    # 类型筛选
    if type is not None:
        query = query.filter(ExchangeCode.type == type)

    # 搜索
    if search:
        query = query.filter(ExchangeCode.code.contains(search.upper()))

    total = query.count()
    codes = query.order_by(
        ExchangeCode.created_at.desc()
    ).offset(skip).limit(limit).all()

    result = []
    for code in codes:
        # 获取使用用户名
        used_by_username = None
        if code.used_by_user_id:
            user = db.query(WebUser).filter(WebUser.id == code.used_by_user_id).first()
            used_by_username = user.username if user else "未知用户"

        # 类型4（充值余额）需要将分转换为元显示
        display_count = code.exchange_count
        if code.type == 4:  # 充值余额类型，存储单位是分，显示时转换为元
            display_count = code.exchange_count / 100

        result.append({
            "id": code.id,
            "code": code.code,
            "type": code.type,
            "type_name": get_exchange_code_type_name(code.type),
            "exchange_count": display_count,  # 显示值（元）
            "status": code.status,
            "status_name": get_exchange_code_status_name(code.status),
            "used_by_user_id": code.used_by_user_id,
            "used_by_username": used_by_username,
            "used_at": code.used_at.isoformat() if code.used_at else None,
            "created_by_admin_id": code.created_by_admin_id,
            "created_by_admin_username": f"管理员_{code.created_by_admin_id}" if code.created_by_admin_id else None,
            "note": code.note,
            "created_at": code.created_at.isoformat() if code.created_at else None
        })

    return {
        "total": total,
        "items": result
    }


@router.get("/exchange-codes/{code_id}")
async def get_exchange_code(
    code_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取单个兑换码详情"""
    code = db.query(ExchangeCode).filter(ExchangeCode.id == code_id).first()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="兑换码不存在"
        )

    # 获取使用用户名
    used_by_username = None
    if code.used_by_user_id:
        user = db.query(WebUser).filter(WebUser.id == code.used_by_user_id).first()
        used_by_username = user.username if user else "未知用户"

    # 类型4（充值余额）需要将分转换为元显示
    display_count = code.exchange_count
    if code.type == 4:  # 充值余额类型，存储单位是分，显示时转换为元
        display_count = code.exchange_count / 100

    return {
        "id": code.id,
        "code": code.code,
        "type": code.type,
        "type_name": get_exchange_code_type_name(code.type),
        "exchange_count": display_count,  # 显示值（元）
        "status": code.status,
        "status_name": get_exchange_code_status_name(code.status),
        "used_by_user_id": code.used_by_user_id,
        "used_by_username": used_by_username,
        "used_at": code.used_at.isoformat() if code.used_at else None,
        "created_by_admin_id": code.created_by_admin_id,
        "created_by_admin_username": f"管理员_{code.created_by_admin_id}" if code.created_by_admin_id else None,
        "note": code.note,
        "created_at": code.created_at.isoformat() if code.created_at else None,
        "updated_at": code.updated_at.isoformat() if code.updated_at else None
    }


# 请求模型
class CreateExchangeCodeRequest(BaseModel):
    """创建兑换码请求"""
    code: Optional[str] = Field(None, description="兑换码（留空自动生成）")
    type: int = Field(1, ge=1, le=4, description="兑换码类型：1激活试用 2按天续期 3按月续期 4充值余额")
    exchange_count: int = Field(1, ge=1, description="兑换数量/天数/余额（元）")
    note: Optional[str] = Field(None, description="备注")

    # 验证器：处理空字符串
    @staticmethod
    def validate_code(code: Optional[str]) -> Optional[str]:
        """验证并清理兑换码"""
        if code is None or code.strip() == "":
            return None
        return code.strip()[:64]

    class Config:
        # 使用自定义验证
        schema_extra = {
            "example": {
                "code": "",
                "type": 1,
                "exchange_count": 1,
                "note": "备注"
            }
        }


class BatchCreateExchangeCodeRequest(BaseModel):
    """批量创建兑换码请求"""
    count: int = Field(..., ge=1, le=100, description="生成数量")
    type: int = Field(..., ge=1, le=4, description="兑换码类型")
    exchange_count: int = Field(1, ge=1, description="兑换数量/天数/余额（元）")
    note: Optional[str] = Field(None, description="备注")


@router.post("/exchange-codes")
async def create_exchange_code(
    data: CreateExchangeCodeRequest,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """创建兑换码（单个）"""
    try:
        # 处理空字符串
        code_input = data.code.strip() if data.code else None
        code_str = code_input if code_input else generate_exchange_code()

        # 检查兑换码是否已存在
        existing = db.query(ExchangeCode).filter(
            ExchangeCode.code == code_str.upper()
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="兑换码已存在"
            )

        # 类型4（充值余额）需要将元转换为分
        exchange_count = data.exchange_count
        if data.type == 4:  # 充值余额类型，输入单位是元，需要转换为分
            exchange_count = data.exchange_count * 100

        # 创建兑换码
        code = ExchangeCode(
            code=code_str.upper(),
            type=data.type,
            exchange_count=exchange_count,
            note=data.note,
            status=0,
            created_by_admin_id=admin.id
        )
        db.add(code)
        db.commit()
        db.refresh(code)

        # 类型4（充值余额）需要将分转换为元显示
        display_count = code.exchange_count
        if code.type == 4:  # 充值余额类型，存储单位是分，显示时转换为元
            display_count = code.exchange_count / 100

        return ApiResponse(
            code=200,
            message="创建成功",
            data={
                "id": code.id,
                "code": code.code,
                "type": code.type,
                "type_name": get_exchange_code_type_name(code.type),
                "exchange_count": display_count,  # 显示值（元）
                "status": code.status,
                "note": code.note
            }
        )
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"创建兑换码数据库错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建兑换码失败，请稍后重试"
        )
    except Exception as e:
        logger.error(f"创建兑换码未知错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建兑换码失败: {str(e)}"
        )


@router.post("/exchange-codes/batch")
async def batch_create_exchange_codes(
    data: BatchCreateExchangeCodeRequest,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """批量生成兑换码"""
    try:
        # 类型4（充值余额）需要将元转换为分
        exchange_count = data.exchange_count
        if data.type == 4:  # 充值余额类型，输入单位是元，需要转换为分
            exchange_count = data.exchange_count * 100

        created_codes = []
        for _ in range(data.count):
            code_str = generate_exchange_code()
            code = ExchangeCode(
                code=code_str,
                type=data.type,
                exchange_count=exchange_count,
                note=data.note,
                status=0,
                created_by_admin_id=admin.id
            )
            db.add(code)
            created_codes.append(code)

        db.commit()

        return ApiResponse(
            code=200,
            message=f"成功生成 {data.count} 个兑换码",
            data={
                "count": len(created_codes),
                "codes": [c.code for c in created_codes]
            }
        )
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"批量创建兑换码数据库错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="批量创建兑换码失败，请稍后重试"
        )
    except Exception as e:
        logger.error(f"批量创建兑换码未知错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"批量创建兑换码失败: {str(e)}"
        )


@router.put("/exchange-codes/{code_id}/status")
async def update_exchange_code_status(
    code_id: int,
    data: dict,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """更新兑换码状态"""
    code = db.query(ExchangeCode).filter(ExchangeCode.id == code_id).first()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="兑换码不存在"
        )

    new_status = data.get('status')
    if new_status not in [-1, 0, 1]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的状态值"
        )

    # 已使用的兑换码不能修改状态
    if code.status == 1 and new_status != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="已使用的兑换码不能修改状态"
        )

    code.status = new_status
    code.updated_at = datetime.now()
    db.commit()

    return {
        "message": "状态更新成功",
        "status": new_status,
        "status_name": get_exchange_code_status_name(new_status)
    }


@router.delete("/exchange-codes/{code_id}")
async def delete_exchange_code(
    code_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """删除兑换码"""
    code = db.query(ExchangeCode).filter(ExchangeCode.id == code_id).first()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="兑换码不存在"
        )

    # 已使用的兑换码不能删除
    if code.status == 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="已使用的兑换码不能删除"
        )

    db.delete(code)
    db.commit()

    return {"message": "删除成功"}


@router.get("/exchange-codes/stats/overview")
async def get_exchange_code_stats(
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取兑换码统计概览"""
    total = db.query(ExchangeCode).count()
    unused = db.query(ExchangeCode).filter(ExchangeCode.status == 0).count()
    used = db.query(ExchangeCode).filter(ExchangeCode.status == 1).count()
    disabled = db.query(ExchangeCode).filter(ExchangeCode.status == -1).count()

    # 按类型统计
    from sqlalchemy import func
    type_stats = db.query(
        ExchangeCode.type,
        func.count(ExchangeCode.id)
    ).group_by(ExchangeCode.type).all()

    by_type = {
        "activate_trial": 0,
        "extend_days": 0,
        "extend_months": 0,
        "recharge_balance": 0
    }
    for code_type, count in type_stats:
        if code_type == 1:
            by_type["activate_trial"] = count
        elif code_type == 2:
            by_type["extend_days"] = count
        elif code_type == 3:
            by_type["extend_months"] = count
        elif code_type == 4:
            by_type["recharge_balance"] = count

    return {
        "total": total,
        "unused": unused,
        "used": used,
        "disabled": disabled,
        "by_type": by_type
    }
