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

import shutil # shutil をインポート

from config import SEVENZ_EXE_PATH as CFG_SEVENZ_EXE_PATH # configからインポート

# 可选依赖检查
# RAR_AVAILABLE は rarfile ではなく 7z.exe の存在で判定するように変更

# まず config から SEVENZ_EXE_PATH を試す
resolved_sevenz_path = None
if CFG_SEVENZ_EXE_PATH and shutil.which(CFG_SEVENZ_EXE_PATH): # 指定があり、かつ実行可能か
    resolved_sevenz_path = CFG_SEVENZ_EXE_PATH
else: # 指定がないか、指定されたパスが見つからない/実行不可の場合、PATHから探す
    resolved_sevenz_path = shutil.which("7z") or shutil.which("7z.exe")

if resolved_sevenz_path:
    RAR_AVAILABLE = True
    SEVENZ_PATH = resolved_sevenz_path # 実際に使用する7zのパス
else:
    RAR_AVAILABLE = False
    SEVENZ_PATH = None

try:
    import py7zr
    SEVENZ_AVAILABLE = True # これはpy7zrライブラリに依存する7z形式の処理用なので残す
                           # もし7z形式も7z.exeで統一するなら、このフラグもSEVENZ_PATHで判定する
except ImportError:
    SEVENZ_AVAILABLE = False


class BaseExtractor:
    """基础解压器类"""
    
    def __init__(self, log_method=None, file_logger=None): # file_logger を追加
        self.log_method = log_method # print のような関数を想定
        self.file_logger = file_logger # ファイル出力用の標準ロガー
        self.extracted_count = 0
    
    def _log(self, message, level="INFO"):
        """Log using the provided log_method."""
        if self.log_method:
            self.log_method(message, level)
        # else: # フォールバックとして print も可能だが、基本は log_method が渡される前提
            # print(f"[{level}] {message}")

    # log_info と log_warning は _log を使うように変更
    def log_info(self, message):
        """记录信息日志"""
        self._log(message, "INFO")
    
    def log_warning(self, message):
        """记录警告日志"""
        # 警告メッセージにプレフィックスは log_method 側で統一されていれば不要
        self._log(message, "WARNING") # BatchExtractor._log がプレフィックスを付ける
    
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
                safe_name = safe_filename(filename, self.file_logger) # self.logger を self.file_logger に変更
                
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
                # self.logger を self.file_logger に変更
                safe_path_parts = [safe_filename(part, self.file_logger) for part in path_parts if part]
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
        member_name_raw = None
        if hasattr(member, 'filename'):  # ZIP
            member_name_raw = member.filename
        elif hasattr(member, 'name'):  # TAR/RAR/7Z
            member_name_raw = member.name
        else:
            member_name_raw = str(member) # フォールバック

        # log_method があればそれを使用 (APIレスポンスとファイルログの両方に出る)
        log_message_initial = f"BaseExtractor._get_member_name: Initial raw member name from library for member {member!r}: {member_name_raw!r} (type: {type(member_name_raw)})"
        if self.log_method:
            self.log_method(log_message_initial, "DEBUG")
        elif self.file_logger:
             self.file_logger.debug(log_message_initial)

        # ZIPファイルでUTF-8フラグが立っていない場合、エンコーディング問題の可能性がある
        # member_name_raw が str 型で、かつそれが誤デコードされた結果かもしれない
        if isinstance(member_name_raw, str) and hasattr(member, 'flag_bits') and not (member.flag_bits & 0x800):
            # member.filename (str) を latin-1 でバイト列に戻し、再デコードを試みる
            # これは、元のバイト列が latin-1 (あるいは他の1バイトエンコーディング) で誤って解釈されたと仮定
            try:
                filename_bytes_candidate = member_name_raw.encode('latin-1')
                log_message_reencode = f"BaseExtractor._get_member_name: ZIP member, non-UTF8 flag. Re-encoded to bytes via latin-1: {filename_bytes_candidate!r}"
                if self.log_method:
                    self.log_method(log_message_reencode, "DEBUG")
                elif self.file_logger:
                    self.file_logger.debug(log_message_reencode)
                # safe_filename にはこのバイト列候補を渡す
                return filename_bytes_candidate
            except Exception as e_reencode:
                log_message_reencode_fail = f"BaseExtractor._get_member_name: Failed to re-encode suspected mis-decoded str via latin-1: {e_reencode}. Proceeding with original str."
                if self.log_method:
                    self.log_method(log_message_reencode_fail, "WARNING")
                elif self.file_logger:
                    self.file_logger.warning(log_message_reencode_fail)
                # 失敗した場合は元の (おそらく文字化けした) 文字列をそのまま返す
                return member_name_raw

        return member_name_raw
    
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
                    def extract_single_zip(member, target_path: Path): # target_path の型ヒント追加
                        ensure_directory_exists(target_path.parent)

                        path_to_open_str = str(target_path)
                        if os.name == 'nt':
                            # resolve() は既に ensure_directory_exists で呼ばれているかもしれないが、念のため
                            # ただし、ファイルパスなので resolve() ではなく abspath() が適切か。
                            # final_path は既に avoid_filename_conflict を通って絶対パスになっている想定。
                            abs_path_str = str(target_path.resolve()) if target_path.is_absolute() else str(Path(os.path.abspath(str(target_path))).resolve())

                            if len(abs_path_str) >= 240 and not abs_path_str.startswith('\\\\?\\'):
                                path_to_open_str = '\\\\?\\' + abs_path_str

                        with zip_ref.open(member) as source, open(path_to_open_str, 'wb') as target:
                            shutil.copyfileobj(source, target)
                    
                    return self.extract_files_flat(members, extract_to, extract_single_zip)
                else:
                    # 保持结构提取
                    def extract_single_zip(member, target_path: Path): # target_path の型ヒント追加
                        ensure_directory_exists(target_path.parent)
                        if not member.is_dir():
                            path_to_open_str = str(target_path)
                            if os.name == 'nt':
                                abs_path_str = str(target_path.resolve()) if target_path.is_absolute() else str(Path(os.path.abspath(str(target_path))).resolve())
                                if len(abs_path_str) >= 240 and not abs_path_str.startswith('\\\\?\\'):
                                    path_to_open_str = '\\\\?\\' + abs_path_str

                            with zip_ref.open(member) as source, open(path_to_open_str, 'wb') as target:
                                shutil.copyfileobj(source, target)
                    
                    return self.extract_files_with_structure(members, extract_to, extract_single_zip)
                
        except zipfile.BadZipFile:
            raise Exception("ZIP文件已损坏或格式不正确")
        except Exception as e:
            raise Exception(f"ZIP解压失败: {str(e)}")


