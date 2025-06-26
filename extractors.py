#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解压器模块 - 处理各种压缩格式的解压操作
"""

import os
import shutil
import zipfile
import tarfile
from pathlib import Path
from utils import safe_filename, avoid_filename_conflict, ensure_directory_exists

# 可选依赖检查
try:
    import rarfile
    RAR_AVAILABLE = True
except ImportError:
    RAR_AVAILABLE = False

try:
    import py7zr
    SEVENZ_AVAILABLE = True
except ImportError:
    SEVENZ_AVAILABLE = False


class BaseExtractor:
    """基础解压器类"""
    
    def __init__(self, logger=None):
        self.logger = logger
        self.extracted_count = 0
    
    def log_info(self, message):
        """记录信息日志"""
        if self.logger:
            self.logger.info(message)
    
    def log_warning(self, message):
        """记录警告日志"""
        if self.logger:
            self.logger.warning(f"⚠️ {message}")
    
    def extract_files_flat(self, members, extract_to, extract_func):
        """扁平化提取文件（只要文件，不要文件夹结构）"""
        extracted_count = 0
        
        for member in members:
            try:
                # 获取成员信息
                member_name = self._get_member_name(member)
                is_dir = self._is_directory(member)
                
                # 跳过目录
                if is_dir:
                    continue
                
                # 获取文件名（不包括路径）
                filename = os.path.basename(member_name)
                if not filename:  # 可能是隐藏文件或特殊情况
                    continue
                
                # 处理文件名乱码和非法字符
                safe_name = safe_filename(filename, self.logger)
                
                # 避免文件名冲突
                final_path = avoid_filename_conflict(extract_to / safe_name)
                
                # 提取单个文件
                extract_func(member, final_path)
                extracted_count += 1
                
                if extracted_count <= 10:  # 只显示前10个文件，避免日志过长
                    self.log_info(f"     ├─ {safe_name}")
                elif extracted_count == 11:
                    self.log_info(f"     ├─ ... (还有更多文件)")
                
            except Exception as e:
                self.log_warning(f"提取文件失败 {member_name}: {str(e)}")
                continue
        
        return extracted_count
    
    def extract_files_with_structure(self, members, extract_to, extract_func):
        """按原结构提取文件（处理乱码）"""
        extracted_count = 0
        
        for member in members:
            try:
                # 获取成员名称
                member_name = self._get_member_name(member)
                
                # 处理路径中的乱码
                path_parts = member_name.split('/')
                safe_path_parts = [safe_filename(part, self.logger) for part in path_parts if part]
                safe_path = '/'.join(safe_path_parts)
                
                if not safe_path:
                    continue
                
                final_path = extract_to / safe_path
                
                # 提取文件
                extract_func(member, final_path)
                extracted_count += 1
                
            except Exception as e:
                self.log_warning(f"提取文件失败 {member_name}: {str(e)}")
                continue
        
        return extracted_count
    
    def _get_member_name(self, member):
        """获取成员名称（不同格式有不同的属性名）"""
        if hasattr(member, 'filename'):  # ZIP
            return member.filename
        elif hasattr(member, 'name'):  # TAR/RAR/7Z
            return member.name
        else:
            return str(member)
    
    def _is_directory(self, member):
        """判断成员是否为目录"""
        if hasattr(member, 'is_dir'):  # ZIP
            return member.is_dir()
        elif hasattr(member, 'isdir'):  # TAR
            return member.isdir()
        else:
            # 简单判断：以/结尾的视为目录
            return self._get_member_name(member).endswith('/')


class ZipExtractor(BaseExtractor):
    """ZIP文件解压器"""
    
    def extract(self, archive_path, extract_to, extract_flat=False):
        """解压ZIP文件"""
        try:
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                # 检查是否有密码保护
                try:
                    zip_ref.testzip()
                except RuntimeError as e:
                    if "Bad password" in str(e) or "password required" in str(e):
                        raise Exception("文件有密码保护，无法解压")
                    raise e
                
                members = zip_ref.infolist()
                
                if extract_flat:
                    # 扁平化提取
                    def extract_single_zip(member, target_path):
                        ensure_directory_exists(target_path.parent)
                        with zip_ref.open(member) as source, open(target_path, 'wb') as target:
                            shutil.copyfileobj(source, target)
                    
                    return self.extract_files_flat(members, extract_to, extract_single_zip)
                else:
                    # 保持结构提取
                    def extract_single_zip(member, target_path):
                        ensure_directory_exists(target_path.parent)
                        if not member.is_dir():
                            with zip_ref.open(member) as source, open(target_path, 'wb') as target:
                                shutil.copyfileobj(source, target)
                    
                    return self.extract_files_with_structure(members, extract_to, extract_single_zip)
                
        except zipfile.BadZipFile:
            raise Exception("ZIP文件已损坏或格式不正确")
        except Exception as e:
            raise Exception(f"ZIP解压失败: {str(e)}")


class RarExtractor(BaseExtractor):
    """RAR文件解压器"""
    
    def extract(self, archive_path, extract_to, extract_flat=False):
        """解压RAR文件"""
        if not RAR_AVAILABLE:
            raise Exception("RAR支持未安装，请使用: pip install rarfile")
            
        try:
            with rarfile.RarFile(archive_path, 'r') as rar_ref:
                # 检查是否需要密码
                if rar_ref.needs_password():
                    raise Exception("RAR文件有密码保护，无法解压")
                
                members = rar_ref.infolist()
                
                if extract_flat:
                    # 扁平化提取
                    def extract_single_rar(member, target_path):
                        ensure_directory_exists(target_path.parent)
                        with rar_ref.open(member) as source, open(target_path, 'wb') as target:
                            shutil.copyfileobj(source, target)
                    
                    return self.extract_files_flat(members, extract_to, extract_single_rar)
                else:
                    # 保持结构提取
                    def extract_single_rar(member, target_path):
                        ensure_directory_exists(target_path.parent)
                        if not member.is_dir():
                            with rar_ref.open(member) as source, open(target_path, 'wb') as target:
                                shutil.copyfileobj(source, target)
                    
                    return self.extract_files_with_structure(members, extract_to, extract_single_rar)
                
        except rarfile.BadRarFile:
            raise Exception("RAR文件已损坏或格式不正确")
        except Exception as e:
            raise Exception(f"RAR解压失败: {str(e)}")


class SevenZipExtractor(BaseExtractor):
    """7Z文件解压器"""
    
    def extract(self, archive_path, extract_to, extract_flat=False):
        """解压7Z文件"""
        if not SEVENZ_AVAILABLE:
            raise Exception("7Z支持未安装，请使用: pip install py7zr")
            
        try:
            with py7zr.SevenZipFile(archive_path, mode='r') as z:
                # 检查是否需要密码
                if z.needs_password():
                    raise Exception("7Z文件有密码保护，无法解压")
                
                if extract_flat:
                    # 扁平化提取
                    extracted_count = 0
                    for info in z.list():
                        if not info.is_dir:
                            filename = os.path.basename(info.filename)
                            if filename:
                                safe_name = safe_filename(filename, self.logger)
                                final_path = avoid_filename_conflict(extract_to / safe_name)
                                
                                # 提取文件
                                ensure_directory_exists(final_path.parent)
                                z.extract(targets=[info.filename], path=final_path.parent)
                                
                                # 移动到最终位置（如果需要重命名）
                                extracted_file = final_path.parent / info.filename
                                if extracted_file != final_path:
                                    shutil.move(str(extracted_file), str(final_path))
                                
                                extracted_count += 1
                                
                                if extracted_count <= 10:
                                    self.log_info(f"     ├─ {safe_name}")
                                elif extracted_count == 11:
                                    self.log_info(f"     ├─ ... (还有更多文件)")
                    
                    return extracted_count
                else:
                    # 保持结构提取
                    z.extractall(extract_to)
                    return len([info for info in z.list() if not info.is_dir])
                
        except py7zr.Bad7zFile:
            raise Exception("7Z文件已损坏或格式不正确")
        except Exception as e:
            raise Exception(f"7Z解压失败: {str(e)}")


class TarExtractor(BaseExtractor):
    """TAR系列文件解压器"""
    
    def extract(self, archive_path, extract_to, extract_flat=False):
        """解压TAR系列文件"""
        try:
            with tarfile.open(archive_path, 'r:*') as tar_ref:
                members = tar_ref.getmembers()
                
                if extract_flat:
                    # 扁平化提取
                    def extract_single_tar(member, target_path):
                        if member.isfile():
                            ensure_directory_exists(target_path.parent)
                            with tar_ref.extractfile(member) as source, open(target_path, 'wb') as target:
                                shutil.copyfileobj(source, target)
                    
                    return self.extract_files_flat(members, extract_to, extract_single_tar)
                else:
                    # 保持结构提取（安全检查）
                    def extract_single_tar(member, target_path):
                        if not (member.name.startswith('/') or '..' in member.name):
                            if member.isfile():
                                ensure_directory_exists(target_path.parent)
                                with tar_ref.extractfile(member) as source, open(target_path, 'wb') as target:
                                    shutil.copyfileobj(source, target)
                    
                    return self.extract_files_with_structure(members, extract_to, extract_single_tar)
                
        except tarfile.TarError:
            raise Exception("TAR文件已损坏或格式不正确")
        except Exception as e:
            raise Exception(f"TAR解压失败: {str(e)}")


# 解压器工厂函数
def get_extractor(file_extension, logger=None):
    """
    根据文件扩展名获取对应的解压器
    
    Args:
        file_extension: 文件扩展名
        logger: 日志记录器
        
    Returns:
        BaseExtractor: 解压器实例
    """
    extractors = {
        '.zip': ZipExtractor,
        '.rar': RarExtractor,
        '.7z': SevenZipExtractor,
        '.tar': TarExtractor,
        '.tar.gz': TarExtractor,
        '.tgz': TarExtractor,
        '.tar.bz2': TarExtractor,
        '.tbz2': TarExtractor,
        '.tar.xz': TarExtractor,
        '.txz': TarExtractor,
    }
    
    extractor_class = extractors.get(file_extension)
    if extractor_class:
        return extractor_class(logger)
    else:
        raise ValueError(f"不支持的文件格式: {file_extension}")
