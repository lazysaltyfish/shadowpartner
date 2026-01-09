from fastapi import FastAPI, HTTPException, UploadFile, File, Request, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
import shutil
import uuid
from enum import Enum
import time
import difflib
import re
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import Services
# Note: Ensure these files exist and are in python path
from services.downloader import VideoDownloader
from services.transcriber import AudioTranscriber
from services.analyzer import JapaneseAnalyzer
from services.aligner import Aligner
from services.translator import Translator
from services.subtitle_linearizer import SubtitleLinearizer
from services.video_utils import generate_video_id_from_file

# Helper to ensure ffmpeg is in path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_BIN = os.path.join(BASE_DIR, "bin") 
if os.path.exists(LOCAL_BIN) and LOCAL_BIN not in os.environ["PATH"]:
    print(f"Adding local bin to PATH: {LOCAL_BIN}")
    os.environ["PATH"] += os.pathsep + LOCAL_BIN

app = FastAPI(title="ShadowPartner API")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"Incoming request: {request.method} {request.url}")
    try:
        response = await call_next(request)
        print(f"Response status: {response.status_code}")
        return response
    except Exception as e:
        print(f"Request failed: {e}")
        raise e

# Configure CORS
# Note: allow_origins=["*"] cannot be used with allow_credentials=True in strict browsers
# We use allow_origin_regex to match Codespaces/Gitpod domains dynamically
# app.add_middleware(
#     CORSMiddleware,
#     # Updated regex to be more permissive for various github codespaces subdomains
#     allow_origin_regex=r"https://.*\.app\.github\.dev|https://.*\.gitpod\.io",
#     # Added explicit port 3000 which is common for some frontend dev servers
#     allow_origins=["http://localhost:8080", "http://127.0.0.1:8080", "http://localhost:5500", "http://127.0.0.1:5500", "http://localhost:3000"],
#     allow_credentials=True,
#     allow_methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"],
#     allow_headers=["*"],
# )

@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    # Handle preflight requests
    if request.method == "OPTIONS":
        response = fastapi.Response()
    else:
        try:
            response = await call_next(request)
        except Exception as e:
            print(f"Request failed: {e}")
            # Ensure we still return a response to attach headers to, even on error
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

import fastapi

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
# We initialize them here so they are ready when requests come in
try:
    # Check for configuration via Env Vars
    whisper_device = os.getenv("WHISPER_DEVICE", None) # Default to None (Auto)
    whisper_fp16 = os.getenv("WHISPER_FP16", "False").lower() == "true"
    whisper_model_size = os.getenv("WHISPER_MODEL_SIZE", "base")
    subtitle_similarity_threshold = float(os.getenv("SUBTITLE_SIMILARITY_THRESHOLD", "0.1"))
    
    downloader = VideoDownloader()
    transcriber = AudioTranscriber(model_size=whisper_model_size, device=whisper_device, fp16=whisper_fp16)
    analyzer = JapaneseAnalyzer()
    aligner = Aligner()
    translator = Translator()
    subtitle_linearizer = SubtitleLinearizer()
    print(f"All services initialized successfully. Transcriber running on {transcriber.device} (fp16={transcriber.fp16}, model={transcriber.model_size})")
except Exception as e:
    print(f"CRITICAL: Failed to initialize services: {e}")
    # We don't exit, but endpoints might fail

def update_task(task_id: str, status: TaskStatus, progress: int = 0, message: str = "", result: Any = None, error: str = None):
    if task_id in tasks:
        tasks[task_id].status = status
        tasks[task_id].progress = progress
        tasks[task_id].message = message
        if result:
            tasks[task_id].result = result
        if error:
            tasks[task_id].error = error

