# Hybrid Timestamp Calibration Design

## 1. Terminology

To ensure clarity in the codebase and documentation, we will strictly use the following terms:

*   **Reference Subtitle:** The "ground truth" text provided by the user (upload) or retrieved from an external source (e.g., YouTube captions). These usually have accurate sentence/segment-level timestamps but lack word-level precision.
*   **Generated Subtitle:** The output from the AI model (Whisper). These contain word-level timestamps (`start`, `end` for each word) but the text content might differ slightly from the Reference Subtitle due to hallucination or recognition errors.

## 2. Objective

The goal is to produce a **Calibrated Subtitle** that possesses:
1.  **Text Content:** Exactly matching the *Reference Subtitle* (as it is assumed to be the correct script).
2.  **Timestamps:** Enhanced with word-level precision derived from the *Generated Subtitle*.

## 3. Workflow

1.  **Input:** Audio/Video file + Optional Reference Subtitle file (SRT).
2.  **Generation Phase:**
    *   **Always** run the AI Transcriber (Whisper) on the audio to produce the *Generated Subtitle* with word timestamps.
    *   If a *Reference Subtitle* file is provided, parse it into segments.
3.  **Calibration Phase (if Reference Subtitle exists):**
    *   Perform **Hybrid Timestamp Calibration** to map the precise timing from the *Generated Subtitle* onto the text of the *Reference Subtitle*.
4.  **Analysis Phase:**
    *   Run morphological analysis (MeCab) on the text.
    *   If calibrated, map the calibrated word timestamps to the MeCab tokens.
    *   If no Reference Subtitle was provided, use the *Generated Subtitle* directly and map its timestamps to MeCab tokens (existing logic).

## 4. Calibration Algorithm

The algorithm bridges the gap between the *Generated* timing and *Reference* text.

### Step 1: Flatten and Prepare
*   **Generated Source:** Flatten the *Generated Subtitle* segments -> words -> characters.
    *   Each character gets an estimated `start` and `end` time (interpolated from its parent word's duration).
*   **Reference Source:** Flatten the *Reference Subtitle* segments -> characters.
    *   Keep track of which Segment each character belongs to (to enforce segment boundaries later).

### Step 2: Alignment (Diff)
*   Use `difflib.SequenceMatcher` to align the `Generated String` vs. `Reference String`.
*   **Matches:** For matching characters, transfer the `start` and `end` timestamps from the *Generated* character to the *Reference* character.
*   **Mismatches:** Leave *Reference* characters with empty timestamps for now.

### Step 3: Interpolation & Boundary Constraints
*   Iterate through the *Reference* characters.
*   **Gap Filling:** Linear interpolation for characters without timestamps, using the nearest valid timestamps.
*   **Segment Constraints (Crucial):**
    *   Ensure that any character belonging to Reference Segment `S` has:
        *   `char.start >= S.start`
        *   `char.end <= S.end`
    *   *Logic:* If the projected AI timestamp is outside the manual segment bounds, clamp it to the bounds. This ensures the words light up when the sentence is actually visible, even if AI timing drifted.

### Step 4: Re-grouping
*   Group the timestamped *Reference* characters back into words (Mecab tokens).
*   The `start` of a token is the `start` of its first character.
*   The `end` of a token is the `end` of its last character.

## 5. Implementation Plan

### `backend/services/aligner.py`
*   Add `calibrate(reference_segments, generated_segments)` method.
*   Refactor the existing `align` method (which aligns Whisper Words -> Mecab Tokens) to be a specialized case or usage of this logic, or keep them separate but share the character-level interpolation logic.
    *   *Decision:* The new `calibrate` will operate at a higher level (Segment to Segment alignment) before MeCab analysis. Or, simpler:
    *   Actually, we can pass the *Generated Words* list and the *Reference Text* to a new alignment function that returns "Timed Reference Words".
    *   Then, we pass these "Timed Reference Words" to the existing `align` function (which maps Words -> Mecab Tokens).

### `backend/main.py`
*   Update `process_audio_task`:
    *   Remove the `if subtitle_path: skip AI` logic.
    *   Execute AI transcription in parallel or sequence.
    *   Call the new calibration logic.
