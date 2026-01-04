from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import os
import shutil

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

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

@app.post("/api/process", response_model=VideoResponse)
async def process_video(request: VideoRequest):
    temp_file = None
    try:
        # 1. Download
        print(f"Processing URL: {request.url}")
        temp_file, info = downloader.download_audio(request.url)
        video_title = info.get('title', 'Unknown Video')
        video_id = info.get('id', 'unknown_id')
        
        # 2. Transcribe (Force Japanese)
        print("Transcribing audio...")
        result = transcriber.transcribe(temp_file, language="ja")
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
            title=video_title,
            segments=final_segments
        )

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
