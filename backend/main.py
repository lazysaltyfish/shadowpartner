from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import os
import shutil
import uuid

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
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.app\.github\.dev|https://.*\.gitpod\.io",
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080", "http://localhost:5500", "http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# Initialize Services
# We initialize them here so they are ready when requests come in
try:
    downloader = VideoDownloader()
    transcriber = AudioTranscriber()
    analyzer = JapaneseAnalyzer()
    aligner = Aligner()
    translator = Translator()
    print("All services initialized successfully.")
except Exception as e:
    print(f"CRITICAL: Failed to initialize services: {e}")
    # We don't exit, but endpoints might fail

@app.get("/")
async def root():
    return {"message": "ShadowPartner API is running"}

async def process_audio_file(file_path: str, video_id: str, title: str):
    try:
        # 2. Transcribe (Force Japanese)
        print("Transcribing audio...")
        result = transcriber.transcribe(file_path, language="ja")
        whisper_segments = result['segments']
        
        # 3. Process Segments (Analyze & Align)
        print(f"Analyzing {len(whisper_segments)} segments...")
        final_segments = []
        raw_texts = []
        
        for seg in whisper_segments:
            text = seg['text'].strip()
            # Whisper sometimes outputs empty segments
            if not text:
                continue
                
            raw_texts.append(text)
            
            # Whisper words for this segment
            whisper_words = seg.get('words', [])
            
            # MeCab Analysis
            mecab_tokens = analyzer.analyze(text)
            
            # Align
            aligned_tokens = aligner.align(whisper_words, mecab_tokens)
            
            # Convert to Pydantic model format
            words_model = []
            for t in aligned_tokens:
                words_model.append(Word(
                    text=t['text'],
                    reading=t.get('reading', ''),
                    # Ensure defaults if alignment failed totally
                    start=t.get('start') or 0.0,
                    end=t.get('end') or 0.0
                ))
                
            final_segments.append(Segment(
                words=words_model,
                translation="", # Placeholder
                start=seg['start'],
                end=seg['end']
            ))
            
        # 4. Translate
        print("Translating segments...")
        translations = translator.translate_batch(raw_texts)
        
        # Map translations back (handle potential length mismatch gracefully)
        for i, trans in enumerate(translations):
            if i < len(final_segments):
                final_segments[i].translation = trans
            
        print("Processing complete.")
        return VideoResponse(
            video_id=video_id,
            title=title,
            segments=final_segments
        )
    except Exception as e:
        print(f"Error processing audio: {e}")
        import traceback
        traceback.print_exc()
        raise e

@app.post("/api/process", response_model=VideoResponse)
async def process_video(request: VideoRequest):
    temp_file = None
    try:
        # 1. Download
        print(f"Processing URL: {request.url}")
        temp_file, info = downloader.download_audio(request.url)
        video_title = info.get('title', 'Unknown Video')
        video_id = info.get('id', 'unknown_id')
        
        return await process_audio_file(temp_file, video_id, video_title)

    except Exception as e:
        print(f"Error processing video: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Cleanup
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass

@app.post("/api/upload", response_model=VideoResponse)
async def upload_video(file: UploadFile = File(...)):
    temp_file = None
    try:
        # Save uploaded file
        upload_dir = "temp"
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
            
        session_id = str(uuid.uuid4())
        # Use mp3 extension as we will process it as audio
        # But we should respect original extension or just save it and let ffmpeg/whisper handle
        ext = os.path.splitext(file.filename)[1] or ".mp3"
        temp_file = os.path.join(upload_dir, f"{session_id}{ext}")
        
        with open(temp_file, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        print(f"File uploaded to: {temp_file}")
        
        # Use session_id as video_id for uploaded content
        return await process_audio_file(temp_file, session_id, file.filename)

    except Exception as e:
        print(f"Error processing uploaded file: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
