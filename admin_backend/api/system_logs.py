"""
系统日志查看 API - 管理后台
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from admin_utils.auth import get_current_admin
import os
import logging
from typing import List, Optional
from datetime import datetime

router = APIRouter()

# 日志目录配置
LOG_DIR = os.getenv('LOG_PATH', '/app/logs')

# 支持的日志文件类型
SUPPORTED_LOG_FILES = ['app.log', 'error.log', 'access.log']


def get_log_files_info() -> List[dict]:
    """获取日志文件列表"""
    log_files = []

    if not os.path.exists(LOG_DIR):
        return log_files

    for filename in os.listdir(LOG_DIR):
        if filename.endswith('.log') or filename.endswith('.log.*'):
            file_path = os.path.join(LOG_DIR, filename)
            if os.path.isfile(file_path):
                stat = os.stat(file_path)
                size = stat.st_size

                # 格式化文件大小
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                elif size < 1024 * 1024 * 1024:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                else:
                    size_str = f"{size / (1024 * 1024 * 1024):.1f} GB"

                # 获取修改时间
                mtime = datetime.fromtimestamp(stat.st_mtime)

                log_files.append({
                    "name": filename,
                    "path": file_path,
                    "size": size_str,
                    "modified": mtime.strftime("%Y-%m-%d %H:%M:%S")
                })

    # 按修改时间倒序排列
    log_files.sort(key=lambda x: x['modified'], reverse=True)
    return log_files


def read_log_file(file_path: str, lines: int = 100) -> List[str]:
    """读取日志文件的最后 N 行"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"日志文件不存在: {file_path}")

    if not os.path.isfile(file_path):
        raise ValueError(f"路径不是文件: {file_path}")

    # 安全检查：确保文件在日志目录内
    real_path = os.path.realpath(file_path)
    real_log_dir = os.path.realpath(LOG_DIR)
    if not real_path.startswith(real_log_dir):
        raise ValueError("非法的日志文件路径")

    # 读取文件最后 N 行
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            # 读取所有行（对于大文件可能需要优化）
            all_lines = f.readlines()
            # 返回最后 N 行
            return all_lines[-lines:] if lines > 0 else all_lines
    except Exception as e:
        logging.error(f"读取日志文件失败: {e}")
        raise


@router.get("/system-logs/files")
async def get_log_files(
    admin = Depends(get_current_admin)
):
    """获取日志文件列表"""
    try:
        files = get_log_files_info()
        return {
            "code": 200,
            "message": "success",
            "data": files
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取日志文件列表失败: {str(e)}"
        )


@router.get("/system-logs/view")
async def view_log(
    filename: str = Query(..., description="日志文件名"),
    lines: int = Query(100, ge=1, le=10000, description="读取行数"),
    admin = Depends(get_current_admin)
):
    """读取日志内容"""
    try:
        # 验证文件名，防止路径遍历攻击
        if '..' in filename or '/' in filename or '\\' in filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="非法的文件名"
            )

        file_path = os.path.join(LOG_DIR, filename)
        content = read_log_file(file_path, lines)

        return {
            "code": 200,
            "message": "success",
            "data": {
                "filename": filename,
                "content": content,
                "total_lines": len(content)
            }
        }
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="日志文件不存在"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logging.error(f"读取日志失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取日志失败: {str(e)}"
        )


@router.get("/system-logs/tailf")
async def tail_log(
    filename: str = Query(..., description="日志文件名"),
    position: int = Query(0, ge=0, description="起始位置（行号）"),
    admin = Depends(get_current_admin)
):
    """实时监控日志（返回从 position 开始的新增行）"""
    try:
        # 验证文件名
        if '..' in filename or '/' in filename or '\\' in filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="非法的文件名"
            )

        file_path = os.path.join(LOG_DIR, filename)

        if not os.path.exists(file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="日志文件不存在"
            )

        # 读取文件所有行
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()

        # 获取从 position 开始的新增行
        new_lines = all_lines[position:] if position < len(all_lines) else []
        new_position = len(all_lines)

        return {
            "code": 200,
            "message": "success",
            "data": {
                "filename": filename,
                "content": new_lines,
                "position": new_position,
                "has_more": position < len(all_lines)
            }
        }
    except Exception as e:
        logging.error(f"监控日志失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"监控日志失败: {str(e)}"
        )


@router.get("/system-logs/stats")
async def get_log_stats(
    admin = Depends(get_current_admin)
):
    """获取日志统计信息"""
    try:
        files = get_log_files_info()

        stats = {
            "total_files": len(files),
            "total_size": 0,
            "files": []
        }

        for f in files:
            # 计算总大小（字节）
            file_path = f['path']
            if os.path.exists(file_path):
                size_bytes = os.path.getsize(file_path)
                stats['total_size'] += size_bytes

            stats['files'].append({
                "name": f['name'],
                "size": f['size'],
                "modified": f['modified']
            })

        # 格式化总大小
        total_bytes = stats['total_size']
        if total_bytes < 1024 * 1024:
            stats['total_size_formatted'] = f"{total_bytes / 1024:.1f} KB"
        elif total_bytes < 1024 * 1024 * 1024:
            stats['total_size_formatted'] = f"{total_bytes / (1024 * 1024):.1f} MB"
        else:
            stats['total_size_formatted'] = f"{total_bytes / (1024 * 1024 * 1024):.1f} GB"

        return {
            "code": 200,
            "message": "success",
            "data": stats
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取日志统计失败: {str(e)}"
        )
