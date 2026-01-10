import asyncio
import difflib
import os
import re
import shutil
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from typing import Any, Dict, List, Optional

import fastapi
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from services.aligner import Aligner
from services.analyzer import JapaneseAnalyzer
from services.downloader import VideoDownloader
from services.subtitle_linearizer import SubtitleLinearizer
from services.transcriber import AudioTranscriber
from services.translator import Translator
from services.video_utils import generate_video_id_from_file
from utils.logger import get_logger
from utils.path_setup import setup_local_bin_path

# Load environment variables from .env file
load_dotenv()

# Setup logger
logger = get_logger(__name__)

# Setup local bin path
local_bin = setup_local_bin_path()
if local_bin:
    logger.info(f"Added local bin to PATH: {local_bin}")

app = FastAPI(title="ShadowPartner API")


@app.on_event("startup")
async def startup_event():
    """Initialize resources on startup."""
    global executor
    executor = ThreadPoolExecutor(max_workers=4)
    logger.info("ThreadPoolExecutor initialized with 4 workers")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup resources on shutdown."""
    global executor
    if executor:
        logger.info("Shutting down ThreadPoolExecutor")
        executor.shutdown(wait=True)
        logger.info("ThreadPoolExecutor shutdown complete")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Skip logging for frequent/unimportant requests
    skip_paths = ["/api/status/", "/api/upload/chunk", "/"]
    should_log = not any(path in str(request.url) for path in skip_paths)

    if should_log:
        logger.info(f"Incoming request: {request.method} {request.url}")

    try:
        response = await call_next(request)

        # Only log non-200 responses for important endpoints
        if should_log and response.status_code != 200:
            logger.info(f"Response status: {response.status_code}")

        return response
    except Exception as e:
        logger.error(f"Request failed: {e}", exc_info=True)
        raise e

@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    # Handle preflight requests
    if request.method == "OPTIONS":
        response = fastapi.Response()
    else:
        try:
            response = await call_next(request)
        except Exception as e:
            logger.error(f"Request failed in CORS middleware: {e}", exc_info=True)
            response = fastapi.Response(status_code=500)
            
    origin = request.headers.get("origin")
    
    # If no origin, we can just return (e.g. server-side curl)
    # But for browser requests, we mirror the origin
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        # Cannot use "*" with credentials: true, must echo back the requested headers
        requested_headers = request.headers.get("access-control-request-headers")
        if requested_headers:
            response.headers["Access-Control-Allow-Headers"] = requested_headers
        else:
            response.headers["Access-Control-Allow-Headers"] = "content-type, authorization, x-requested-with"
    else:
        # Fallback for some cases where Origin might be missing but we want to be permissive
        # Note: '*' cannot be used with credentials: true
        pass 

    return response


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class TaskInfo(BaseModel):
    task_id: str
    status: TaskStatus
    progress: int = 0  # 0 to 100
    message: str = "Waiting to start..."
    result: Optional[Any] = None
    error: Optional[str] = None

# In-memory task store (Use Redis/DB in production)
tasks: Dict[str, TaskInfo] = {}

# Global thread pool executor for CPU-bound tasks
executor: Optional[ThreadPoolExecutor] = None
whisper_lock: Optional[asyncio.Semaphore] = None
whisper_lock_label = "transcription"

UPLOAD_DIR = "temp"


@dataclass
class UploadSession:
    task_id: str
    temp_file: str
    next_index: int = 0
    subtitle_path: Optional[str] = None
    updated_at: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    completed: bool = False
    processing_started: bool = False


upload_sessions: Dict[str, UploadSession] = {}

class VideoRequest(BaseModel):
    url: str

class ProcessingMetrics(BaseModel):
    download_time: float = 0.0
    transcribe_time: float = 0.0
    analysis_time: float = 0.0
    translation_time: float = 0.0
    total_time: float = 0.0

class Word(BaseModel):
    text: str
    reading: Optional[str] = None
    start: float
    end: float

class Segment(BaseModel):
    words: List[Word]
    translation: str
    start: float
    end: float

class VideoResponse(BaseModel):
    video_id: str
    title: str
    segments: List[Segment]
    metrics: Optional[ProcessingMetrics] = None
    has_word_timestamps: bool = True  # False when using user-provided subtitles (no word-level timing)
    warnings: List[str] = []

class AsyncProcessResponse(BaseModel):
    task_id: str
    message: str

# Initialize Services
try:
    whisper_device = os.getenv("WHISPER_DEVICE", None)
    whisper_fp16 = os.getenv("WHISPER_FP16", "False").lower() == "true"
    whisper_model_size = os.getenv("WHISPER_MODEL_SIZE", "base")
    subtitle_similarity_threshold = float(os.getenv("SUBTITLE_SIMILARITY_THRESHOLD", "0.1"))

    logger.info("Initializing services...")
    downloader = VideoDownloader()
    transcriber = AudioTranscriber(model_size=whisper_model_size, device=whisper_device, fp16=whisper_fp16)
    analyzer = JapaneseAnalyzer()
    aligner = Aligner()
    translator = Translator()
    subtitle_linearizer = SubtitleLinearizer()
    is_accelerated = transcriber.device.lower() != "cpu"
    if is_accelerated:
        whisper_lock = asyncio.Semaphore(1)
        whisper_lock_label = "GPU transcription"
        logger.info("Whisper transcription queue enabled (1 at a time)")
    logger.info(f"All services initialized successfully. Transcriber running on {transcriber.device} (fp16={transcriber.fp16}, model={transcriber.model_size})")
except Exception as e:
    logger.critical(f"Failed to initialize services: {e}", exc_info=True)

def update_task(task_id: str, status: TaskStatus, progress: int = 0, message: str = "", result: Any = None, error: str = None):
    if task_id in tasks:
        tasks[task_id].status = status
        tasks[task_id].progress = progress
        tasks[task_id].message = message
        if result:
            tasks[task_id].result = result
        if error:
            tasks[task_id].error = error

def get_upload_session(task_id: str) -> Optional[UploadSession]:
    return upload_sessions.get(task_id)

def release_upload_session(task_id: str):
    upload_sessions.pop(task_id, None)

async def run_cpu_bound(func, *args, **kwargs):
    """Run CPU-bound function in thread pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, partial(func, *args, **kwargs))

