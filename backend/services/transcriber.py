import whisper
import os

# Helper to ensure ffmpeg is in path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_BIN = os.path.join(BASE_DIR, "bin") 
if os.path.exists(LOCAL_BIN) and LOCAL_BIN not in os.environ["PATH"]:
    print(f"Adding local bin to PATH: {LOCAL_BIN}")
    os.environ["PATH"] += os.pathsep + LOCAL_BIN

# Load model globally to avoid reloading on every request
# Options: tiny, base, small, medium, large
# 'base' is a good balance for MVP testing.
MODEL_SIZE = "base"
print(f"Loading Whisper model ({MODEL_SIZE})...")
try:
    model = whisper.load_model(MODEL_SIZE)
    print("Whisper model loaded.")
except Exception as e:
    print(f"Error loading Whisper model: {e}")
    # We might fail here if ffmpeg is totally missing and whisper checks on load? 
    # Usually it downloads the model first.
    model = None

class AudioTranscriber:
    def transcribe(self, audio_path: str, language: str = None):
        """
        Transcribes audio and returns segments with word timestamps.
        """
        if model is None:
            raise Exception("Whisper model failed to load.")

        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Ensure we are using absolute path for safety
        audio_path = os.path.abspath(audio_path)

        options = {
            "word_timestamps": True,
        }
        if language:
            options["language"] = language

        # Transcribe
        # Note: This is blocking. In a real app, run in a thread pool or background task.
        result = model.transcribe(audio_path, **options)
        
        return result
