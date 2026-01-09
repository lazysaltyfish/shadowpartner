# Subtitle Matching & Warning Design

## Objective
Detect and warn the user when the uploaded reference subtitles (SRT) significantly differ from the audio's content (AI transcription). This prevents users from accidentally using the wrong subtitle file or a completely mismatched version.

## 1. Algorithm Design

We need a fast, global similarity metric. Since we are comparing Japanese text (mostly), character-based comparison is appropriate.

### Inputs
*   `generated_segments`: List of segments from Whisper (AI Transcription).
*   `reference_segments`: List of segments from user's SRT (after linearization).

### Steps
1.  **Text Extraction & Sampling**:
    *   To ensure performance (avoiding O(N*M) on full text for hour-long videos), we will sample the text.
    *   Extract text from the **first 20%**, **middle 20%**, and **last 20%** of the segments (capped at ~2000 characters per chunk to ensure speed).
    *   Concatenate these into `text_gen` and `text_ref`.

2.  **Normalization**:
    *   Remove all whitespace (newlines, spaces).
    *   Remove common punctuation (Japanese and English).
    *   This ensures that formatting differences don't penalize the score.

3.  **Similarity Calculation**:
    *   Use `difflib.SequenceMatcher.ratio()`.
    *   This calculates a value between 0.0 and 1.0.
    *   Formula: `2.0 * M / T` where M is matches and T is total elements.

4.  **Threshold Determination**:
    *   **> 0.5**: Acceptable match. (Likely same content, maybe different translation or timing).
    *   **0.3 - 0.5**: Potential Mismatch. (Heavy editing or very different translation).
    *   **< 0.3**: **Warning Level**. (Likely wrong file, different language, or completely different content).
    *   *Initial Warning Threshold*: **0.3**

## 2. Backend Implementation

### Location
*   Since `backend/services/analyzer.py` is specific to Japanese morphological analysis, we should create a lightweight utility for this check to avoid circular deps or clutter.
*   We can place this logic in a new method `calculate_similarity` in `backend/services/aligner.py` (since it deals with aligning/comparing) or simply as a helper in `backend/main.py` if it remains simple.
*   **Decision**: Add a helper function `check_subtitle_similarity` in `backend/main.py` (or a utility module) for now to keep it close to the orchestration logic.

### Integration Point
In `backend/main.py`, inside `process_audio_task`:
1.  After `transcriber.transcribe` (Step 2).
2.  After `load_subtitle` and `linearize` (Step 3).
3.  Before `aligner.calibrate`.
4.  Run the check. If score < threshold, add a warning string to a `warnings` list.

## 3. API Response Updates

Modify `VideoResponse` in `backend/main.py` to include a warnings field.

```python
class VideoResponse(BaseModel):
    video_id: str
    title: str
    segments: List[Segment]
    metrics: Optional[ProcessingMetrics] = None
    has_word_timestamps: bool = True
    warnings: List[str] = []  # New field
```

## 4. Frontend Presentation

*   **Location**: Top of the result page or right below the video player.
*   **Component**: An amber/yellow alert banner.
*   **Content**: "⚠️ Low subtitle match detected (Similarity: 25%). Please check if you uploaded the correct subtitle file."
*   **Behavior**: Dismissible by the user.

## 5. Future Optimizations (If `difflib` is too slow)
*   Switch to `rapidfuzz` (requires adding dependency) for C++ optimized Levenshtein.
*   Use Jaccard Similarity on Character N-Grams (very fast, O(N)).