def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def _touch_file(path: str):
    with open(path, "wb"):
        pass

def _write_upload_file(path: str, upload_file: UploadFile, mode: str = "wb"):
    upload_file.file.seek(0)
    with open(path, mode) as buffer:
        shutil.copyfileobj(upload_file.file, buffer)

def check_subtitle_similarity(generated_segments: List[Dict], reference_segments: List[Dict], threshold: float = 0.1) -> List[str]:
    """
    Check similarity between generated segments and reference segments.
    Returns a list of warnings if similarity is low.
    """
    if not generated_segments or not reference_segments:
        return []

    # Helper to extract text from a list of segments
    def extract_text(segments, sample_ratio=0.2, max_chars=2000):
        total_len = len(segments)
        if total_len == 0:
            return ""
        
        # Define ranges: Start, Middle, End
        count = max(1, int(total_len * sample_ratio))
        
        ranges = [
            (0, count), # Start
            (total_len // 2 - count // 2, total_len // 2 + count // 2), # Middle
            (total_len - count, total_len) # End
        ]
        
        text_parts = []
        for start, end in ranges:
            start = max(0, start)
            end = min(total_len, end)
            if start >= end:
                continue
            
            chunk_text = "".join([seg.get('text', '') for seg in segments[start:end]])
            text_parts.append(chunk_text)
            
        full_text = "".join(text_parts)
        # Normalize: Remove whitespace and common punctuation
        normalized = re.sub(r'[\s\u3000\u3001\u3002,.!?]', '', full_text).lower()
        return normalized[:max_chars * 3] # Cap length just in case

    text_gen = extract_text(generated_segments)
    text_ref = extract_text(reference_segments)
    
    if not text_gen or not text_ref:
        return []

    # Calculate similarity
    ratio = difflib.SequenceMatcher(None, text_gen, text_ref).ratio()
    logger.info(f"Subtitle similarity score: {ratio:.4f}")

    warnings = []
    if ratio < threshold:
        warning_msg = f"Low subtitle match detected (Similarity: {ratio:.0%}). Please check if you uploaded the correct subtitle file."
        logger.warning(warning_msg)
        warnings.append(warning_msg)

    return warnings

async def process_audio_task(task_id: str, file_path: str, video_id: str, title: str, download_time: float = 0.0, subtitle_path: str = None):
    """
    Process audio/video file and generate learning segments.
    
    Args:
        task_id: Unique task identifier
        file_path: Path to the audio/video file
        video_id: Video identifier
        title: Video title
        download_time: Time spent downloading (for metrics)
        subtitle_path: Optional path to user-provided subtitle file (SRT format).
                      If provided, skips AI transcription and uses the subtitle directly.
    """
    start_total = time.time()
    transcribe_time = 0.0
    analysis_time = 0.0
    translation_time = 0.0
    has_word_timestamps = True  # Track if we have precise word-level timestamps
    warnings = []
    
    try:
        # 2. Transcribe (Always run AI for timing reference)
        if whisper_lock:
            update_task(task_id, TaskStatus.PROCESSING, 5, f"Waiting for {whisper_lock_label} slot...")
            async with whisper_lock:
                update_task(task_id, TaskStatus.PROCESSING, 10, "Transcribing audio (Generating Timing Reference)...")
                logger.info(f"Task {task_id}: Starting transcription for timing reference")
                t0 = time.time()
                gen_result = await run_cpu_bound(transcriber.transcribe, file_path, language="ja")
                generated_segments = gen_result['segments']
                transcribe_time = time.time() - t0
                logger.info(f"Task {task_id}: Transcription completed in {transcribe_time:.2f}s")
        else:
            update_task(task_id, TaskStatus.PROCESSING, 10, "Transcribing audio (Generating Timing Reference)...")
            logger.info(f"Task {task_id}: Starting transcription for timing reference")
            t0 = time.time()
            gen_result = await run_cpu_bound(transcriber.transcribe, file_path, language="ja")
            generated_segments = gen_result['segments']
            transcribe_time = time.time() - t0
            logger.info(f"Task {task_id}: Transcription completed in {transcribe_time:.2f}s")
        
        reference_segments = []

        # 3. Load & Calibrate User Subtitle (if provided)
        if subtitle_path and os.path.exists(subtitle_path):
            update_task(task_id, TaskStatus.PROCESSING, 30, "Loading and Calibrating User Subtitle...")
            logger.info(f"Task {task_id}: Loading user-provided subtitle file")

            # Load Reference
            ref_result = await run_cpu_bound(transcriber.load_subtitle, subtitle_path)
            raw_reference_segments = ref_result['segments']
            logger.info(f"Task {task_id}: Loaded {len(raw_reference_segments)} segments from user subtitle")

            # Deduplicate scrolling subtitles with metadata tracking
            logger.info(f"Task {task_id}: Deduplicating scrolling subtitles")
            merged_text, char_metadata = subtitle_linearizer.deduplicate_with_metadata(raw_reference_segments)
            logger.info(f"Task {task_id}: Merged text length: {len(merged_text)} chars")

            # Check Similarity using merged text vs AI text
            logger.info(f"Task {task_id}: Checking subtitle similarity")
            temp_ref_segments = [{'text': merged_text, 'start': 0, 'end': 0}]
            warnings = check_subtitle_similarity(generated_segments, temp_ref_segments, threshold=subtitle_similarity_threshold)
            if warnings:
                logger.warning(f"Task {task_id}: Subtitle check warnings: {warnings}")
            else:
                logger.info(f"Task {task_id}: Subtitle check passed")

            # Calibrate timestamps using new method
            logger.info(f"Task {task_id}: Calibrating timestamps")
            _, char_timestamps = await run_cpu_bound(
                aligner.calibrate_from_merged,
                merged_text,
                char_metadata,
                generated_segments
            )

            # Rebuild segments with calibrated timestamps
            logger.info(f"Task {task_id}: Rebuilding segments")
            reference_segments = aligner.rebuild_segments_with_timestamps(
                merged_text, char_metadata, char_timestamps
            )
            logger.info(f"Task {task_id}: Rebuilt {len(reference_segments)} segments with timestamps")

            has_word_timestamps = True
            
        else:
            # No subtitle provided - use AI transcription as reference
            reference_segments = generated_segments
            has_word_timestamps = True
        
        update_task(task_id, TaskStatus.PROCESSING, 40, "Analyzing Japanese text...")

        # 4. Process Segments (Analyze & Align)
        logger.info(f"Task {task_id}: Analyzing {len(reference_segments)} segments")
        final_segments = []
        raw_texts = []
        
        # We can also offload the analysis loop if it's heavy, but let's see. 
        # For now, let's keep it in the loop but yield control occasionally if needed.
        # However, MeCab analysis IS CPU bound.
        
        def analyze_segments(segments):
            processed_segments = []
            texts = []
            for i, seg in enumerate(segments):
                text = seg['text'].strip()
                if not text:
                    continue
                texts.append(text)
                whisper_words = seg.get('words', [])
                mecab_tokens = analyzer.analyze(text)
                aligned_tokens = aligner.align(
                    whisper_words,
                    mecab_tokens,
                    segment_start=seg.get('start'),
                    segment_end=seg.get('end')
                )
                
                words_model = []
                for t in aligned_tokens:
                    words_model.append(Word(
                        text=t['text'],
                        reading=t.get('reading', ''),
                        start=t.get('start') or 0.0,
                        end=t.get('end') or 0.0
                    ))
                
                processed_segments.append(Segment(
                    words=words_model,
                    translation="", 
                    start=seg['start'],
                    end=seg['end']
                ))
            return processed_segments, texts

        # Run analysis in thread
        t0 = time.time()
        final_segments, raw_texts = await run_cpu_bound(analyze_segments, reference_segments)
        analysis_time = time.time() - t0

        update_task(task_id, TaskStatus.PROCESSING, 70, "Translating to Chinese...")

        # 4. Translate
        logger.info(f"Task {task_id}: Translating {len(raw_texts)} segments")
        t0 = time.time()
        # Translation involves network I/O. We updated translator to be async and concurrent.
        translations = await translator.translate_batch(raw_texts)
        translation_time = time.time() - t0
        
        # Map translations back (handle potential length mismatch gracefully)
        for i, trans in enumerate(translations):
            if i < len(final_segments):
                final_segments[i].translation = trans

        logger.info(f"Task {task_id}: Processing complete")
        
        total_time = (time.time() - start_total) + download_time
        
        metrics = ProcessingMetrics(
            download_time=download_time,
            transcribe_time=transcribe_time,
            analysis_time=analysis_time,
            translation_time=translation_time,
            total_time=total_time
        )
        
        logger.info(f"Task {task_id} completed - "
                   f"Download: {metrics.download_time:.2f}s, "
                   f"Transcribe: {metrics.transcribe_time:.2f}s, "
                   f"Analysis: {metrics.analysis_time:.2f}s, "
                   f"Translation: {metrics.translation_time:.2f}s, "
                   f"Total: {metrics.total_time:.2f}s")
        
        final_response = VideoResponse(
            video_id=video_id,
            title=title,
            segments=final_segments,
            metrics=metrics,
            has_word_timestamps=has_word_timestamps,
            warnings=warnings
        )
        
        update_task(task_id, TaskStatus.COMPLETED, 100, "Completed", result=final_response)

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}", exc_info=True)
        update_task(task_id, TaskStatus.FAILED, 0, "Processing failed", error=str(e))
    finally:
        # Cleanup audio/video file
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.debug(f"Cleaned up file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup file {file_path}: {e}")
        # Cleanup subtitle file if provided
        if subtitle_path and os.path.exists(subtitle_path):
            try:
                os.remove(subtitle_path)
                logger.debug(f"Cleaned up subtitle: {subtitle_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup subtitle {subtitle_path}: {e}")
        release_upload_session(task_id)


