from fastapi import FastAPI, HTTPException, UploadFile, File, Request, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
import shutil
import uuid
from enum import Enum
import time
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
        response.headers["Access-Control-Allow-Headers"] = "*"
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
    
    downloader = VideoDownloader()
    transcriber = AudioTranscriber(model_size=whisper_model_size, device=whisper_device, fp16=whisper_fp16)
    analyzer = JapaneseAnalyzer()
    aligner = Aligner()
    translator = Translator()
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

async def process_audio_task(task_id: str, file_path: str, video_id: str, title: str):
    try:
        update_task(task_id, TaskStatus.PROCESSING, 10, "Transcribing audio (this may take a while)...")
        
        # 2. Transcribe (Force Japanese)
        print("Transcribing audio...")
        # Run synchronous transcribe in a thread
        result = await run_cpu_bound(transcriber.transcribe, file_path, language="ja")
        whisper_segments = result['segments']
        
        update_task(task_id, TaskStatus.PROCESSING, 40, "Analyzing Japanese text...")
        
        # 3. Process Segments (Analyze & Align)
        print(f"Analyzing {len(whisper_segments)} segments...")
        final_segments = []
        raw_texts = []
        
        total_segments = len(whisper_segments)
        
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
                aligned_tokens = aligner.align(whisper_words, mecab_tokens)
                
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
        final_segments, raw_texts = await run_cpu_bound(analyze_segments, whisper_segments)

        update_task(task_id, TaskStatus.PROCESSING, 70, "Translating to Chinese...")

        # 4. Translate
        print("Translating segments...")
        # Translation involves network I/O but the client might be sync or async. 
        # Our new translator uses google-genai which might be sync or async depending on usage.
        # We implemented it as synchronous calls. So offload it.
        translations = await run_cpu_bound(translator.translate_batch, raw_texts)
        
        # Map translations back (handle potential length mismatch gracefully)
        for i, trans in enumerate(translations):
            if i < len(final_segments):
                final_segments[i].translation = trans
            
        print("Processing complete.")
        
        final_response = VideoResponse(
            video_id=video_id,
            title=title,
            segments=final_segments
        )
        
        update_task(task_id, TaskStatus.COMPLETED, 100, "Completed", result=final_response)

    except Exception as e:
        print(f"Error processing audio: {e}")
        import traceback
        traceback.print_exc()
        update_task(task_id, TaskStatus.FAILED, 0, "Processing failed", error=str(e))
    finally:
         # Cleanup
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
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
        temp_file, info = downloader.download_audio(url)
        video_title = info.get('title', 'Unknown Video')
        video_id = info.get('id', 'unknown_id')
        
        await process_audio_task(task_id, temp_file, video_id, video_title)
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
    files = [f for f in os.listdir(upload_dir) if f.startswith(task_id)]
    if not files:
        raise HTTPException(status_code=404, detail="Upload session not found")
    
    temp_file = os.path.join(upload_dir, files[0])
    
    # Append chunk
    with open(temp_file, "ab") as f:
        shutil.copyfileobj(file.file, f)
        
    tasks[task_id].message = f"Uploaded chunk {chunk_index + 1}"
    return {"status": "success"}

@app.post("/api/upload/complete", response_model=AsyncProcessResponse)
async def complete_upload(task_id: str = Form(...), filename: str = Form(...)):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    upload_dir = "temp"
    files = [f for f in os.listdir(upload_dir) if f.startswith(task_id)]
    if not files:
        raise HTTPException(status_code=404, detail="File not found")
    
    temp_file = os.path.join(upload_dir, files[0])
    
    tasks[task_id].status = TaskStatus.PENDING
    tasks[task_id].message = "Upload complete. Processing..."
    
    import asyncio
    # Reuse process_audio_task
    # Note: we need a video_id (we use task_id as session id)
    asyncio.create_task(process_audio_task(task_id, temp_file, task_id, filename))
    
    return AsyncProcessResponse(task_id=task_id, message="Processing started")

@app.post("/api/upload", response_model=AsyncProcessResponse)
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    temp_file = None
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
        
        # Start async task
        task_id = str(uuid.uuid4())
        tasks[task_id] = TaskInfo(task_id=task_id, status=TaskStatus.PENDING, message="File uploaded. Queued for processing...")
        
        # Pass the file path to background task
        # IMPORTANT: The file is already on disk, so the background task can access it.
        # We don't need to keep the 'file' object open.
        
        import asyncio
        asyncio.create_task(process_audio_task(task_id, temp_file, session_id, file.filename))
        
        return AsyncProcessResponse(task_id=task_id, message="File uploaded, processing started")

    except Exception as e:
        print(f"Error processing uploaded file: {e}")
        # Cleanup if we failed before starting task
        if temp_file and os.path.exists(temp_file):
             try:
                os.remove(temp_file)
             except:
                pass
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
