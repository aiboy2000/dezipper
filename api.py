from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio
import os
from pathlib import Path

import logging
import sys
import shutil
import time
from datetime import datetime

from config import (
    SUPPORTED_EXTENSIONS, MAX_PROCESSING_ROUNDS,
    LOG_FORMAT, LOG_FILENAME_FORMAT, STATS_FIELDS
)
from utils import (
    format_file_size, get_file_extension,
    get_unique_backup_name, ensure_directory_exists,
    avoid_filename_conflict_timestamp # Added import
)
from extractors import get_extractor, RAR_AVAILABLE, SEVENZ_AVAILABLE


class BatchExtractor:
    """批量解压缩工具主类"""

    def __init__(self, work_dir, create_backup=True, delete_original=True,
                 preserve_structure=True, extract_flat=False, request_id: str = "api_request"):
        self.work_dir = Path(work_dir)
        self.create_backup = create_backup
        self.delete_original = delete_original
        self.preserve_structure = preserve_structure
        self.extract_flat = extract_flat
        self.request_id = request_id # APIリクエストごとのログ識別用

        self.logs = []  # APIレスポンス用のログリスト
        self.stats = {field: 0 for field in STATS_FIELDS}

        # 標準のロガーもセットアップ (ファイル出力用)
        self.logger = self._setup_file_logger()

    def _setup_file_logger(self):
        """ファイル出力用のロガーをセットアップ"""
        logger = logging.getLogger(f"BatchExtractor_{self.request_id}")
        logger.setLevel(logging.DEBUG) # INFO から DEBUG に変更

        # Avoid adding handlers multiple times if logger already configured
        if not logger.handlers:
            # ファイルハンドラ
            log_dir = self.work_dir / "batch_extractor_logs"
            ensure_directory_exists(log_dir)
            log_filename = datetime.now().strftime(LOG_FILENAME_FORMAT.replace("batch_extractor", f"batch_extractor_{self.request_id}"))
            log_path = log_dir / log_filename

            fh = logging.FileHandler(log_path, encoding='utf-8')
            fh.setFormatter(logging.Formatter(LOG_FORMAT))
            logger.addHandler(fh)

            # API呼び出しの場合はコンソール出力は任意 (FastAPIのログと重複する可能性)
            # ch = logging.StreamHandler(sys.stdout)
            # ch.setFormatter(logging.Formatter(LOG_FORMAT))
            # logger.addHandler(ch)
        return logger

    def _log(self, message, level="INFO"):
        """ログを内部リストと標準ロガーの両方に出力"""
        log_entry = f"[{level}] {message}"
        self.logs.append(log_entry)

        if level == "INFO":
            self.logger.info(message)
        elif level == "ERROR":
            self.logger.error(message)
        elif level == "WARNING":
            self.logger.warning(message)
        elif level == "SUCCESS": # カスタムレベル的な使い方
            self.logger.info(f"✅ {message}")
        else:
            self.logger.debug(message)


    async def create_backup_copy_async(self):
        """非同期でバックアップを作成"""
        if not self.create_backup:
            self._log("Skipping backup creation", "INFO")
            return True

        backup_path = get_unique_backup_name(self.work_dir)

        self._log(f"Creating backup copy...", "INFO")
        self._log(f"Original directory: {self.work_dir}", "INFO")
        self._log(f"Backup directory: {backup_path}", "INFO")

        try:
            # shutil.copytree は同期的なので asyncio.to_thread を使用
            await asyncio.to_thread(shutil.copytree, self.work_dir, backup_path, dirs_exist_ok=True)
            self._log(f"Backup created successfully: {backup_path}", "SUCCESS")
            return True
        except Exception as e:
            self._log(f"Backup creation failed: {str(e)}", "ERROR")
            return False

    async def scan_compressed_files_async(self, initial_scan=True):
        """非同期で圧縮ファイルをスキャン"""
        if initial_scan:
            self._log("Starting initial scan for compressed files...", "INFO")

        compressed_files = []
        total_size = 0

        # os.walk は同期的だが、ここではPath.rglobを使用してみる (よりPythonic)
        # for root, dirs, files in os.walk(self.work_dir):
        #     for file in files:
        #         file_path = Path(root) / file
        #         # ... (以下同様)

        # Path.rglob を使用 (ジェネレータなのでメモリ効率が良い)
        for file_path in self.work_dir.rglob('*'):
            if file_path.is_file():
                file_ext = get_file_extension(file_path)
                if file_ext in SUPPORTED_EXTENSIONS:
                    try:
                        file_size = await asyncio.to_thread(file_path.stat)
                        file_size = file_size.st_size
                        compressed_files.append((file_path, file_size))
                        if initial_scan: # 初回スキャン時のみ全ファイルサイズを合計
                             total_size += file_size

                        relative_path = file_path.relative_to(self.work_dir)
                        self._log(f"Found compressed file: {relative_path} ({format_file_size(file_size)})", "INFO")
                    except Exception as e:
                        self._log(f"Could not stat file {file_path}: {e}", "WARNING")


        if initial_scan:
            self._log(f"Initial scan results:", "INFO")
            self._log(f"  Total compressed files found: {len(compressed_files)}", "INFO")
            self._log(f"  Total size of compressed files: {format_file_size(total_size)}", "INFO")
            if not compressed_files:
                self._log("No supported compressed files found.", "WARNING")
                self._log(f"Supported formats: {', '.join(SUPPORTED_EXTENSIONS.keys())}", "INFO")
            else:
                self._log("Note: Due to nested extraction, the actual number of processed files may be higher.", "WARNING")

        return compressed_files

    def get_extraction_path(self, archive_path):
        """解压目标路径 (変更なし)"""
        if self.preserve_structure:
            return archive_path.parent / archive_path.stem
        else:
            return self.work_dir / archive_path.stem

    async def extract_single_file_async(self, archive_path, archive_size):
        """非同期で単一ファイルを解凍"""
        relative_path = archive_path.relative_to(self.work_dir)
        extract_to = self.get_extraction_path(archive_path)
        file_ext = get_file_extension(archive_path)

        self._log(f"Processing [{self.stats['processed'] + 1}]: {relative_path}", "INFO")
        self._log(f"  File size: {format_file_size(archive_size)}", "INFO")
        self._log(f"  Target path: {extract_to.relative_to(self.work_dir)}", "INFO")

        extraction_success = False
        extracted_count = 0

        try:
            await asyncio.to_thread(ensure_directory_exists, extract_to)

            # get_extractor は同期的だが、Extractorのメソッドを非同期対応にするか、
            # to_threadでラップする
            # logger を self._log メソッドに変更し、file_logger として self.logger を渡す
            extractor_instance = get_extractor(file_ext, log_method=self._log, file_logger=self.logger)

            extracted_items_count = 0 # 初期化
            # RarExtractor.extract は同期メソッド、他は async def になっている
            if file_ext == '.rar': # RarExtractor の場合 (SEVENZ_PATH を使う)
                extracted_items_count = await asyncio.to_thread(
                    extractor_instance.extract,
                    archive_path,
                    extract_to,
                    self.extract_flat
                )
            else: # ZipExtractor, TarExtractor, SevenZipExtractor (py7zr) の場合
                extracted_items_count = await extractor_instance.extract(
                    archive_path,
                    extract_to,
                    self.extract_flat
                )

            extraction_success = True
            # ログメッセージで extracted_items_count を使用
            self._log(f"Extraction successful, {extracted_items_count} files/folders reported by extractor.", "SUCCESS")
            self.stats['success'] += 1
            # self.stats['extracted_files'] は元々 Extractor が報告するアイテム数だったので、これに加算
            self.stats['extracted_files'] += extracted_items_count

        except Exception as e:
            # エラーログの改善: どのファイルで失敗したかわかるように archive_path を含める
            self._log(f"  Extraction failed for {archive_path.name}: {str(e)}", "ERROR")
            self.stats['error'] += 1

        finally:
            self.stats['processed'] += 1
            # Moved archive deletion logic after flattening

        if extraction_success:
            # Call flatten operation here, using extract_to as the folder to flatten
            # extract_to is the directory where files were initially extracted (e.g., work_dir/archive_stem)
            await self._flatten_extraction_result_async(extract_to)

            # Now handle original archive deletion after successful extraction and flattening
            if self.delete_original:
                try:
                    if await asyncio.to_thread(archive_path.exists):
                        await asyncio.to_thread(archive_path.unlink)
                        self.stats['freed_size'] += archive_size
                        self._log(f"  Deleted original archive: {relative_path}", "INFO")
                    else:
                        self._log(f"  Original file not found, cannot delete: {relative_path}", "WARNING")
                except Exception as delete_error:
                    self._log(f"  Failed to delete original file: {str(delete_error)}", "ERROR")
            else: # not self.delete_original
                self._log(f"  Kept original archive: {relative_path}", "INFO")

        return extraction_success

    async def process_all_files_async(self):
        """非同期ですべての圧縮ファイルを処理 (ネスト対応)"""
        self._log("=" * 60, "INFO")
        self._log("Starting batch extraction (supports nested archives)...", "INFO")

        start_time = time.time()
        round_count = 0

        while True:
            round_count += 1
            self._log(f"\nRound {round_count} scanning and extraction...", "INFO")

            # スキャンを非同期に
            compressed_files_this_round = await self.scan_compressed_files_async(initial_scan=False)

            if not compressed_files_this_round:
                self._log("No more compressed files found, processing complete.", "SUCCESS")
                break

            self._log(f"Found {len(compressed_files_this_round)} compressed files in this round.", "INFO")

            round_start_success = self.stats['success']

            for i, (archive_path, archive_size) in enumerate(compressed_files_this_round):
                await self.extract_single_file_async(archive_path, archive_size)
                if i < len(compressed_files_this_round) - 1:
                    self._log("─" * 30, "INFO")

            round_success_count = self.stats['success'] - round_start_success
            if round_success_count == 0 and compressed_files_this_round: # ファイルが見つかったのに何も成功しなかった場合
                self._log("No files were successfully processed in this round, stopping to prevent infinite loop.", "WARNING")
                break

            if round_count >= MAX_PROCESSING_ROUNDS:
                self._log(f"Reached maximum processing rounds ({MAX_PROCESSING_ROUNDS}), stopping.", "WARNING")
                break

        end_time = time.time()
        processing_time = end_time - start_time

        self._log("=" * 60, "INFO")
        self._log("All nested extraction processing finished!", "SUCCESS")
        self._log(f"Final Statistics:", "INFO")
        self._log(f"  Processing rounds: {round_count}", "INFO")
        self._log(f"  Total archives processed: {self.stats['processed']}", "INFO")
        self._log(f"  Total files extracted: {self.stats['extracted_files']}", "INFO") # This counts items reported by extractor
        self._log(f"  Successfully extracted: {self.stats['success']}", "INFO")
        self._log(f"  Failed to extract: {self.stats['error']}", "INFO")
        self._log(f"  Total time: {processing_time:.2f} seconds", "INFO")

        if self.delete_original and self.stats['freed_size'] > 0:
            self._log(f"  Space freed: {format_file_size(self.stats['freed_size'])} by deleting archives", "INFO")

        # The _collect_final_stats will now count files in work_dir,
        # which after flattening, should represent the true final state.
        try:
            actual_files, actual_folders = await self._collect_final_stats(self.work_dir)
            self.stats['total_extracted_actual_files'] = actual_files
            self.stats['total_extracted_folders'] = actual_folders # This will be 0 or low if flattening works
            self._log(f"  Final actual files count in work_dir: {actual_files}", "INFO")
            self._log(f"  Final folders count in work_dir: {actual_folders}", "INFO")
        except Exception as e_stats:
            self._log(f"Error collecting final stats: {e_stats}", "ERROR")
            self.stats.setdefault('total_extracted_actual_files', -1)
            self.stats.setdefault('total_extracted_folders', -1)

    async def _flatten_extraction_result_async(self, result_folder_path: Path):
        """
        Moves all files from result_folder_path (and its subdirectories)
        directly into self.work_dir, handling name conflicts with timestamps.
        Then deletes the result_folder_path.
        """
        self._log(f"Flattening results from: {result_folder_path.relative_to(self.work_dir)}", "INFO")
        moved_files_count = 0

        # Collect all files first to avoid issues if modifying while iterating rglob directly
        # Ensure paths are absolute for robust operations
        files_to_move = []
        if await asyncio.to_thread(result_folder_path.exists) and await asyncio.to_thread(result_folder_path.is_dir):
            for item_path in result_folder_path.rglob('*'):
                if await asyncio.to_thread(item_path.is_file):
                    files_to_move.append(item_path)
        else:
            self._log(f"  Result folder {result_folder_path.name} does not exist or is not a directory. Skipping flattening.", "WARNING")
            return

        if not files_to_move:
            self._log(f"  No files found within {result_folder_path.name} to move.", "INFO")

        for src_file_path in files_to_move:
            try:
                target_filename = src_file_path.name
                dest_path_in_work_dir = self.work_dir / target_filename

                # Handle potential name conflicts in the work_dir
                # The avoid_filename_conflict_timestamp function is synchronous, wrap it
                final_dest_path = await asyncio.to_thread(avoid_filename_conflict_timestamp, dest_path_in_work_dir)

                if final_dest_path != dest_path_in_work_dir:
                    self._log(f"  Name conflict for {target_filename}. Renaming to {final_dest_path.name} in work_dir.", "INFO")

                # Move the file (shutil.move is synchronous)
                await asyncio.to_thread(shutil.move, str(src_file_path), str(final_dest_path))
                moved_files_count += 1
                self._log(f"  Moved: {src_file_path.relative_to(result_folder_path)} -> {final_dest_path.relative_to(self.work_dir)}", "DEBUG")
            except Exception as e:
                self._log(f"  Error moving file {src_file_path.name}: {str(e)}", "ERROR")
                self.logger.debug(f"Exception details for moving {src_file_path.name}:", exc_info=True)


        self._log(f"Moved {moved_files_count} files from {result_folder_path.name} to {self.work_dir.name}.", "INFO")

        # Delete the original result_folder_path
        if await asyncio.to_thread(result_folder_path.exists) and result_folder_path != self.work_dir : # Ensure not deleting work_dir itself
            try:
                self._log(f"Deleting original extraction folder: {result_folder_path.name}", "INFO")
                await asyncio.to_thread(shutil.rmtree, result_folder_path)
                self._log(f"  Successfully deleted folder: {result_folder_path.name}", "SUCCESS")
            except Exception as e:
                self._log(f"  Error deleting folder {result_folder_path.name}: {str(e)}", "ERROR")
                self.logger.debug(f"Exception details for deleting {result_folder_path.name}:", exc_info=True)
        elif result_folder_path == self.work_dir:
             self._log(f"  Skipping deletion of result folder as it is the working directory itself: {result_folder_path.name}", "WARNING")


    async def run(self):
        """主処理を非同期で実行"""
        self._log("Batch Extractor starting...", "INFO")
        self._log(f"Working directory: {self.work_dir}", "INFO")
        self._log(f"Options: Backup={self.create_backup}, DeleteOriginal={self.delete_original}, PreserveStructure={self.preserve_structure}, ExtractFlat={self.extract_flat}", "INFO")

        if not await asyncio.to_thread(self.work_dir.exists):
            self._log(f"Work directory does not exist: {self.work_dir}", "ERROR")
            self.stats['error'] +=1
            return False, "Work directory does not exist."
        if not await asyncio.to_thread(self.work_dir.is_dir):
            self._log(f"Specified path is not a directory: {self.work_dir}", "ERROR")
            self.stats['error'] +=1
            return False, "Specified path is not a directory."

        if self.create_backup:
            if not await self.create_backup_copy_async():
                self._log("Backup creation failed, stopping.", "ERROR")
                # self.stats['error'] +=1 # create_backup_copy_async内で記録済み
                return False, "Backup creation failed."

        initial_files = await self.scan_compressed_files_async(initial_scan=True)
        if not initial_files:
            self._log("No compressed files found to process.", "INFO")
            return True, "No compressed files found." # 処理するファイルがないのはエラーではない

        try:
            await self.process_all_files_async()
            return True, "Extraction process completed."
        except KeyboardInterrupt:
            self._log("User interrupted the operation.", "WARNING")
            return False, "Operation interrupted by user."
        except Exception as e:
            self._log(f"An error occurred during execution: {str(e)}", "ERROR")
            # スタックトレースをファイルログに出力したい場合
            self.logger.exception("Detailed error during execution:")
            return False, f"An unexpected error occurred: {str(e)}"

    async def _collect_final_stats(self, scan_root_path: Path) -> tuple[int, int]:
        """
        指定されたパス内の実際のファイル数（圧縮ファイルを除く）とフォルダ数を収集します。
        """
        actual_files_count = 0
        folders_count = 0
        self._log(f"Starting final stats collection in: {scan_root_path}", "DEBUG")

        # Path.rglob は非同期ではないため、全体を to_thread でラップするか、
        # 個々の is_file/is_dir 呼び出しをラップするか。
        # アイテム数が非常に多い場合を考慮し、rglob自体はメインスレッドで実行し、
        # stat呼び出しを伴うis_file/is_dirを非同期にする。
        # しかし、rglobのイテレーション自体がブロッキングになるため、
        # 大量のファイルがあるディレクトリではUIが固まる可能性を避けるため、
        # ループ全体をto_threadで実行するのがより安全かもしれない。
        # ここでは、まず個々のチェックを非同期にするアプローチで試みる。

        items_to_check = list(scan_root_path.rglob('*')) # 一旦リスト化（大量ファイルでメモリ注意）
                                                       # 非同期ジェネレータ的に扱えると良いが複雑になる

        for item in items_to_check:
            try:
                is_file = await asyncio.to_thread(item.is_file)
                is_dir = await asyncio.to_thread(item.is_dir)

                if is_file:
                    file_ext = get_file_extension(item) # これは同期的なPath操作
                    if file_ext not in SUPPORTED_EXTENSIONS:
                        actual_files_count += 1
                        self._log(f"  Counted file: {item.relative_to(scan_root_path)}", "DEBUG")
                    else:
                        self._log(f"  Skipped (compressed archive): {item.relative_to(scan_root_path)}", "DEBUG")
                elif is_dir:
                    folders_count += 1
                    self._log(f"  Counted folder: {item.relative_to(scan_root_path)}", "DEBUG")
            except Exception as e:
                self._log(f"Error processing item {item} during stats collection: {e}", "WARNING")

        self._log(f"Final stats: {actual_files_count} actual files, {folders_count} folders.", "INFO")
        return actual_files_count, folders_count

