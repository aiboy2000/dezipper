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
import chardet # chardet をインポート
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
import sys # sysモジュールをインポート

def _is_ascii_only(s: str) -> bool:
    """文字列がASCII文字のみで構成されているかチェック"""
    return all(ord(c) < 128 for c in s)

def _try_decode_bytes(byte_sequence, logger=None):
    """指定されたバイトシーケンスに対してchardetとENCODING_ORDERでデコードを試みるヘルパー関数"""
    decoded_str = None
    if logger:
        logger.debug(f"_try_decode_bytes: Attempting to decode byte sequence: {byte_sequence!r}")

    # 1. chardet
    detected_info = chardet.detect(byte_sequence)
    if logger:
        logger.debug(f"_try_decode_bytes: chardet.detect result: {detected_info}")
    if detected_info and detected_info['encoding'] and detected_info['confidence'] > 0.7:
        try:
            decoded_str = byte_sequence.decode(detected_info['encoding'])
            if logger:
                logger.debug(f"_try_decode_bytes: Decoded as '{detected_info['encoding']}' by chardet (conf: {detected_info['confidence']:.2f}). Result: {decoded_str!r}")
            return decoded_str # 成功したら返す
        except (UnicodeDecodeError, UnicodeError, LookupError) as e:
            if logger:
                logger.debug(f"_try_decode_bytes: Chardet detected '{detected_info['encoding']}' but decoding failed: {e}")
            decoded_str = None

    # 2. ENCODING_ORDER
    if decoded_str is None:
        if logger:
            logger.debug(f"_try_decode_bytes: chardet failed or low confidence. Trying ENCODING_ORDER: {ENCODING_ORDER}")
        for enc in ENCODING_ORDER:
            try:
                decoded_str = byte_sequence.decode(enc)
                if logger:
                    logger.debug(f"_try_decode_bytes: Successfully decoded as '{enc}' from ENCODING_ORDER. Result: {decoded_str!r}")
                return decoded_str # 成功したら返す
            except (UnicodeDecodeError, UnicodeError):
                if logger:
                    logger.debug(f"_try_decode_bytes: Failed to decode as '{enc}'.")
                continue
        else: # ループがbreakしなかった場合
            if logger:
                logger.warning(f"_try_decode_bytes: All ENCODING_ORDER attempts failed for byte string. Original bytes: {byte_sequence!r}")
            # ここではNoneを返す (呼び出し元で最終フォールバック処理)
            return None
    return None # chardet成功時以外でここに到達しないはずだが念のため

