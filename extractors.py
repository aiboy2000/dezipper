#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解压器模块 - 处理各种压缩格式的解压操作
"""

import os
import shutil # shutil をインポート (重複を削除し、ここに集約)
import zipfile
import tarfile
from pathlib import Path
import asyncio # asyncio をここにインポート
import time # time をインポート
import subprocess # subprocess をインポート
import sys # sys をインポート

from utils import safe_filename, avoid_filename_conflict, ensure_directory_exists, get_file_size
from config import SEVENZ_EXE_PATH as CFG_SEVENZ_EXE_PATH, SUPPORTED_EXTENSIONS # SUPPORTED_EXTENSIONS もここでインポート

# 可选依赖检查
# RAR_AVAILABLE は rarfile ではなく 7z.exe の存在で判定するように変更
resolved_sevenz_path = None
if CFG_SEVENZ_EXE_PATH and shutil.which(CFG_SEVENZ_EXE_PATH):
    resolved_sevenz_path = CFG_SEVENZ_EXE_PATH
else:
    resolved_sevenz_path = shutil.which("7z") or shutil.which("7z.exe")

if resolved_sevenz_path:
    RAR_AVAILABLE = True
    SEVENZ_PATH = resolved_sevenz_path
else:
    RAR_AVAILABLE = False
    SEVENZ_PATH = None

try:
    import py7zr
    SEVENZ_AVAILABLE = True
except ImportError:
    SEVENZ_AVAILABLE = False


class BaseExtractor:
    """基础解压器类"""
    
    def __init__(self, log_method=None, file_logger=None):
        self.log_method = log_method
        self.file_logger = file_logger
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
    
    async def extract_files_flat(self, members, extract_to: Path, extract_func):
        """扁平化提取文件（只要文件，不要文件夹结构），支持同名文件处理"""
        from utils import get_file_size # asyncio.to_thread を使うので get_file_size も async

        processed_in_this_call = 0
        
        for member in members:
            member_name_for_log = "unknown_member"
            try:
                member_name_raw = self._get_member_name(member)
                member_name_for_log = repr(member_name_raw)
                
                is_dir = self._is_directory(member)
                if is_dir:
                    if self.log_method: self.log_method(f"  Skipping directory in flat mode: {member_name_raw!r}", "DEBUG")
                    continue
                
                # 1. _get_member_name から取得した名前をまず safe_filename に通す
                safe_full_member_name = safe_filename(member_name_raw, self.file_logger)
                # 2. その結果からファイル名部分のみを取得
                #    safe_full_member_name が str であることを期待。通常 safe_filename は str を返す。
                filename_only = os.path.basename(str(safe_full_member_name))

                if not filename_only:
                    if self.log_method: self.log_method(f"  Could not determine filename from member: {member_name_raw!r} after sanitization. Skipping.", "WARNING")
                    continue
                
                current_target_path = extract_to / filename_only

                if await asyncio.to_thread(current_target_path.exists) and \
                   await asyncio.to_thread(current_target_path.is_file):

                    member_size = self._get_member_uncompressed_size(member)
                    existing_file_size = await get_file_size(current_target_path)

                    log_msg_conflict = (
                        f"  File '{filename_only}' already exists at target. "
                        f"Member size: {member_size}, Existing file size: {existing_file_size}."
                    )
                    if self.log_method: self.log_method(log_msg_conflict, "DEBUG")
                    # (elif self.file_logger は log_method があれば不要なので削除)

                    if member_size != -1 and existing_file_size != -1 and member_size == existing_file_size:
                        msg = f"  Skipping (same name and size): {filename_only} (Size: {member_size} bytes)"
                        if self.log_method: self.log_method(msg, "INFO")
                        continue
                    else:
                        renamed_target_path = avoid_filename_conflict(current_target_path)
                        msg = (
                            f"  File '{filename_only}' exists with different size or size unknown. "
                            f"Renaming to '{renamed_target_path.name}'."
                        )
                        if self.log_method: self.log_method(msg, "INFO")
                        current_target_path = renamed_target_path
                
                await asyncio.to_thread(extract_func, member, current_target_path)
                self.extracted_count += 1
                processed_in_this_call +=1
                
                if processed_in_this_call <= 10:
                    log_extract_msg = f"     ├─ Extracted (flat): {current_target_path.name}"
                    if self.log_method: self.log_method(log_extract_msg, "INFO")
                elif processed_in_this_call == 11:
                    log_extract_msg_more = f"     ├─ ... (more files extracted flatly in this archive)"
                    if self.log_method: self.log_method(log_extract_msg_more, "INFO")
                
            except Exception as e:
                err_msg = f"Failed to extract member {member_name_for_log} during flat extraction: {str(e)}"
                if self.log_method: self.log_method(err_msg, "WARNING")
                elif self.file_logger: self.file_logger.warning(err_msg)

                if self.file_logger: # エラーの詳細は常にファイルロガーのDEBUGレベルで出す
                    self.file_logger.debug(f"Exception details for member {member_name_for_log} in extract_files_flat:", exc_info=True)
                continue
        
        return processed_in_this_call # この呼び出しで実際に処理したファイル数を返す

    async def extract_files_with_structure(self, members, extract_to: Path, extract_func):
        """按原结构提取文件（处理乱码）"""
        processed_in_this_call = 0
        for member in members:
            member_name_for_log = "unknown_member_struct"
            try:
                member_name_raw = self._get_member_name(member) # Can be str or bytes
                member_name_for_log = repr(member_name_raw)

                # Ensure member_name is str before split, using safe_filename for robust conversion
                # safe_filename handles bytes or str input and returns a sanitized str
                safe_full_member_name = safe_filename(member_name_raw, self.file_logger)

                if not safe_full_member_name:
                    if self.log_method: self.log_method(f"  Filename became empty after safe_filename for member: {member_name_raw!r}. Skipping struct extract.", "WARNING")
                    continue
                
                # Now split the sanitized full name. os.path.normpath might be good too.
                # Path parts should not be re-sanitized individually unless specific reasons.
                parts = str(safe_full_member_name).split('/')
                
                # Filter out empty parts that might result from multiple slashes or leading/trailing slashes
                # after safe_filename (though safe_filename should handle most of this)
                cleaned_parts = [part for part in parts if part and part != '.'] # also remove '.' parts

                if not cleaned_parts:
                    if self.log_method: self.log_method(f"  Path for member {member_name_raw!r} resulted in no valid parts after cleaning. Skipping.", "WARNING")
                    continue

                # Create the final path by joining parts.
                # os.path.join is robust for creating paths.
                # extract_to is the base, and cleaned_parts form the relative path.
                current_relative_path = Path(*cleaned_parts) # Use Path to join parts correctly for the OS
                final_path = extract_to / current_relative_path

                # The extract_func is responsible for creating parent dirs if needed for the final_path
                # ensure_directory_exists(final_path.parent) # This should be handled by extract_func or just before it
                
                await asyncio.to_thread(extract_func, member, final_path) # extract_func is still synchronous
                self.extracted_count += 1
                processed_in_this_call += 1
                
                # Optional: Log first few extractions
                if processed_in_this_call <= 5: # Reduced from 10 for brevity if many files
                    log_extract_msg = f"     ├─ Extracted (structure): {final_path.relative_to(extract_to)}"
                    if self.log_method: self.log_method(log_extract_msg, "INFO")
                elif processed_in_this_call == 6:
                    log_extract_msg_more = f"     ├─ ... (more files extracted with structure in this archive)"
                    if self.log_method: self.log_method(log_extract_msg_more, "INFO")

            except Exception as e:
                err_msg_struct = f"Failed to extract member {member_name_for_log} with structure: {str(e)}"
                if self.log_method: self.log_method(err_msg_struct, "WARNING")

                if self.file_logger:
                    self.file_logger.debug(f"Exception details for member {member_name_for_log} in extract_files_with_structure:", exc_info=True)
                continue
        
        return processed_in_this_call # Return count of items processed in *this call*
    
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
            # 推定される元のエンコーディングでバイト列に戻す試み
            # Windowsの場合は 'mbcs' (システムのANSIコードページ)、その他はファイルシステムエンコーディング
            assumed_original_encoding = 'mbcs' if os.name == 'nt' else sys.getfilesystemencoding()
            try:
                # errors='surrogateescape' を使うことで、変換不能な文字があってもエラーにせず特殊なUnicode文字として保持し、
                # 再度同じエンコーディングでデコードする際に元のバイトに戻せる可能性がある。
                filename_bytes_candidate = member_name_raw.encode(assumed_original_encoding, errors='surrogateescape')

                log_message_reencode = (
                    f"BaseExtractor._get_member_name: ZIP member, non-UTF8 flag. "
                    f"Attempting to re-encode str to bytes using '{assumed_original_encoding}' (with surrogateescape). "
                    f"Original str: {member_name_raw!r}, Candidate bytes: {filename_bytes_candidate!r}"
                )
                if self.log_method: self.log_method(log_message_reencode, "DEBUG")
                elif self.file_logger: self.file_logger.debug(log_message_reencode)

                # safe_filename にはこのバイト列候補を渡す
                return filename_bytes_candidate

            except Exception as e_reencode:
                log_message_reencode_fail = (
                    f"BaseExtractor._get_member_name: Failed to re-encode mis-decoded str via '{assumed_original_encoding}' (surrogateescape): {e_reencode}. "
                    f"Proceeding with original (potentially garbled) str: {member_name_raw!r}"
                )
                if self.log_method: self.log_method(log_message_reencode_fail, "WARNING")
                elif self.file_logger: self.file_logger.warning(log_message_reencode_fail)

                # 失敗した場合は元の (おそらく文字化けした) 文字列をそのまま返す
                return member_name_raw

        return member_name_raw

    def _get_member_uncompressed_size(self, member) -> int:
        """アーカイブメンバーの非圧縮サイズを取得する。取得できない場合は -1 を返す。"""
        # 型アノテーションのためにインポート (ただし、実行時の型チェックが主)
        import zipfile
        import tarfile
        # py7zr と rarfile はオプションなので、hasattr でチェックする

        size = -1 # デフォルトは取得失敗を示す-1
        if isinstance(member, zipfile.ZipInfo):
            size = member.file_size
        elif isinstance(member, tarfile.TarInfo):
            size = member.size
        elif RAR_AVAILABLE and hasattr(member, 'uncompressed_size'): # rarfile使用時 (現在は7z.exeなので通らない)
            size = member.uncompressed_size
        elif SEVENZ_AVAILABLE and hasattr(member, 'uncompressed'): # py7zr使用時
             size = member.uncompressed
        # 7z.exe経由のRarExtractorの場合は、このメソッドは呼ばれるが、memberオブジェクトが
        # subprocessの結果ではないため、上記条件に合致せず -1 を返すことになる。
        # (これは意図した動作：7z.exeでは個々のメンバーサイズを事前に知るのが難しい)

        if self.log_method:
            self.log_method(f"BaseExtractor._get_member_uncompressed_size: Member {getattr(member, 'name', str(member))}, Uncompressed size: {size}", "DEBUG")
        elif self.file_logger:
            self.file_logger.debug(f"BaseExtractor._get_member_uncompressed_size: Member {getattr(member, 'name', str(member))}, Uncompressed size: {size}")
        return size

    def _is_directory(self, member):
        """判断成员是否为目录"""
        if hasattr(member, 'is_dir'):  # ZIP
            return member.is_dir()
        elif hasattr(member, 'isdir'):  # TAR
            return member.isdir()
        else:
            # 简单判断：以/结尾的视为目录
            # 注意: RarExtractor (7z.exe使用時) や SevenZipExtractor (py7zr不使用時) では
            # member オブジェクトの型が異なるため、この判定は必ずしも正しくない可能性がある。
            # 各Extractorで必要ならオーバーライドするか、より堅牢な判定が必要。
            # ただし、extract_files_flatでは主にファイルのみを処理するため、影響は限定的。
            name_to_check = self._get_member_name(member) # _get_member_name can return bytes
            if isinstance(name_to_check, bytes):
                try:
                    name_to_check = name_to_check.decode('utf-8', 'surrogateescape')
                except Exception: # Fallback if any error during decode
                    name_to_check = "" # Avoid error in endswith if decode fails badly
            return name_to_check.endswith('/')


class ZipExtractor(BaseExtractor):
    """ZIP文件解压器"""
    
    async def extract(self, archive_path, extract_to: Path, extract_flat=False):
        """解压ZIP文件"""
        try:
            # zipfile.ZipFile is sync, consider to_thread if it blocks for too long on open
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                # 检查是否有密码保护
                try:
                    # testzip can be I/O bound
                    await asyncio.to_thread(zip_ref.testzip)
                except RuntimeError as e:
                    if "Bad password" in str(e) or "password required" in str(e):
                        raise Exception("文件有密码保护，无法解压")
                    raise e
                
                members = zip_ref.infolist() # This is sync
                
                if extract_flat:
                    # 扁平化提取
                    def extract_single_zip(member, target_path_cb: Path): # Renamed to avoid confusion
                        ensure_directory_exists(target_path_cb.parent)
                        path_to_open_str = str(target_path_cb)
                        if os.name == 'nt':
                            # resolve() は既に ensure_directory_exists で呼ばれているかもしれないが、念のため
                            # ただし、ファイルパスなので resolve() ではなく abspath() が適切か。
                            # final_path は既に avoid_filename_conflict を通って絶対パスになっている想定。
                            abs_path_str = str(target_path_cb.resolve()) if target_path_cb.is_absolute() else str(Path(os.path.abspath(str(target_path_cb))).resolve())

                            if len(abs_path_str) >= 240 and not abs_path_str.startswith('\\\\?\\'):
                                path_to_open_str = '\\\\?\\' + abs_path_str

                        # zip_ref.open and shutil.copyfileobj are sync
                        # This whole callback runs in the main thread if extract_files_flat isn't careful,
                        # or in a thread if extract_func itself is wrapped in to_thread by the caller.
                        # For simplicity, assuming extract_func is called in a way that allows blocking IO for now.
                        with zip_ref.open(member) as source, open(path_to_open_str, 'wb') as target:
                            shutil.copyfileobj(source, target)
                    
                    # extract_files_flat は async になったので await で呼び出す
                    # extract_to はフラット展開のルートディレクトリを指す必要がある。
                    # BatchExtractor.get_extraction_path が extract_flat=True の場合、
                    # 適切なフラットな展開先 (例: self.work_dir / archive_name) を返す想定。
                    # ここでは extract_to がそのフラットな展開先ディレクトリを指していると仮定。
                    return await self.extract_files_flat(members, extract_to, extract_single_zip)
                else:
                    # 保持结构提取
                    def extract_single_zip(member, target_path_cb: Path):
                        ensure_directory_exists(target_path_cb.parent) # これは同期のままで良い
                        if not member.is_dir(): # member.is_dir() is sync
                            path_to_open_str = str(target_path_cb)
                            if os.name == 'nt':
                                abs_path_str = str(target_path_cb.resolve()) if target_path_cb.is_absolute() else str(Path(os.path.abspath(str(target_path_cb))).resolve())
                                if len(abs_path_str) >= 240 and not abs_path_str.startswith('\\\\?\\'):
                                    path_to_open_str = '\\\\?\\' + abs_path_str

                            with zip_ref.open(member) as source, open(path_to_open_str, 'wb') as target:
                                shutil.copyfileobj(source, target)
                    
                    # extract_files_with_structure も async になったので await で呼び出す
                    return await self.extract_files_with_structure(members, extract_to, extract_single_zip)
                
        except zipfile.BadZipFile:
            raise Exception("ZIP文件已损坏或格式不正确")
        except Exception as e:
            raise Exception(f"ZIP解压失败: {str(e)}")

class RarExtractor(BaseExtractor):
    """RAR文件解压器 (7z.exe を使用)"""
    
    def extract(self, archive_path, extract_to: Path, extract_flat=False): # async を削除し、同期メソッドに戻す
        """使用7z.exe解压RAR文件"""
        # このメソッドは subprocess.run を使うので、元々ブロッキング。
        # 呼び出し側 (api.py) で asyncio.to_thread を使って非同期化するのが正しい。
        if not RAR_AVAILABLE or not SEVENZ_PATH:
            raise Exception("7-Zip (7z.exe) not found. Please install 7-Zip and ensure it's in your PATH.")

        archive_path_str = str(archive_path)
        extract_to_str = str(extract_to)

        if extract_flat:
            cmd = [SEVENZ_PATH, 'e', archive_path_str, f'-o{extract_to_str}', '-y']
            self.log_method(f"RAR flat extraction with 7z.exe: Files will be extracted to {extract_to_str}. Existing same-name files will be overwritten.", "INFO")
        else:
            cmd = [SEVENZ_PATH, 'x', archive_path_str, f'-o{extract_to_str}', '-y']

        self.log_method(f"Attempting to extract RAR (using 7z.exe): {archive_path_str} to {extract_to_str} (flat={extract_flat})", "INFO")
        self.log_method(f"Executing command: {' '.join(cmd)}", "DEBUG")

        try:
            # subprocess.run is sync, run in thread
            process = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, check=False,
                encoding='utf-8', errors='replace'
            )

            if process.stdout:
                self.log_method(f"7z stdout:\n{process.stdout}", "DEBUG")
            if process.stderr:
                self.log_method(f"7z stderr:\n{process.stderr}", "DEBUG" if process.returncode == 0 else "ERROR")

            if process.returncode != 0:
                error_message = f"7z.exe failed with return code {process.returncode}."
                if "password" in process.stderr.lower() or "cannot open encrypted archive" in process.stderr.lower() :
                     error_message = "RAR file seems to be password protected. 7z.exe cannot extract it without a password."
                elif "cannot open file as archive" in process.stderr.lower():
                     error_message = "File is not a valid RAR archive or is corrupted."
                self.log_method(error_message, "ERROR")
                raise Exception(error_message)

            self.log_method(f"RAR file extracted successfully (using 7z.exe): {archive_path_str}", "SUCCESS")
            return 1

        except FileNotFoundError:
            self.log_method(f"7z.exe not found at {SEVENZ_PATH}. Please ensure 7-Zip is installed and in your PATH.", "ERROR")
            raise Exception(f"7z.exe not found at {SEVENZ_PATH}.")
        except Exception as e:
            self.log_method(f"An unexpected error occurred during RAR extraction with 7z.exe: {str(e)}", "ERROR")
            raise Exception(f"RAR extraction failed: {str(e)}")


class SevenZipExtractor(BaseExtractor):
    """7Z文件解压器"""
    
    async def extract(self, archive_path, extract_to: Path, extract_flat=False):
        """解压7Z文件"""
        if not SEVENZ_AVAILABLE: # This refers to py7zr library
            # TODO: Consider falling back to 7z.exe if py7zr is not available but SEVENZ_PATH is set.
            # For now, stick to py7zr if SEVENZ_AVAILABLE is True.
            raise Exception("py7zr library not installed. Please use: pip install py7zr")
            
        try:
            # py7zr operations are mostly synchronous.
            async def do_extract_flat_py7zr():
                processed_count = 0
                # Opening the archive
                with py7zr.SevenZipFile(archive_path, mode='r') as z_sync:
                    if z_sync.needs_password():
                        raise Exception("7Z文件有密码保护，无法解压 (py7zr)")
                    member_infos_sync = z_sync.list()

                # Process members
                for info in member_infos_sync:
                    if not info.is_dir:
                        filename_part_raw = os.path.basename(info.filename)
                        if not filename_part_raw:
                            if self.log_method: self.log_method(f"  7Z: Could not determine filename from member: {info.filename!r}. Skipping.", "WARNING")
                            continue

                        safe_filename_part = safe_filename(filename_part_raw, self.file_logger)
                        if not safe_filename_part:
                            safe_filename_part = f"unnamed_7z_file_{int(time.time())}"
                            if self.log_method: self.log_method(f"  7Z: Filename became empty, using fallback: {safe_filename_part}", "WARNING")

                        current_target_path = extract_to / safe_filename_part

                        if await asyncio.to_thread(current_target_path.exists) and \
                           await asyncio.to_thread(current_target_path.is_file):
                            member_size = info.uncompressed if hasattr(info, 'uncompressed') else getattr(info, 'size', -1)
                            existing_file_size = await get_file_size(current_target_path)

                            if member_size != -1 and existing_file_size != -1 and member_size == existing_file_size:
                                if self.log_method: self.log_method(f"  7Z: Skipping (same name/size): {safe_filename_part}", "INFO")
                                continue
                            else:
                                renamed_target_path = avoid_filename_conflict(current_target_path)
                                if self.log_method: self.log_method(f"  7Z: Renaming '{safe_filename_part}' to '{renamed_target_path.name}'", "INFO")
                                current_target_path = renamed_target_path

                        path_to_open_str = str(current_target_path)
                        if os.name == 'nt':
                            abs_path_str = str(current_target_path.resolve()) if current_target_path.is_absolute() else str(Path(os.path.abspath(str(current_target_path))).resolve())
                            if len(abs_path_str) >= 240 and not abs_path_str.startswith('\\\\?\\'):
                                path_to_open_str = '\\\\?\\' + abs_path_str

                        # Re-open for z.read to avoid issues with shared file handle across threads if any
                        with py7zr.SevenZipFile(archive_path, mode='r') as z_read_sync:
                             file_data_map_sync = z_read_sync.read(targets=[info.filename])

                        if info.filename in file_data_map_sync:
                            content_bytes = file_data_map_sync[info.filename].read()
                            await asyncio.to_thread(ensure_directory_exists, current_target_path.parent)

                            def sync_write_7z(p_path_str, p_content):
                                with open(p_path_str, 'wb') as f:
                                    f.write(p_content)
                            await asyncio.to_thread(sync_write_7z, path_to_open_str, content_bytes)

                            processed_count += 1
                            self.extracted_count +=1

                            if processed_count <= 10:
                                self.log_info(f"     ├─ Extracted (flat 7z): {current_target_path.name}")
                            elif processed_count == 11:
                                self.log_info(f"     ├─ ... (more 7z files extracted flatly)")
                        else:
                            self.log_warning(f"  7Z: Content for {info.filename} not found after z.read(). Skipping.")
                return processed_count

            async def do_extract_all_py7zr():
                # This inner function is still largely synchronous due to py7zr's nature
                with py7zr.SevenZipFile(archive_path, mode='r') as z_sync:
                    if z_sync.needs_password(): # This is a property access, likely quick
                        raise Exception("7Z文件有密码保护，无法解压 (py7zr)")
                    # extractall can be very I/O bound and block
                    z_sync.extractall(path=extract_to)
                    member_infos_sync = z_sync.list() # Also potentially blocking if archive is large
                    return len([info for info in member_infos_sync if not info.is_dir])

            if extract_flat:
                return await do_extract_flat_py7zr()
            else:
                # Wrap the call to the synchronous part in to_thread
                # The original do_extract_all_py7zr itself contains synchronous blocking calls.
                # So, we run the entire helper in a thread.
                return await asyncio.to_thread(do_extract_all_py7zr)
                
        except py7zr.Bad7zFile:
            raise Exception("7Z文件已损坏或格式不正确")
        except Exception as e:
            raise Exception(f"7Z解压失败: {str(e)}")


class TarExtractor(BaseExtractor):
    """TAR系列文件解压器"""
    
    async def extract(self, archive_path, extract_to: Path, extract_flat=False): # Made async
        """解压TAR系列文件"""
        try:
            # tarfile.open is sync
            with tarfile.open(archive_path, 'r:*') as tar_ref:
                members = tar_ref.getmembers() # sync
                
                if extract_flat:
                    def extract_single_tar(member, target_path_cb: Path):
                        if member.isfile(): # sync
                            ensure_directory_exists(target_path_cb.parent) # sync
                            path_to_open_str = str(target_path_cb)
                            if os.name == 'nt':
                                abs_path_str = str(target_path_cb.resolve()) if target_path_cb.is_absolute() else str(Path(os.path.abspath(str(target_path_cb))).resolve())
                                if len(abs_path_str) >= 240 and not abs_path_str.startswith('\\\\?\\'):
                                    path_to_open_str = '\\\\?\\' + abs_path_str
                            # tar_ref.extractfile and shutil.copyfileobj are sync
                            with tar_ref.extractfile(member) as source, open(path_to_open_str, 'wb') as target:
                                shutil.copyfileobj(source, target)
                    
                    return await self.extract_files_flat(members, extract_to, extract_single_tar)
                else:
                    def extract_single_tar(member, target_path_cb: Path):
                        if not (member.name.startswith('/') or '..' in member.name):
                            if member.isfile():
                                ensure_directory_exists(target_path_cb.parent)
                                path_to_open_str = str(target_path_cb)
                                if os.name == 'nt':
                                    abs_path_str = str(target_path_cb.resolve()) if target_path_cb.is_absolute() else str(Path(os.path.abspath(str(target_path_cb))).resolve())
                                    if len(abs_path_str) >= 240 and not abs_path_str.startswith('\\\\?\\'):
                                        path_to_open_str = '\\\\?\\' + abs_path_str
                                with tar_ref.extractfile(member) as source, open(path_to_open_str, 'wb') as target:
                                    shutil.copyfileobj(source, target)
                    
                    return await self.extract_files_with_structure(members, extract_to, extract_single_tar)
                
        except tarfile.TarError:
            raise Exception("TAR文件已损坏或格式不正确")
        except Exception as e:
            raise Exception(f"TAR解压失败: {str(e)}")


# 解压器工厂函数
def get_extractor(file_extension, log_method=None, file_logger=None):
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
        return extractor_class(log_method=log_method, file_logger=file_logger)
    else:
        raise ValueError(f"不支持的文件格式: {file_extension}")