app = FastAPI()

class ExtractRequest(BaseModel):
    directory: str
    create_backup: bool = True
    delete_original: bool = True
    preserve_structure: bool = True
    extract_flat: bool = False

class ExtractResponse(BaseModel):
    success: bool
    message: str
    logs: list[str]
    stats: dict

# 静的ファイルを提供するための設定
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Mount static files directory
# Make sure 'static' directory exists at the same level as api.py or adjust path
# For robustness, define base path if needed:
# import os
# SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# STATIC_DIR = os.path.join(SCRIPT_DIR, "static")
# app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Simpler version if 'static' is in the current working directory when server starts
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=FileResponse)
async def read_index():
    # Return index.html from the static directory
    # Ensure 'index.html' is inside the 'static' directory
    return "static/index.html"

@app.post("/extract", response_model=ExtractResponse)
async def extract_archive(request: ExtractRequest):
    """
    指定されたディレクトリ内のアーカイブファイルを解凍します。
    """
    request_id = datetime.now().strftime("%Y%m%d%H%M%S%f") # request_id は最初に定義
    try:
        target_dir = Path(request.directory)
        # Pathオブジェクトでディレクトリの存在と種類を非同期で確認
        if not await asyncio.to_thread(target_dir.exists):
             raise HTTPException(status_code=400, detail=f"Directory not found: {request.directory}")
        if not await asyncio.to_thread(target_dir.is_dir):
             raise HTTPException(status_code=400, detail=f"Path is not a directory: {request.directory}")

        # logging.info(f"RAR_AVAILABLE: {RAR_AVAILABLE}, SEVENZ_AVAILABLE: {SEVENZ_AVAILABLE}")
        extractor = BatchExtractor(
            work_dir=request.directory, # BatchExtractor内ではPath(work_dir)とされる
            create_backup=request.create_backup,
            delete_original=request.delete_original,
            preserve_structure=request.preserve_structure,
            extract_flat=request.extract_flat,
            request_id=request_id
        )

        success, message = await extractor.run()

        return ExtractResponse(
            success=success,
            message=message,
            logs=extractor.logs,
            stats=extractor.stats
        )
    except HTTPException as e:
        # FastAPIからのHTTPExceptionはそのまま再raiseする
        # (例えば、リクエストバリデーションエラーや上記のディレクトリチェックエラー)
        raise e
    except Exception as e:
        # BatchExtractor.run()内部や、その他の予期せぬエラー
        app_logger = logging.getLogger(__name__) # api.pyのモジュールロガー
        # request_id が未定義になるケースを避ける (tryブロックの最初で定義済みの想定)
        app_logger.error(
            f"Critical error in /extract endpoint for request_id={request_id}: {str(e)}",
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="An internal server error occurred. Please check server logs for details.")

# FastAPIサーバーを起動するためのコマンド (開発用)
if __name__ == "__main__":
    import uvicorn
    # 基本的なロギング設定 (Uvicornが独自に行うものとは別)
    # Uvicornのログレベルとフォーマットはコマンドラインやプログラムから設定可能
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    uvicorn.run(app, host="0.0.0.0", port=8000)

# print("api.py created with FastAPI app and /extract endpoint skeleton.") # 開発中のprint文は削除
