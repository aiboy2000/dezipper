#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具函数模块 - 提供通用的工具函数
"""

import os
import time
import unicodedata
import re
from pathlib import Path
from config import ENCODING_ORDER, ILLEGAL_CHARS_PATTERN, COMPOUND_EXTENSIONS


def format_file_size(size_bytes):
    """格式化文件大小显示"""
    if size_bytes == 0:
        return "0 B"
    
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def safe_filename(filename, logger=None):
    """
    处理可能包含非法字符或乱码的文件名
    
    Args:
        filename: 原始文件名
        logger: 可选的日志记录器
        
    Returns:
        str: 安全的文件名
    """
    try:
        # 尝试正确解码文件名
        if isinstance(filename, bytes):
            # 尝试多种编码方式
            for encoding in ENCODING_ORDER:
                try:
                    filename = filename.decode(encoding)
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue
            else:
                # 如果所有编码都失败，使用错误处理
                filename = filename.decode('utf-8', errors='replace')
        
        # 规范化Unicode字符
        filename = unicodedata.normalize('NFC', filename)
        
        # 移除或替换非法字符
        filename = re.sub(ILLEGAL_CHARS_PATTERN, '_', filename)
        filename = filename.strip('. ')
        
        # 处理空文件名
        if not filename:
            filename = f"unnamed_file_{int(time.time())}"
            
        return filename
        
    except Exception as e:
        if logger:
            logger.warning(f"文件名处理失败: {str(e)}")
        return f"unnamed_file_{int(time.time())}"


def get_file_extension(file_path):
    """
    获取文件扩展名，处理复合扩展名
    
    Args:
        file_path: 文件路径对象
        
    Returns:
        str: 文件扩展名（小写）
    """
    file_str = str(file_path).lower()
    
    # 检查复合扩展名
    for ext in COMPOUND_EXTENSIONS:
        if file_str.endswith(ext):
            return ext
            
    return file_path.suffix.lower()


def avoid_filename_conflict(target_path):
    """
    避免文件名冲突，如果文件已存在则添加数字后缀
    
    Args:
        target_path: 目标文件路径
        
    Returns:
        Path: 不冲突的文件路径
    """
    if not target_path.exists():
        return target_path
    
    counter = 1
    while True:
        name_part, ext_part = os.path.splitext(target_path.name)
        new_name = f"{name_part}_{counter}{ext_part}"
        new_path = target_path.parent / new_name
        
        if not new_path.exists():
            return new_path
        
        counter += 1
        
        # 防止无限循环
        if counter > 9999:
            return target_path.parent / f"{name_part}_{int(time.time())}{ext_part}"


def ensure_directory_exists(directory_path):
    """
    确保目录存在，如果不存在则创建
    
    Args:
        directory_path: 目录路径
        
    Returns:
        bool: 是否成功创建或目录已存在
    """
    try:
        Path(directory_path).mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


def is_safe_path(file_path):
    """
    检查路径是否安全（防止路径遍历攻击）
    
    Args:
        file_path: 文件路径字符串
        
    Returns:
        bool: 路径是否安全
    """
    # 检查是否包含危险的路径模式
    if file_path.startswith('/') or '..' in file_path:
        return False
    
    # 检查是否包含其他危险字符
    dangerous_patterns = ['\\', ':', '*', '?', '"', '<', '>', '|']
    for pattern in dangerous_patterns:
        if pattern in file_path:
            return False
    
    return True


def get_unique_backup_name(original_path, timestamp_format='%Y%m%d_%H%M%S'):
    """
    生成唯一的备份文件夹名称
    
    Args:
        original_path: 原始路径
        timestamp_format: 时间戳格式
        
    Returns:
        Path: 备份路径
    """
    from datetime import datetime
    
    original_path = Path(original_path)
    timestamp = datetime.now().strftime(timestamp_format)
    backup_name = f"{original_path.name}_backup_{timestamp}"
    backup_path = original_path.parent / backup_name
    
    # 如果仍然存在冲突，添加计数器
    counter = 1
    while backup_path.exists():
        backup_name = f"{original_path.name}_backup_{timestamp}_{counter}"
        backup_path = original_path.parent / backup_name
        counter += 1
    
    return backup_path