def safe_filename(filename, logger=None):
    """
    处理可能包含非法字符或乱码的文件名

    Args:
        filename: 原始文件名
        logger: 可选的日志记录器

    Returns:
        str: 安全的文件名
    """
    if logger:
        logger.debug(f"safe_filename: Received raw filename: {filename!r} (type: {type(filename)})")

    try:
        filename_str = None

        if isinstance(filename, bytes):
            filename_str = _try_decode_bytes(filename, logger)
            if filename_str is None: # _try_decode_bytes がNoneを返した場合 (全てのデコード失敗)
                if logger:
                    logger.warning(f"safe_filename: Decoding byte input failed completely. Falling back to utf-8 with 'replace'. Original bytes: {filename!r}")
                filename_str = filename.decode('utf-8', errors='replace')

        elif isinstance(filename, str):
            if _is_ascii_only(filename):
                if logger:
                    logger.debug(f"safe_filename: Input is ASCII-only str: {filename!r}. Skipping advanced decoding attempts.")
                filename_str = filename
            else:
                if logger:
                    logger.debug(f"safe_filename: Input is non-ASCII str: {filename!r}. Attempting re-encode and decode.")

                # 文字化けしたstrをバイト列に戻すための試行エンコーディングリスト
                # WindowsのANSIコードページ(mbcs)、zipfileが使うcp437、汎用的なlatin-1など
                re_encode_candidates = ['mbcs'] if os.name == 'nt' else [sys.getfilesystemencoding()]
                re_encode_candidates += ['cp437', 'latin-1'] # これらも試す価値あり

                successfully_re_decoded = False
                for re_enc in re_encode_candidates:
                    try:
                        if logger:
                            logger.debug(f"safe_filename: Trying to re-encode str to bytes using '{re_enc}' (with surrogateescape).")
                        byte_candidate = filename.encode(re_enc, errors='surrogateescape')
                        if logger:
                            logger.debug(f"safe_filename: Re-encoded to bytes: {byte_candidate!r}")

                        # 得られたバイト列候補を再度デコード試行
                        decoded_from_candidate = _try_decode_bytes(byte_candidate, logger)
                        if decoded_from_candidate is not None:
                            filename_str = decoded_from_candidate
                            successfully_re_decoded = True
                            if logger:
                                logger.info(f"safe_filename: Successfully re-decoded str via '{re_enc}' into: {filename_str!r}")
                            break
                    except Exception as e_re_enc:
                        if logger:
                            logger.debug(f"safe_filename: Failed to re-encode str using '{re_enc}': {e_re_enc}")
                        continue

                if not successfully_re_decoded:
                    if logger:
                        logger.warning(f"safe_filename: Failed to re-decode non-ASCII str. Proceeding with original (potentially garbled) str: {filename!r}")
                    filename_str = filename # どの試行もうまくいかなければ元のstr

        else: # bytesでもstrでもない場合
            if logger:
                logger.error(f"safe_filename: Received unexpected type: {type(filename)}. Value: {filename!r}. Converting to string representation.")
            try:
                filename_str = str(filename) # 強引に文字列化
            except Exception as e_conv:
                if logger:
                    logger.error(f"safe_filename: Failed to convert type {type(filename)} to string: {e_conv}. Using fallback name.")
                filename_str = f"unprocessable_type_{int(time.time())}"


        # 规范化Unicode字符 (filename_str はこの時点で必ず str)
        normalized_filename = unicodedata.normalize('NFC', filename_str)
        if logger and normalized_filename != filename_str: # 変更があった場合のみログ出力
            logger.debug(f"safe_filename: Normalized from {filename_str!r} to {normalized_filename!r}")
        
        # 移除或替换非法字符
        safe_filename_str = re.sub(ILLEGAL_CHARS_PATTERN, '_', normalized_filename)
        if logger and safe_filename_str != normalized_filename: # 変更があった場合のみログ出力
            logger.debug(f"safe_filename: Replaced illegal chars from {normalized_filename!r} to {safe_filename_str!r}")
            
        # Strip leading/trailing dots and spaces
        final_filename = safe_filename_str.strip('. ')
        if logger and final_filename != safe_filename_str: # 変更があった場合のみログ出力
            logger.debug(f"safe_filename: Stripped dots/spaces from {safe_filename_str!r} to {final_filename!r}")

        # 处理空文件名
        if not final_filename:
            final_filename = f"unnamed_file_{int(time.time())}"
            if logger:
                logger.warning(f"safe_filename: Filename became empty after sanitization. Using fallback: {final_filename}")

        if logger:
            logger.debug(f"safe_filename: Returning final safe filename: {final_filename!r}")
        return final_filename
        
    except Exception as e:
        # このトップレベルのtry-exceptは、予期せぬ重大なエラーを捕捉するためのもの
        if logger:
            logger.error(f"safe_filename: Unexpected critical error during safe_filename processing for input {filename!r}: {e}", exc_info=True)
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
        path_obj = Path(directory_path)
        # Windowsの場合、長いパスに対応するために \\?\ プレフィックスを試す
        if os.name == 'nt':
            path_str = str(path_obj.resolve()) # resolve() で絶対パスにし、シンボリックリンクも解決
            # MAX_PATHに近い長さの場合にプレフィックスを付与
            # Python 3.6+ で LongPathsEnabled が有効なら不要な場合もあるが、互換性のため
            if len(path_str) >= 240: # 260より少し手前で予防的に
                if not path_str.startswith('\\\\?\\'):
                    # 既に \\?\ が付いている場合は何もしない (resolve() が返す可能性は低いが念のため)
                    # abspath を使ってから \\?\ を付けるのが一般的
                    # ただし Path.resolve() が既に適切な絶対パスを返していることを期待
                    path_to_create_str = '\\\\?\\' + path_str
                    Path(path_to_create_str).mkdir(parents=True, exist_ok=True)
                    return True

        # 通常の処理 (Windowsで短いパスの場合、または非Windows OSの場合)
        path_obj.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        # エラーログは呼び出し元で出すか、ここで出すか選択
        # print(f"Error creating directory {directory_path}: {e}")
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