import subprocess # subprocess をインポート

class RarExtractor(BaseExtractor):
    """RAR文件解压器 (7z.exe を使用)"""
    
    def extract(self, archive_path, extract_to, extract_flat=False): # extract_flat は7z.exeでは直接制御しにくい
        """使用7z.exe解压RAR文件"""
        if not RAR_AVAILABLE or not SEVENZ_PATH:
            # このメッセージは実質的に「7z.exeが見つかりません」となる
            raise Exception("7-Zip (7z.exe) not found. Please install 7-Zip and ensure it's in your PATH.")

        archive_path_str = str(archive_path)
        extract_to_str = str(extract_to)

        # 7z.exe のコマンドを構築
        # x: eXtract with full paths (フルパスで展開)
        # -y: Assume Yes on all queries (すべて上書き)
        # -o: Set Output directory (出力先指定。-o とパスの間にスペースなし)
        cmd = [SEVENZ_PATH, 'x', archive_path_str, f'-o{extract_to_str}', '-y']

        # extract_flat の考慮:
        # 7z.exe の 'e' コマンドはフラット展開だが、サブディレクトリ内の同名ファイルは上書きされる可能性がある。
        # 安全のため、'x' で構造通り展開後、必要ならPython側でファイルを移動する方が確実だが、複雑になる。
        # ここでは extract_flat が True の場合、'e' コマンドを使用する試みを行う。
        # ただし、7z.exe 'e' の挙動（特にサブディレクトリの扱い）は注意が必要。
        # BaseExtractorのextract_files_flatのような柔軟な処理は難しい。
        # 今回は extract_flat は無視し、常に構造を保持して展開するか、
        # または 'e' コマンドで試みるが、限定的なサポートとなることを許容する。
        # シンプルにするため、今回は extract_flat を直接サポートせず、常に 'x' を使用する。
        # もし extract_flat が重要な場合は、展開後にPythonでファイルを移動する処理を追加する必要がある。
        if extract_flat:
            self.log_method("RAR extraction with 7z.exe: 'extract_flat' is requested, but 7z.exe 'x' command will preserve structure. For true flat extraction, manual post-processing might be needed or use 'e' command with caution.", "WARNING")
            # 代替として 'e' コマンドを使う場合:
            # cmd = [SEVENZ_PATH, 'e', archive_path_str, f'-o{extract_to_str}', '-y']
            # ただし、この場合 BaseExtractor の extract_files_flat のようなファイルごとの処理はできない。

        self.log_method(f"Attempting to extract RAR (using 7z.exe): {archive_path_str} to {extract_to_str}", "INFO")
        self.log_method(f"Executing command: {' '.join(cmd)}", "DEBUG")

        try:
            process = subprocess.run(cmd, capture_output=True, text=True, check=False, encoding='utf-8', errors='replace')

            if process.stdout:
                self.log_method(f"7z stdout:\n{process.stdout}", "DEBUG")
            if process.stderr:
                # 7zはエラーでなくてもstderrに情報を出すことがある (例: "Everything is Ok")
                # そのため、終了コードも併せて判断する
                self.log_method(f"7z stderr:\n{process.stderr}", "DEBUG" if process.returncode == 0 else "ERROR")

            if process.returncode != 0:
                # エラーコードの詳細は7zのドキュメント参照
                # 1: Warning (non-critical error)
                # 2: Fatal error
                # 7: Command line error
                # 8: Not enough memory
                # 255: User stopped the process
                error_message = f"7z.exe failed with return code {process.returncode}."
                if "password" in process.stderr.lower() or "cannot open encrypted archive" in process.stderr.lower() :
                     error_message = "RAR file seems to be password protected. 7z.exe cannot extract it without a password."
                elif "cannot open file as archive" in process.stderr.lower():
                     error_message = "File is not a valid RAR archive or is corrupted."
                self.log_method(error_message, "ERROR")
                raise Exception(error_message)

            self.log_method(f"RAR file extracted successfully (using 7z.exe): {archive_path_str}", "SUCCESS")
            # extracted_count はアーカイブ単位で1とする。
            # 正確なファイル数を取るには `7z l -ba <archive>` を事前実行しパースする必要がある。
            return 1

        except FileNotFoundError:
            self.log_method(f"7z.exe not found at {SEVENZ_PATH}. Please ensure 7-Zip is installed and in your PATH.", "ERROR")
            raise Exception(f"7z.exe not found at {SEVENZ_PATH}.")
        except subprocess.CalledProcessError as e: # check=True の場合だが、今回はFalseなのでここには来ないはず
            self.log_method(f"7z.exe execution failed: {e.stderr}", "ERROR")
            raise Exception(f"RAR extraction failed using 7z.exe: {e.stderr}")
        except Exception as e:
            self.log_method(f"An unexpected error occurred during RAR extraction with 7z.exe: {str(e)}", "ERROR")
            # raise e # 元の例外をそのまま投げるか、カスタム例外を投げる
            raise Exception(f"RAR extraction failed: {str(e)}")


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
                                extracted_file = final_path.parent / info.filename # これはPathオブジェクト
                                if extracted_file != final_path:
                                    src_path_str = str(extracted_file)
                                    dst_path_str = str(final_path)
                                    if os.name == 'nt':
                                        # shutil.move の src と dst の両方にプレフィックスを試す
                                        abs_src_path_str = str(extracted_file.resolve()) if extracted_file.is_absolute() else str(Path(os.path.abspath(str(extracted_file))).resolve())
                                        abs_dst_path_str = str(final_path.resolve()) if final_path.is_absolute() else str(Path(os.path.abspath(str(final_path))).resolve())

                                        if len(abs_src_path_str) >= 240 and not abs_src_path_str.startswith('\\\\?\\'):
                                            src_path_str = '\\\\?\\' + abs_src_path_str
                                        if len(abs_dst_path_str) >= 240 and not abs_dst_path_str.startswith('\\\\?\\'):
                                            dst_path_str = '\\\\?\\' + abs_dst_path_str

                                    shutil.move(src_path_str, dst_path_str)
                                
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
                    def extract_single_tar(member, target_path: Path): # target_path の型ヒント追加
                        if member.isfile():
                            ensure_directory_exists(target_path.parent)
                            path_to_open_str = str(target_path)
                            if os.name == 'nt':
                                abs_path_str = str(target_path.resolve()) if target_path.is_absolute() else str(Path(os.path.abspath(str(target_path))).resolve())
                                if len(abs_path_str) >= 240 and not abs_path_str.startswith('\\\\?\\'):
                                    path_to_open_str = '\\\\?\\' + abs_path_str
                            with tar_ref.extractfile(member) as source, open(path_to_open_str, 'wb') as target:
                                shutil.copyfileobj(source, target)
                    
                    return self.extract_files_flat(members, extract_to, extract_single_tar)
                else:
                    # 保持结构提取（安全检查）
                    def extract_single_tar(member, target_path: Path): # target_path の型ヒント追加
                        if not (member.name.startswith('/') or '..' in member.name): # 安全チェック
                            if member.isfile():
                                ensure_directory_exists(target_path.parent)
                                path_to_open_str = str(target_path)
                                if os.name == 'nt':
                                    abs_path_str = str(target_path.resolve()) if target_path.is_absolute() else str(Path(os.path.abspath(str(target_path))).resolve())
                                    if len(abs_path_str) >= 240 and not abs_path_str.startswith('\\\\?\\'):
                                        path_to_open_str = '\\\\?\\' + abs_path_str
                                with tar_ref.extractfile(member) as source, open(path_to_open_str, 'wb') as target:
                                    shutil.copyfileobj(source, target)
                    
                    return self.extract_files_with_structure(members, extract_to, extract_single_tar)
                
        except tarfile.TarError:
            raise Exception("TAR文件已损坏或格式不正确")
        except Exception as e:
            raise Exception(f"TAR解压失败: {str(e)}")


# 解压器工厂函数
def get_extractor(file_extension, log_method=None, file_logger=None): # file_logger を追加
    """
    根据文件扩展名获取对应的解压器
    
    Args:
        file_extension: 文件扩展名
        log_method: ログ出力用のメソッド (例: BatchExtractor._log)
        file_logger: ファイル出力用の標準ロガー
        
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
        # log_method と file_logger の両方を渡す
        return extractor_class(log_method=log_method, file_logger=file_logger)
    else:
        raise ValueError(f"不支持的文件格式: {file_extension}")
