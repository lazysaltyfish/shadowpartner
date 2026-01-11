import os
import re

import torch
import whisper

from utils.logger import get_logger
from utils.path_setup import setup_local_bin_path

# Setup logger
logger = get_logger(__name__)

# Setup local bin path
setup_local_bin_path()


def parse_srt_time(time_str: str) -> float:
    """Parse SRT timestamp (HH:MM:SS,mmm) to seconds."""
    # Handle both comma and period as decimal separator
    time_str = time_str.replace(',', '.')
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def parse_srt(content: str) -> list:
    """
    Parse SRT subtitle content and return segments in Standard Segment format.
    
    Returns:
        list: List of segment dicts with 'text', 'start', 'end', and 'words' keys.
    """
    segments = []
    # Split by double newline to get subtitle blocks
    # Handle different line endings
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    blocks = re.split(r'\n\n+', content.strip())
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2:
            continue
            
        # First line is the index (skip it)
        # Second line is the timestamp
        # Remaining lines are the text
        
        # Find the timestamp line (contains ' --> ')
        timestamp_idx = -1
        for i, line in enumerate(lines):
            if ' --> ' in line:
                timestamp_idx = i
                break
        
        if timestamp_idx == -1:
            continue
            
        timestamp_line = lines[timestamp_idx]
        text_lines = lines[timestamp_idx + 1:]
        
        # Parse timestamp: "00:00:01,000 --> 00:00:04,000"
        match = re.match(
            r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})',
            timestamp_line
        )
        if not match:
            continue
            
        start_time = parse_srt_time(match.group(1))
        end_time = parse_srt_time(match.group(2))
        text = ' '.join(text_lines).strip()
        
        if not text:
            continue
        
        # Create segment in Standard Segment format
        # Note: We don't have word-level timestamps from SRT, so words list will be empty
        # The aligner will handle this case via calibration
        segment = {
            'text': text,
            'start': start_time,
            'end': end_time,
            'words': []  # No word-level timestamps available from SRT
        }
        segments.append(segment)
    
    return segments


class AudioTranscriber:
    def __init__(self, model_size="base", device=None, fp16=False):
        """
        Initialize the transcriber model.
        
        Args:
            model_size (str): Size of the whisper model (tiny, base, small, medium, large)
            device (str): Device to run the model on ("cpu" or "cuda").
                         If None, detects automatically.
            fp16 (bool): Whether to use fp16 for inference. 
                         WARNING: fp16=True can cause NaN errors on some GPUs,
                         so default is False for stability.
        """
        self.model_size = model_size
        self.fp16 = fp16
        
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
            
        logger.info(
            f"Loading Whisper model ({self.model_size}) on {self.device} "
            f"with fp16={self.fp16}"
        )
        try:
            self.model = whisper.load_model(self.model_size, device=self.device)
            logger.info("Whisper model loaded successfully")
        except Exception as e:
            logger.error(f"Error loading Whisper model: {e}", exc_info=True)
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

        logger.info(f"Starting transcription for: {audio_path}")
        result = self.model.transcribe(audio_path, **options)
        logger.info(f"Transcription completed: {len(result.get('segments', []))} segments")

        return result

    def load_subtitle(self, subtitle_path: str = None, subtitle_content: str = None) -> dict:
        """
        Load subtitle from file or content string and return in Standard Segment format.
        
        Args:
            subtitle_path (str): Path to the subtitle file (SRT format).
            subtitle_content (str): Raw subtitle content string (SRT format).
            
        Returns:
            dict: Result dict with 'segments' key containing parsed subtitle segments.
            
        Note:
            Either subtitle_path or subtitle_content must be provided.
            If both are provided, subtitle_content takes precedence.
        """
        if subtitle_content is None and subtitle_path is None:
            raise ValueError("Either subtitle_path or subtitle_content must be provided.")
        
        if subtitle_content is None:
            if not os.path.exists(subtitle_path):
                raise FileNotFoundError(f"Subtitle file not found: {subtitle_path}")
            
            # Try different encodings
            encodings = ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'shift_jis', 'latin-1']
            content = None
            for encoding in encodings:
                try:
                    with open(subtitle_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    logger.debug(f"Successfully decoded subtitle with encoding: {encoding}")
                    break
                except UnicodeDecodeError:
                    logger.debug(f"Failed to decode with encoding: {encoding}")
                    continue

            if content is None:
                logger.error(f"Could not decode subtitle file with any supported encoding: {subtitle_path}")
                raise ValueError(f"Could not decode subtitle file with any supported encoding: {subtitle_path}")
            
            subtitle_content = content
        
        segments = parse_srt(subtitle_content)

        if not segments:
            logger.error("No valid subtitle segments found in the provided content")
            raise ValueError("No valid subtitle segments found in the provided content.")

        logger.info(f"Loaded {len(segments)} subtitle segments from user-provided file")

        return {'segments': segments}