async def run_cpu_bound(func, *args, **kwargs):
    import asyncio
    from functools import partial
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))

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
    print(f"[Similarity Check] Score: {ratio:.4f}")

    warnings = []
    if ratio < threshold:
        warnings.append(f"Low subtitle match detected (Similarity: {ratio:.0%}). Please check if you uploaded the correct subtitle file.")
        
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
        update_task(task_id, TaskStatus.PROCESSING, 10, "Transcribing audio (Generating Timing Reference)...")
        print("Transcribing audio for timing reference...")
        t0 = time.time()
        # Run synchronous transcribe in a thread
        gen_result = await run_cpu_bound(transcriber.transcribe, file_path, language="ja")
        generated_segments = gen_result['segments']
        transcribe_time = time.time() - t0
        
        reference_segments = []

        # 3. Load & Calibrate User Subtitle (if provided)
        if subtitle_path and os.path.exists(subtitle_path):
            update_task(task_id, TaskStatus.PROCESSING, 30, "Loading and Calibrating User Subtitle...")
            print("Loading user-provided subtitle file...")

            # Load Reference
            ref_result = await run_cpu_bound(transcriber.load_subtitle, subtitle_path)
            raw_reference_segments = ref_result['segments']
            print(f"Loaded {len(raw_reference_segments)} segments from user subtitle.")

            # Deduplicate scrolling subtitles with metadata tracking
            print("Deduplicating scrolling subtitles...")
            merged_text, char_metadata = subtitle_linearizer.deduplicate_with_metadata(raw_reference_segments)
            print(f"Merged text length: {len(merged_text)} chars")

            # Check Similarity using merged text vs AI text
            print("Checking subtitle similarity...")
            # Create a temporary segment list for similarity check
            temp_ref_segments = [{'text': merged_text, 'start': 0, 'end': 0}]
            warnings = check_subtitle_similarity(generated_segments, temp_ref_segments, threshold=subtitle_similarity_threshold)
            if warnings:
                print(f"[Subtitle Check] Generated warnings: {warnings}")
            else:
                print(f"[Subtitle Check] Passed. No warnings generated.")

            # Calibrate timestamps using new method
            print("Calibrating timestamps...")
            _, char_timestamps = await run_cpu_bound(
                aligner.calibrate_from_merged,
                merged_text,
                char_metadata,
                generated_segments
            )

            # Rebuild segments with calibrated timestamps
            print("Rebuilding segments...")
            reference_segments = aligner.rebuild_segments_with_timestamps(
                merged_text, char_metadata, char_timestamps
            )
            print(f"Rebuilt {len(reference_segments)} segments with timestamps")

            has_word_timestamps = True
            
        else:
            # No subtitle provided - use AI transcription as reference
            reference_segments = generated_segments
            has_word_timestamps = True
        
        update_task(task_id, TaskStatus.PROCESSING, 40, "Analyzing Japanese text...")
        
        # 4. Process Segments (Analyze & Align)
        print(f"Analyzing {len(reference_segments)} segments...")
        final_segments = []
        raw_texts = []
        
        total_segments = len(reference_segments)
        
        # We can also offload the analysis loop if it's heavy, but let's see. 
        # For now, let's keep it in the loop but yield control occasionally if needed.
        # However, MeCab analysis IS CPU bound.
        
        def analyze_segments(segments):
            processed_segments = []
            texts = []
            for i, seg in enumerate(segments):
                # We can't update task progress easily from inside this sync function without callback
                # So we might split this up.
                text = seg['text'].strip()
                if not text:
                    continue
                texts.append(text)
                whisper_words = seg.get('words', [])
                mecab_tokens = analyzer.analyze(text)
                # Pass segment timestamps for cases where word-level timestamps are not available
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
        print("Translating segments...")
        t0 = time.time()
        # Translation involves network I/O. We updated translator to be async and concurrent.
        translations = await translator.translate_batch(raw_texts)
        translation_time = time.time() - t0
        
        # Map translations back (handle potential length mismatch gracefully)
        for i, trans in enumerate(translations):
            if i < len(final_segments):
                final_segments[i].translation = trans
            
        print("Processing complete.")
        
        total_time = (time.time() - start_total) + download_time
        
        metrics = ProcessingMetrics(
            download_time=download_time,
            transcribe_time=transcribe_time,
            analysis_time=analysis_time,
            translation_time=translation_time,
            total_time=total_time
        )
        
        print(f"[Metrics] Task {task_id} Completed. "
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
        print(f"Error processing audio: {e}")
        import traceback
        traceback.print_exc()
        update_task(task_id, TaskStatus.FAILED, 0, "Processing failed", error=str(e))
    finally:
        # Cleanup audio/video file
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        # Cleanup subtitle file if provided
        if subtitle_path and os.path.exists(subtitle_path):
            try:
                os.remove(subtitle_path)
            except:
                pass


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
        
        # 1. Download (Synchronous part to fail fast if URL invalid, or could be async too)
        # Moving download to background to avoid timeout
        import asyncio
        asyncio.create_task(download_and_process(task_id, request.url))
        
        return AsyncProcessResponse(task_id=task_id, message="Video processing started")

    except Exception as e:
        print(f"Error starting video processing: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def download_and_process(task_id: str, url: str):
    temp_file = None
    try:
        update_task(task_id, TaskStatus.PROCESSING, 5, "Downloading video...")
        print(f"Processing URL: {url}")
        
        t0 = time.time()
        temp_file, info = downloader.download_audio(url)
        download_time = time.time() - t0
        
        video_title = info.get('title', 'Unknown Video')
        video_id = info.get('id', 'unknown_id')
        
        await process_audio_task(task_id, temp_file, video_id, video_title, download_time=download_time)
    except Exception as e:
         update_task(task_id, TaskStatus.FAILED, 0, "Download failed", error=str(e))


class ChunkUpload(BaseModel):
    task_id: str
    chunk_index: int
    total_chunks: int

@app.post("/api/upload/init", response_model=AsyncProcessResponse)
async def init_upload(filename: str = Form(...)):
    task_id = str(uuid.uuid4())
    upload_dir = "temp"
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
        
    ext = os.path.splitext(filename)[1] or ".mp3"
    temp_file = os.path.join(upload_dir, f"{task_id}{ext}")
    
    # Create empty file
    open(temp_file, 'wb').close()
    
    tasks[task_id] = TaskInfo(task_id=task_id, status=TaskStatus.PENDING, message="Initialized upload...")
    
    return AsyncProcessResponse(task_id=task_id, message="Upload initialized")

@app.post("/api/upload/chunk")
async def upload_chunk(
    task_id: str = Form(...),
    chunk_index: int = Form(...),
    file: UploadFile = File(...)
):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
        
    # We assume simple sequential upload for now (appending)
    # Ideally we'd write to specific offsets but for this demo appending is fine if sequential
    # But wait, concurrent chunks might mess this up. 
    # For safety, let's write to part files then merge? 
    # Or just assume frontend sends sequentially (easier).
    
    # Let's verify file exists
    # We need to recover the extension or store it. 
    # Actually we can just find the file starting with task_id in temp
    upload_dir = "temp"
    # Exclude subtitle files to avoid appending to them by mistake
    files = [f for f in os.listdir(upload_dir) if f.startswith(task_id) and "_subtitle" not in f]
    if not files:
        raise HTTPException(status_code=404, detail="Upload session not found")
    
    temp_file = os.path.join(upload_dir, files[0])
    
    # Append chunk
    with open(temp_file, "ab") as f:
        shutil.copyfileobj(file.file, f)
        
    tasks[task_id].message = f"Uploaded chunk {chunk_index + 1}"
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
    
    upload_dir = "temp"
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
    
    # Save subtitle file with task_id prefix
    subtitle_ext = os.path.splitext(file.filename)[1] or ".srt"
    subtitle_path = os.path.join(upload_dir, f"{task_id}_subtitle{subtitle_ext}")
    
    with open(subtitle_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    print(f"Subtitle uploaded for task {task_id}: {subtitle_path}")
    return {"status": "success", "path": subtitle_path}

@app.post("/api/upload/complete", response_model=AsyncProcessResponse)
async def complete_upload(
    task_id: str = Form(...), 
    filename: str = Form(...),
    subtitle_filename: Optional[str] = Form(None)
):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    upload_dir = "temp"
    # Exclude subtitle files so we don't accidentally select the subtitle as the video source
    files = [f for f in os.listdir(upload_dir) if f.startswith(task_id) and "_subtitle" not in f]
    if not files:
        raise HTTPException(status_code=404, detail="File not found")
    
    temp_file = os.path.join(upload_dir, files[0])
    
    # Check for subtitle file
    subtitle_path = None
    if subtitle_filename:
        # Look for the corresponding subtitle part file, which we assume was uploaded with the same task_id
        subtitle_files = [f for f in os.listdir(upload_dir) if f.startswith(f"{task_id}_subtitle")]
        if subtitle_files:
            subtitle_path = os.path.join(upload_dir, subtitle_files[0])
            print(f"Found subtitle for completion: {subtitle_path}")

    # Generate stable video_id based on file content hash
    video_id = generate_video_id_from_file(temp_file)
    print(f"Generated video_id: {video_id} for file: {filename}")

    tasks[task_id].status = TaskStatus.PENDING
    tasks[task_id].message = "Upload complete. Processing..."

    import asyncio
    asyncio.create_task(process_audio_task(
        task_id,
        temp_file,
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
        upload_dir = "temp"
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
            
        session_id = str(uuid.uuid4())
        # Use mp3 extension as we will process it as audio
        ext = os.path.splitext(file.filename)[1] or ".mp3"
        temp_file = os.path.join(upload_dir, f"{session_id}{ext}")
        
        with open(temp_file, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        print(f"File uploaded to: {temp_file}")
        
        # Save subtitle file if provided
        if subtitle and subtitle.filename:
            subtitle_ext = os.path.splitext(subtitle.filename)[1] or ".srt"
            subtitle_file = os.path.join(upload_dir, f"{session_id}_subtitle{subtitle_ext}")
            
            with open(subtitle_file, "wb") as buffer:
                shutil.copyfileobj(subtitle.file, buffer)
                
            print(f"Subtitle uploaded to: {subtitle_file}")

        # Generate stable video_id based on file content hash
        video_id = generate_video_id_from_file(temp_file)
        print(f"Generated video_id: {video_id} for file: {file.filename}")

        # Start async task
        task_id = str(uuid.uuid4())

        if subtitle_file:
            tasks[task_id] = TaskInfo(task_id=task_id, status=TaskStatus.PENDING, message="Files uploaded. Using provided subtitle...")
        else:
            tasks[task_id] = TaskInfo(task_id=task_id, status=TaskStatus.PENDING, message="File uploaded. Queued for processing...")

        import asyncio
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
        print(f"Error processing uploaded file: {e}")
        # Cleanup if we failed before starting task
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        if subtitle_file and os.path.exists(subtitle_file):
            try:
                os.remove(subtitle_file)
            except:
                pass
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
