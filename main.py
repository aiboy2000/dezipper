#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量解压缩工具 - 主程序
"""

import os
import sys
import shutil
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime

from config import (
    SUPPORTED_EXTENSIONS, MAX_PROCESSING_ROUNDS, 
    LOG_FORMAT, LOG_FILENAME_FORMAT, STATS_FIELDS
)
from utils import (
    format_file_size, get_file_extension, 
    get_unique_backup_name, ensure_directory_exists
)
from extractors import get_extractor


class BatchExtractor:
    """批量解压缩工具主类"""
    
    def __init__(self, work_dir, create_backup=True, delete_original=True, 
                 preserve_structure=True, extract_flat=False):
        self.work_dir = Path(work_dir)
        self.create_backup = create_backup
        self.delete_original = delete_original
        self.preserve_structure = preserve_structure
        self.extract_flat = extract_flat
        
        # 初始化统计信息
        self.stats = {field: 0 for field in STATS_FIELDS}
        
        # 设置日志
        self.setup_logging()
        
    def setup_logging(self):
        """设置日志记录"""
        log_filename = datetime.now().strftime(LOG_FILENAME_FORMAT)
        log_path = self.work_dir / log_filename
        
        logging.basicConfig(
            level=logging.INFO,
            format=LOG_FORMAT,
            handlers=[
                logging.FileHandler(log_path, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
        
    def log_info(self, message):
        """记录信息日志"""
        self.logger.info(message)
        
    def log_error(self, message):
        """记录错误日志"""
        self.logger.error(message)
        
    def log_success(self, message):
        """记录成功日志"""
        self.logger.info(f"✅ {message}")
        
    def log_warning(self, message):
        """记录警告日志"""
        self.logger.warning(f"⚠️ {message}")

    def create_backup_copy(self):
        """创建备份副本"""
        if not self.create_backup:
            self.log_info("跳过备份创建")
            return True
            
        backup_path = get_unique_backup_name(self.work_dir)
        
        self.log_info(f"📋 开始创建备份副本...")
        self.log_info(f"📋 原始目录: {self.work_dir}")
        self.log_info(f"📋 备份目录: {backup_path}")
        
        try:
            shutil.copytree(self.work_dir, backup_path)
            self.log_success(f"备份创建完成: {backup_path}")
            return True
        except Exception as e:
            self.log_error(f"备份创建失败: {str(e)}")
            return False

    def scan_compressed_files(self):
        """初始扫描所有压缩文件（仅用于统计）"""
        self.log_info("🔍 开始初始扫描压缩文件...")
        
        compressed_files = []
        total_size = 0
        
        for root, dirs, files in os.walk(self.work_dir):
            for file in files:
                file_path = Path(root) / file
                file_ext = get_file_extension(file_path)
                
                if file_ext in SUPPORTED_EXTENSIONS:
                    file_size = file_path.stat().st_size
                    compressed_files.append((file_path, file_size))
                    total_size += file_size
                    
                    relative_path = file_path.relative_to(self.work_dir)
                    self.log_info(f"📦 发现压缩文件: {relative_path} ({format_file_size(file_size)})")
        
        self.log_info(f"📊 初始扫描结果:")
        self.log_info(f"   📦 压缩文件总数: {len(compressed_files)} 个")
        self.log_info(f"   📁 压缩文件总大小: {format_file_size(total_size)}")
        
        if not compressed_files:
            self.log_warning("未发现任何支持的压缩文件")
            self.log_info(f"支持的格式: {', '.join(SUPPORTED_EXTENSIONS.keys())}")
        else:
            self.log_info("⚠️ 注意：由于支持嵌套解压，实际处理的文件数量可能更多")
            
        return compressed_files

    def scan_compressed_files_current_round(self):
        """扫描当前轮次的压缩文件"""
        compressed_files = []
        
        for root, dirs, files in os.walk(self.work_dir):
            for file in files:
                file_path = Path(root) / file
                file_ext = get_file_extension(file_path)
                
                if file_ext in SUPPORTED_EXTENSIONS:
                    file_size = file_path.stat().st_size
                    compressed_files.append((file_path, file_size))
                    
                    relative_path = file_path.relative_to(self.work_dir)
                    self.log_info(f"   📦 发现: {relative_path} ({format_file_size(file_size)})")
        
        return compressed_files

    def get_extraction_path(self, archive_path):
        """获取解压目标路径"""
        if self.preserve_structure:
            # 在原位置创建同名文件夹
            return archive_path.parent / archive_path.stem
        else:
            # 在工作目录根部创建文件夹
            return self.work_dir / archive_path.stem

    def extract_single_file(self, archive_path, archive_size):
        """解压单个文件并确保删除原文件"""
        relative_path = archive_path.relative_to(self.work_dir)
        extract_to = self.get_extraction_path(archive_path)
        file_ext = get_file_extension(archive_path)
        
        self.log_info(f"🔄 [{self.stats['processed'] + 1}] 正在处理: {relative_path}")
        self.log_info(f"   📁 文件大小: {format_file_size(archive_size)}")
        self.log_info(f"   📂 目标路径: {extract_to.relative_to(self.work_dir)}")
        
        extraction_success = False
        extracted_count = 0
        
        try:
            # 创建目标目录
            ensure_directory_exists(extract_to)
            
            # 获取对应的解压器
            extractor = get_extractor(file_ext, self.logger)
            extracted_count = extractor.extract(archive_path, extract_to, self.extract_flat)
            
            extraction_success = True
            self.log_success(f"解压成功，提取了 {extracted_count} 个文件/文件夹")
            self.stats['success'] += 1
            self.stats['extracted_files'] += extracted_count
            
        except Exception as e:
            self.log_error(f"   ❌ 解压失败: {str(e)}")
            self.stats['error'] += 1
            
        finally:
            self.stats['processed'] += 1
            
            # 只有在解压成功且用户要求删除原文件时才删除
            if extraction_success and self.delete_original:
                try:
                    # 确保文件存在后再删除
                    if archive_path.exists():
                        archive_path.unlink()
                        self.stats['freed_size'] += archive_size
                        self.log_info(f"   🗑️ 已删除原压缩文件: {relative_path}")
                    else:
                        self.log_warning(f"   ⚠️ 原文件不存在，无法删除: {relative_path}")
                except Exception as delete_error:
                    self.log_error(f"   ❌ 删除原文件失败: {str(delete_error)}")
                    # 删除失败不影响整体成功状态
            
            elif extraction_success and not self.delete_original:
                self.log_info(f"   📦 保留原压缩文件: {relative_path}")
        
        return extraction_success

    def process_all_files(self):
        """处理所有压缩文件（支持嵌套解压）"""
        self.log_info("=" * 60)
        self.log_info("🚀 开始批量解压处理（支持嵌套解压）...")
        
        start_time = time.time()
        round_count = 0
        
        while True:
            round_count += 1
            self.log_info(f"\n🔄 第 {round_count} 轮扫描和解压...")
            
            compressed_files = self.scan_compressed_files_current_round()
            
            if not compressed_files:
                self.log_info("✅ 没有发现更多压缩文件，处理完成")
                break
            
            self.log_info(f"📦 本轮发现 {len(compressed_files)} 个压缩文件")
            
            # 记录本轮处理前的统计
            round_start_success = self.stats['success']
            round_start_error = self.stats['error']
            
            for i, (archive_path, archive_size) in enumerate(compressed_files):
                self.extract_single_file(archive_path, archive_size)
                
                # 添加分隔线
                if i < len(compressed_files) - 1:
                    self.log_info("─" * 30)
            
            # 本轮统计
            round_success = self.stats['success'] - round_start_success
            round_error = self.stats['error'] - round_start_error
            
            self.log_info(f"🎯 第 {round_count} 轮完成: 成功 {round_success} 个, 失败 {round_error} 个")
            
            # 防止无限循环（如果本轮没有成功处理任何文件）
            if round_success == 0:
                self.log_warning("本轮没有成功处理任何文件，停止继续扫描")
                break
                
            # 限制最大轮数，防止异常情况
            if round_count >= MAX_PROCESSING_ROUNDS:
                self.log_warning(f"已达到最大处理轮数({MAX_PROCESSING_ROUNDS})，停止处理")
                break
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # 输出最终统计
        self.log_info("=" * 60)
        self.log_success("所有嵌套解压处理完成！")
        self.log_info(f"📊 最终统计:")
        self.log_info(f"   🔄 处理轮数: {round_count} 轮")
        self.log_info(f"   📦 总处理压缩包: {self.stats['processed']} 个")
        self.log_info(f"   📄 总提取文件: {self.stats['extracted_files']} 个")
        self.log_info(f"   ✅ 成功解压: {self.stats['success']} 个")
        self.log_info(f"   ❌ 处理失败: {self.stats['error']} 个")
        self.log_info(f"   ⏱️ 总耗时: {processing_time:.2f} 秒")
        
        if self.delete_original and self.stats['freed_size'] > 0:
            self.log_info(f"   💾 释放空间: {format_file_size(self.stats['freed_size'])}")

    def run(self):
        """运行主程序"""
        self.log_info("🎯 批量解压缩工具启动")
        self.log_info(f"📁 工作目录: {self.work_dir}")
        self.log_info(f"⚙️ 配置选项:")
        self.log_info(f"   📋 创建备份: {'是' if self.create_backup else '否'}")
        self.log_info(f"   🗑️ 删除原文件: {'是' if self.delete_original else '否'}")
        self.log_info(f"   📂 保持结构: {'是' if self.preserve_structure else '否'}")
        self.log_info(f"   📄 扁平化提取: {'是' if self.extract_flat else '否'}")
        self.log_info(f"   🔤 自动处理乱码: 是")
        
        # 检查工作目录
        if not self.work_dir.exists():
            self.log_error(f"工作目录不存在: {self.work_dir}")
            return False
            
        if not self.work_dir.is_dir():
            self.log_error(f"指定路径不是目录: {self.work_dir}")
            return False
        
        # 创建备份
        if self.create_backup:
            if not self.create_backup_copy():
                self.log_error("备份创建失败，程序终止")
                return False
        
        # 初始扫描（仅用于展示）
        initial_files = self.scan_compressed_files()
        if not initial_files:
            self.log_info("没有发现压缩文件，程序结束")
            return True
        
        # 处理文件（支持嵌套）
        try:
            self.process_all_files()
            return True
        except KeyboardInterrupt:
            self.log_warning("用户中断操作")
            return False
        except Exception as e:
            self.log_error(f"程序执行出错: {str(e)}")
            return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='批量解压缩工具 - 支持嵌套解压和中文文件名处理',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python main.py /path/to/folder                    # 标准模式
  python main.py /path/to/folder --extract-flat     # 扁平化提取
  python main.py /path/to/folder --no-backup        # 不创建备份
  python main.py /path/to/folder --keep-original    # 保留原文件

支持的格式: ZIP, RAR, 7Z, TAR, TAR.GZ, TAR.BZ2, TAR.XZ
        """
    )
    
    parser.add_argument('directory', help='要处理的目录路径')
    parser.add_argument('--no-backup', action='store_true', help='不创建备份')
    parser.add_argument('--keep-original', action='store_true', help='保留原压缩文件')
    parser.add_argument('--flat-structure', action='store_true', help='不保持目录结构')
    parser.add_argument('--extract-flat', action='store_true', help='扁平化提取（只要文件，不要文件夹）')
    
    args = parser.parse_args()
    
    # 检查目录是否存在
    if not Path(args.directory).exists():
        print(f"❌ 错误: 目录不存在 - {args.directory}")
        sys.exit(1)
    
    # 创建解压器实例
    extractor = BatchExtractor(
        work_dir=args.directory,
        create_backup=not args.no_backup,
        delete_original=not args.keep_original,
        preserve_structure=not args.flat_structure,
        extract_flat=args.extract_flat
    )
    
    # 运行处理
    success = extractor.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()