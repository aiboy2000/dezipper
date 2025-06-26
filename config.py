#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置模块 - 存储工具的配置信息和常量
"""

# 支持的压缩文件扩展名
SUPPORTED_EXTENSIONS = {
    '.zip': 'ZIP压缩文件',
    '.rar': 'RAR压缩文件', 
    '.7z': '7-Zip压缩文件',
    '.tar': 'TAR归档文件',
    '.tar.gz': 'TAR.GZ压缩文件',
    '.tgz': 'TGZ压缩文件',
    '.tar.bz2': 'TAR.BZ2压缩文件',
    '.tbz2': 'TBZ2压缩文件',
    '.tar.xz': 'TAR.XZ压缩文件',
    '.txz': 'TXZ压缩文件',
}

# 复合扩展名（需要特殊处理）
COMPOUND_EXTENSIONS = ['.tar.gz', '.tar.bz2', '.tar.xz']

# 文件名编码检测顺序
ENCODING_ORDER = ['utf-8', 'gbk', 'gb2312', 'big5', 'shift_jis', 'cp932', 'latin1']

# 非法文件名字符（需要替换）
ILLEGAL_CHARS_PATTERN = r'[<>:"/\\|?*]'

# 处理限制
MAX_PROCESSING_ROUNDS = 50  # 最大处理轮数，防止无限循环
MAX_LOG_FILES_DISPLAY = 10  # 日志中最多显示的文件数量

# 日志格式
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
LOG_FILENAME_FORMAT = 'batch_extractor_%Y%m%d_%H%M%S.log'

# 统计信息字段
STATS_FIELDS = [
    'found',           # 发现的压缩文件数
    'processed',       # 已处理的压缩文件数
    'success',         # 成功解压的文件数
    'error',           # 解压失败的文件数
    'total_size',      # 压缩文件总大小
    'freed_size',      # 释放的磁盘空间
    'extracted_files'  # 提取的文件总数
]
