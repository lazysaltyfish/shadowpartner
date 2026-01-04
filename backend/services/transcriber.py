import whisper
import os
import torch

# Helper to ensure ffmpeg is in path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_BIN = os.path.join(BASE_DIR, "bin") 
if os.path.exists(LOCAL_BIN) and LOCAL_BIN not in os.environ["PATH"]:
    print(f"Adding local bin to PATH: {LOCAL_BIN}")
    os.environ["PATH"] += os.pathsep + LOCAL_BIN

class AudioTranscriber:
    def __init__(self, model_size="base", device=None, fp16=False):
        """
        Initialize the transcriber model.
        
        Args:
            model_size (str): Size of the whisper model (tiny, base, small, medium, large)
            device (str): Device to run the model on ("cpu" or "cuda"). If None, detects automatically.
            fp16 (bool): Whether to use fp16 for inference. 
                         WARNING: fp16=True can cause NaN errors on some GPUs, so default is False for stability.
        """
        self.model_size = model_size
        self.fp16 = fp16
        
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
            
        print(f"Loading Whisper model ({self.model_size}) on {self.device} with fp16={self.fp16}...")
        try:
            self.model = whisper.load_model(self.model_size, device=self.device)
            print("Whisper model loaded.")
        except Exception as e:
            print(f"Error loading Whisper model: {e}")
            self.model = None

    def transcribe(self, audio_path: str, language: str = None):
        """
        Transcribes audio and returns segments with word timestamps.
        """
        if self.model is None:
            raise Exception("Whisper model failed to load.")

        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Ensure we are using absolute path for safety
        audio_path = os.path.abspath(audio_path)

        options = {
            "word_timestamps": True,
            "fp16": self.fp16
        }
        if language:
            options["language"] = language

        # Transcribe
        # Note: This is blocking. In a real app, run in a thread pool or background task.
        result = self.model.transcribe(audio_path, **options)
        
        return result
