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
                
                extract_func(member, current_target_path)
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
                
                extract_func(member, final_path) # extract_func is still synchronous
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
                    
                    # extract_files_flat は async になったので await で呼び出す
                    # extract_to はフラット展開のルートディレクトリを指す必要がある。
                    # BatchExtractor.get_extraction_path が extract_flat=True の場合、
                    # 適切なフラットな展開先 (例: self.work_dir / archive_name) を返す想定。
                    # ここでは extract_to がそのフラットな展開先ディレクトリを指していると仮定。
                    return await self.extract_files_flat(members, extract_to, extract_single_zip)
                else:
                    # 保持结构提取
                    def extract_single_zip(member, target_path: Path): # target_path の型ヒント追加
                        ensure_directory_exists(target_path.parent) # これは同期のままで良い
                        if not member.is_dir():
                            path_to_open_str = str(target_path)
                            if os.name == 'nt':
                                abs_path_str = str(target_path.resolve()) if target_path.is_absolute() else str(Path(os.path.abspath(str(target_path))).resolve())
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


import subprocess # subprocess をインポート
import sys # sys をインポート

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
        if extract_flat:
            # フラット展開の場合、'e' コマンドを使用し、出力先は extract_to をそのまま使用
            # (extract_to は BatchExtractor側でフラットなパスが指定される想定)
            cmd = [SEVENZ_PATH, 'e', archive_path_str, f'-o{extract_to_str}', '-y']
            self.log_method(f"RAR flat extraction with 7z.exe: Files will be extracted to {extract_to_str}. Existing same-name files will be overwritten.", "INFO")
        else:
            # 構造を保持する場合 (既存のロジック)
            cmd = [SEVENZ_PATH, 'x', archive_path_str, f'-o{extract_to_str}', '-y']

        self.log_method(f"Attempting to extract RAR (using 7z.exe): {archive_path_str} to {extract_to_str} (flat={extract_flat})", "INFO")
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
    
    async def extract(self, archive_path, extract_to: Path, extract_flat=False): # async def に変更, extract_to の型ヒント追加
        """解压7Z文件"""
        from utils import get_file_size # ローカルインポート
        if not SEVENZ_AVAILABLE:
            raise Exception("7Z支持未安装，请使用: pip install py7zr")
            
        try:
            # py7zr.SevenZipFile は同期的なので、必要なら to_thread でラップするが、
            # open処理自体はそれほど重くないと仮定。重いのは extract や list。
            with py7zr.SevenZipFile(archive_path, mode='r') as z:
                if await asyncio.to_thread(z.needs_password): # needs_password も同期の可能性
                    raise Exception("7Z文件有密码保护，无法解压")
                
                if extract_flat:
                    processed_in_this_call = 0
                    # z.list() も同期的なので注意。大量ファイルでブロックする可能性。
                    # 理想的にはライブラリが非同期サポートするか、反復処理を to_thread で行う。
                    # ここでは簡略化のため同期的にリスト取得。
                    member_infos = await asyncio.to_thread(z.list)

                    for info in member_infos:
                        if not info.is_dir:
                            filename_part_raw = os.path.basename(info.filename)
                            if not filename_part_raw:
                                if self.log_method: self.log_method(f"  7Z: Could not determine filename from member: {info.filename!r}. Skipping.", "WARNING")
                                continue

                            safe_filename_part = safe_filename(filename_part_raw, self.file_logger)
                            if not safe_filename_part:
                                safe_filename_part = f"unnamed_7z_file_{int(time.time())}"
                                if self.log_method: self.log_method(f"  7Z: Filename became empty after sanitization, using fallback: {safe_filename_part}", "WARNING")

                            current_target_path = extract_to / safe_filename_part

                            if await asyncio.to_thread(current_target_path.exists) and \
                               await asyncio.to_thread(current_target_path.is_file):

                                member_size = info.uncompressed if hasattr(info, 'uncompressed') else getattr(info, 'size', -1)
                                existing_file_size = await get_file_size(current_target_path)

                                log_msg_conflict = (
                                    f"  7Z: File '{safe_filename_part}' already exists. "
                                    f"Member size: {member_size}, Existing size: {existing_file_size}."
                                )
                                if self.log_method: self.log_method(log_msg_conflict, "DEBUG")

                                if member_size != -1 and existing_file_size != -1 and member_size == existing_file_size:
                                    msg = f"  7Z: Skipping (same name and size): {safe_filename_part} (Size: {member_size} bytes)"
                                    if self.log_method: self.log_method(msg, "INFO")
                                    continue
                                else:
                                    renamed_target_path = avoid_filename_conflict(current_target_path)
                                    msg = (
                                        f"  7Z: File '{safe_filename_part}' exists with different size or size unknown. "
                                        f"Renaming to '{renamed_target_path.name}'."
                                    )
                                    if self.log_method: self.log_method(msg, "INFO")
                                    current_target_path = renamed_target_path

                            # 実際の展開処理
                            # z.extract はターゲットファイル名を指定できないため、一度テンポラリな親ディレクトリに展開し、
                            # その後正しい名前で移動する必要がある。
                            # ここでは current_target_path.parent に info.filename という名前で展開されると仮定。
                            # そして shutil.move で current_target_path (リネーム後かもしれない) に移動する。

                            # py7zr の extract メソッドは path にディレクトリを指定する。
                            # targets に展開したいファイル名をリストで渡す。
                            # ここでは、extract_to (フラット展開先のルート) に直接展開させる。
                            # しかし、ファイル名を指定して展開できないため、この方法は使えない。
                            # やはり、一度安全な一時ディレクトリに全展開するか、
                            # または、py7zrのextractの挙動をよく理解して、
                            # 展開後のファイル名が予測できるならそれを使う。
                            # info.filename はアーカイブ内のフルパス。
                            # py7zrは、デフォルトではターゲットパス直下にそのフルパス構造を再現しようとする。
                            # フラット展開のためには、ファイルごとに処理し、メモリ上で展開して書き出すのが理想。

                            # py7zrのドキュメントによると、extractのtargetsで指定したファイルは、
                            # 指定したpathの直下に展開されるのではなく、アーカイブ内のパス構造を一部維持する。
                            # targets=['path/to/file.txt'], path='extract_dir' -> 'extract_dir/path/to/file.txt'
                            # これではフラット展開にならない。

                            # 従って、py7zrでフラット展開と同名ファイル処理を厳密に行うには、
                            # メモリ上でファイル内容を取得し、current_target_pathに書き込む必要がある。
                            # all_files = await asyncio.to_thread(z.read, targets=[info.filename])
                            # if info.filename in all_files:
                            #     content = all_files[info.filename].read() # BytesIO.read() -> bytes
                            #     async with aiofiles.open(current_target_path, 'wb') as f: # aiofiles が必要
                            #         await f.write(content)

                            # aiofilesを使わない同期的な代替 (to_threadでラップ)
                            def write_file_content(p_target_path, p_info_filename):
                                ensure_directory_exists(p_target_path.parent) # Windows長いパス対応のため、自前のensureを使う
                                file_data_map = z.read(targets=[p_info_filename]) # これは同期
                                if p_info_filename in file_data_map:
                                    with open(p_target_path, 'wb') as f_out: # openも長いパス対応が必要
                                        f_out.write(file_data_map[p_info_filename].read())
                                else:
                                    raise FileNotFoundError(f"Content for {p_info_filename} not found in py7zr read result")

                            # Windows長いパス対応のため、open前にパス文字列を加工
                            path_to_open_str = str(current_target_path)
                            if os.name == 'nt':
                                abs_path_str = str(current_target_path.resolve()) if current_target_path.is_absolute() else str(Path(os.path.abspath(str(current_target_path))).resolve())
                                if len(abs_path_str) >= 240 and not abs_path_str.startswith('\\\\?\\'):
                                    path_to_open_str = '\\\\?\\' + abs_path_str

                            # 実際の書き出し処理を to_thread で実行
                            # write_file_content に渡す target_path は Path オブジェクトのままが良いか、
                            # あるいは加工済みの path_to_open_str を渡すか。
                            # write_file_content 内部で open する際に path_to_open_str を使うようにする。
                            # そのためには、write_file_content の引数を調整するか、
                            # open(path_to_open_str, 'wb') を直接 to_thread でラップする。

                            file_data_map_sync = z.read(targets=[info.filename]) # 同期処理
                            if info.filename in file_data_map_sync:
                                content_bytes = file_data_map_sync[info.filename].read()
                                await asyncio.to_thread(ensure_directory_exists, current_target_path.parent)

                                # open と write をまとめて to_thread で実行
                                def sync_write(p_path_str, p_content):
                                    with open(p_path_str, 'wb') as f:
                                        f.write(p_content)
                                await asyncio.to_thread(sync_write, path_to_open_str, content_bytes)

                                processed_in_this_call += 1
                                self.extracted_count +=1 # BaseExtractor の総カウント

                                if processed_in_this_call <= 10:
                                    self.log_info(f"     ├─ Extracted (flat 7z): {current_target_path.name}")
                                elif processed_in_this_call == 11:
                                    self.log_info(f"     ├─ ... (more 7z files extracted flatly)")
                            else:
                                self.log_warning(f"  7Z: Content for {info.filename} not found after z.read(). Skipping.")

                    return processed_in_this_call
                else:
                    # 保持结构提取 (py7zr の extractall は同期)
                    # ensure_directory_exists(extract_to) # extractallがやってくれるはず
                    await asyncio.to_thread(z.extractall, extract_to)
                    # カウントはディレクトリ以外のメンバー数
                    member_infos = await asyncio.to_thread(z.list)
                    return len([info for info in member_infos if not info.is_dir])

        except py7zr.Bad7zFile:
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
                    
                    # extract_files_flat は async になったので await で呼び出す
                    return await self.extract_files_flat(members, extract_to, extract_single_tar)
                else:
                    # 保持结构提取（安全检查）
                    def extract_single_tar(member, target_path: Path): # target_path の型ヒント追加
                        if not (member.name.startswith('/') or '..' in member.name): # 安全チェック
                            if member.isfile():
                                ensure_directory_exists(target_path.parent) # 同期でOK
                                path_to_open_str = str(target_path)
                                if os.name == 'nt':
                                    abs_path_str = str(target_path.resolve()) if target_path.is_absolute() else str(Path(os.path.abspath(str(target_path))).resolve())
                                    if len(abs_path_str) >= 240 and not abs_path_str.startswith('\\\\?\\'):
                                        path_to_open_str = '\\\\?\\' + abs_path_str
                                with tar_ref.extractfile(member) as source, open(path_to_open_str, 'wb') as target:
                                    shutil.copyfileobj(source, target)
                    
                    # extract_files_with_structure も async になったので await で呼び出す
                    return await self.extract_files_with_structure(members, extract_to, extract_single_tar)
                
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