@app.get("/api/status/{task_id}", response_model=TaskInfo)
async def get_task_status(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return tasks[task_id]

@app.get("/")
async def root():
    return {"message": "ShadowPartner API is running"}



@app.post("/api/process", response_model=AsyncProcessResponse)
async def process_video(request: VideoRequest, background_tasks: BackgroundTasks):
    try:
        task_id = str(uuid.uuid4())
        tasks[task_id] = TaskInfo(task_id=task_id, status=TaskStatus.PENDING, message="Downloading video...")
        logger.info(f"Starting video processing task {task_id} for URL: {request.url}")

        asyncio.create_task(download_and_process(task_id, request.url))

        return AsyncProcessResponse(task_id=task_id, message="Video processing started")

    except Exception as e:
        logger.error(f"Error starting video processing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

async def download_and_process(task_id: str, url: str):
    temp_file = None
    try:
        update_task(task_id, TaskStatus.PROCESSING, 5, "Downloading video...")
        logger.info(f"Task {task_id}: Downloading from URL: {url}")

        t0 = time.time()
        temp_file, info = await asyncio.to_thread(downloader.download_audio, url)
        download_time = time.time() - t0

        video_title = info.get('title', 'Unknown Video')
        video_id = info.get('id', 'unknown_id')
        logger.info(f"Task {task_id}: Download completed in {download_time:.2f}s - {video_title}")

        await process_audio_task(task_id, temp_file, video_id, video_title, download_time=download_time)
    except Exception as e:
        logger.error(f"Task {task_id}: Download failed - {e}", exc_info=True)
        update_task(task_id, TaskStatus.FAILED, 0, "Download failed", error=str(e))


@app.post("/api/upload/init", response_model=AsyncProcessResponse)
async def init_upload(filename: str = Form(...)):
    task_id = str(uuid.uuid4())
    await asyncio.to_thread(_ensure_dir, UPLOAD_DIR)

    ext = os.path.splitext(filename)[1] or ".mp3"
    temp_file = os.path.join(UPLOAD_DIR, f"{task_id}{ext}")

    await asyncio.to_thread(_touch_file, temp_file)

    tasks[task_id] = TaskInfo(task_id=task_id, status=TaskStatus.PENDING, message="Initialized upload...")
    upload_sessions[task_id] = UploadSession(task_id=task_id, temp_file=temp_file)
    logger.info(f"Upload initialized: task_id={task_id}, filename={filename}")

    return AsyncProcessResponse(task_id=task_id, message="Upload initialized")

@app.post("/api/upload/chunk")
async def upload_chunk(
    task_id: str = Form(...),
    chunk_index: int = Form(...),
    file: UploadFile = File(...)
):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    session = get_upload_session(task_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Upload session not found")

    if chunk_index < 0:
        raise HTTPException(status_code=400, detail="Invalid chunk index")

    async with session.lock:
        if session.completed:
            raise HTTPException(status_code=409, detail="Upload already completed")
        if chunk_index < session.next_index:
            # Duplicate chunk upload; acknowledge to support retries.
            return {"status": "success"}
        if chunk_index > session.next_index:
            raise HTTPException(
                status_code=409,
                detail=f"Out-of-order chunk. Expected {session.next_index}, got {chunk_index}."
            )

        await asyncio.to_thread(_write_upload_file, session.temp_file, file, "ab")
        session.next_index += 1
        session.updated_at = time.time()

    tasks[task_id].message = f"Uploaded chunk {chunk_index + 1}"
    logger.debug(f"Task {task_id}: Uploaded chunk {chunk_index + 1}")
    return {"status": "success"}

@app.post("/api/upload/subtitle")
async def upload_subtitle(
    task_id: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Upload a subtitle file for an existing chunked upload session.
    The subtitle file will be saved with the naming convention {task_id}_subtitle.{ext}
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    session = get_upload_session(task_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Upload session not found")
    if not os.path.exists(UPLOAD_DIR):
        await asyncio.to_thread(_ensure_dir, UPLOAD_DIR)
    
    # Save subtitle file with task_id prefix
    subtitle_ext = os.path.splitext(file.filename)[1] or ".srt"
    subtitle_path = os.path.join(UPLOAD_DIR, f"{task_id}_subtitle{subtitle_ext}")
    
    async with session.lock:
        if session.completed:
            raise HTTPException(status_code=409, detail="Upload already completed")
        await asyncio.to_thread(_write_upload_file, subtitle_path, file, "wb")
        session.subtitle_path = subtitle_path
        session.updated_at = time.time()

    logger.info(f"Task {task_id}: Subtitle uploaded - {subtitle_path}")
    return {"status": "success", "path": subtitle_path}

@app.post("/api/upload/complete", response_model=AsyncProcessResponse)
async def complete_upload(
    task_id: str = Form(...), 
    filename: str = Form(...),
    subtitle_filename: Optional[str] = Form(None)
):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    session = get_upload_session(task_id)
    if session is None:
        return AsyncProcessResponse(task_id=task_id, message="Processing already started")

    async with session.lock:
        if session.completed:
            return AsyncProcessResponse(task_id=task_id, message="Processing already started")
        if not os.path.exists(session.temp_file):
            raise HTTPException(status_code=404, detail="File not found")

        subtitle_path = session.subtitle_path
        if subtitle_filename and subtitle_path is None:
            subtitle_files = [
                f for f in os.listdir(UPLOAD_DIR)
                if f.startswith(f"{task_id}_subtitle")
            ]
            if subtitle_files:
                subtitle_path = os.path.join(UPLOAD_DIR, subtitle_files[0])
                logger.info(f"Task {task_id}: Found subtitle for completion - {subtitle_path}")

        # Generate stable video_id based on file content hash
        video_id = await asyncio.to_thread(generate_video_id_from_file, session.temp_file)
        logger.info(f"Task {task_id}: Generated video_id={video_id} for file={filename}")

        tasks[task_id].status = TaskStatus.PENDING
        tasks[task_id].message = "Upload complete. Processing..."

        session.completed = True
        session.processing_started = True

        asyncio.create_task(process_audio_task(
            task_id,
            session.temp_file,
            video_id,  # Use hash-based video_id
            filename,
            download_time=0.0,
            subtitle_path=subtitle_path
        ))

    return AsyncProcessResponse(task_id=task_id, message="Processing started")

@app.post("/api/upload", response_model=AsyncProcessResponse)
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    subtitle: Optional[UploadFile] = File(None)
):
    """
    Upload audio/video file for processing.
    
    Args:
        file: The audio/video file to process (required)
        subtitle: Optional subtitle file in SRT format. If provided, AI transcription
                 will be skipped and the provided subtitle will be used instead.
    
    Returns:
        AsyncProcessResponse with task_id for tracking progress
    """
    temp_file = None
    subtitle_file = None
    try:
        # Save uploaded file immediately
        await asyncio.to_thread(_ensure_dir, UPLOAD_DIR)
            
        session_id = str(uuid.uuid4())
        # Use mp3 extension as we will process it as audio
        ext = os.path.splitext(file.filename)[1] or ".mp3"
        temp_file = os.path.join(UPLOAD_DIR, f"{session_id}{ext}")
        
        await asyncio.to_thread(_write_upload_file, temp_file, file, "wb")

        logger.info(f"File uploaded: {temp_file}")
        
        # Save subtitle file if provided
        if subtitle and subtitle.filename:
            subtitle_ext = os.path.splitext(subtitle.filename)[1] or ".srt"
            subtitle_file = os.path.join(UPLOAD_DIR, f"{session_id}_subtitle{subtitle_ext}")
            
            await asyncio.to_thread(_write_upload_file, subtitle_file, subtitle, "wb")

            logger.info(f"Subtitle uploaded: {subtitle_file}")

        # Generate stable video_id based on file content hash
        video_id = await asyncio.to_thread(generate_video_id_from_file, temp_file)
        logger.info(f"Generated video_id: {video_id} for file: {file.filename}")

        # Start async task
        task_id = str(uuid.uuid4())

        if subtitle_file:
            tasks[task_id] = TaskInfo(task_id=task_id, status=TaskStatus.PENDING, message="Files uploaded. Using provided subtitle...")
        else:
            tasks[task_id] = TaskInfo(task_id=task_id, status=TaskStatus.PENDING, message="File uploaded. Queued for processing...")

        logger.info(f"Starting processing task {task_id} for uploaded file")
        asyncio.create_task(process_audio_task(
            task_id,
            temp_file,
            video_id,  # Use hash-based video_id
            file.filename,
            download_time=0.0,
            subtitle_path=subtitle_file
        ))
        
        return AsyncProcessResponse(task_id=task_id, message="File uploaded, processing started")

    except Exception as e:
        logger.error(f"Error processing uploaded file: {e}", exc_info=True)
        # Cleanup if we failed before starting task
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup temp file: {cleanup_error}")
        if subtitle_file and os.path.exists(subtitle_file):
            try:
                os.remove(subtitle_file)
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup subtitle file: {cleanup_error}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
