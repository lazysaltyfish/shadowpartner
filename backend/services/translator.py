import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from google import genai

from settings import get_settings
from utils.logger import get_logger
from utils.resilience import retry_on_http_errors

# Setup logger
logger = get_logger(__name__)

DEFAULT_TRANSLATION_TIMEOUT_SECONDS = 60
DEFAULT_TRANSLATION_TIMEOUT_RETRIES = 2
DEFAULT_TRANSLATION_TIMEOUT_BACKOFF_SECONDS = 2


class Translator:
    def __init__(self, executor: Optional[ThreadPoolExecutor] = None):
        # Read API key at initialization time (settings loads .env once)
        settings = get_settings()
        api_key = settings.gemini_api_key

        self.client = None
        if api_key:
            self.client = genai.Client(api_key=api_key)
        self.available = bool(api_key)
        self.model_id = settings.gemini_model_id
        self.chunk_size = settings.translate_batch_chunk_size
        self.executor = executor
        self.request_timeout_seconds = DEFAULT_TRANSLATION_TIMEOUT_SECONDS
        logger.info(
            f"Translator initialized with model: {self.model_id}, chunk size: {self.chunk_size}"
        )

    def set_executor(self, executor: Optional[ThreadPoolExecutor]) -> None:
        self.executor = executor

    @retry_on_http_errors()
    def _generate_content(self, prompt: str) -> str:
        response = self.client.models.generate_content(
            model=self.model_id,
            contents=prompt,
        )
        return response.text.strip()

    def translate(self, text: str, target_lang: str = "Chinese") -> str:
        if not self.available:
            logger.warning("Gemini API Key missing. Skipping translation.")
            return "[需要配置 GEMINI_API_KEY]"

        if not text.strip():
            return ""

        logger.info(f"Starting single translation. Length: {len(text)}")
        try:
            prompt = (
                f"Translate the following Japanese text to {target_lang}. "
                f"Only output the translation, no explanation:\n\n{text}"
            )
            response_text = self._generate_content(prompt)
            logger.info("Single translation completed.")
            return response_text
        except Exception as e:
            logger.error(f"Gemini translation error after retries: {e}")
            return f"[翻译失败: {str(e)}]"

    def _process_chunk(self, chunk: List[str], chunk_index: int, target_lang: str) -> List[str]:
        """
        Process a single chunk of text for translation.
        """
        logger.info(f"Processing chunk {chunk_index + 1} ({len(chunk)} items)...")

        # Format:
        # 1. <text>
        # 2. <text>
        joined_text = "\n".join([f"{idx + 1}. {t}" for idx, t in enumerate(chunk)])

        prompt = (
            f"Translate the following Japanese sentences to {target_lang} "
            "(Simplified Chinese). "
            f"Output strictly as a numbered list corresponding to the input "
            "numbers (e.g., '1. translation'). "
            f"Do not merge sentences. Maintain the original tone.\n\n{joined_text}"
        )

        chunk_results = []
        try:
            response_text = self._generate_content(prompt)

            # Parse logic
            lines = response_text.split("\n")
            chunk_map = {}
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                # Look for "1. " pattern
                parts = line.split(".", 1)
                if len(parts) >= 2 and parts[0].strip().isdigit():
                    idx = int(parts[0].strip()) - 1
                    trans = parts[1].strip()
                    chunk_map[idx] = trans

            # Reconstruct chunk results
            for j in range(len(chunk)):
                chunk_results.append(chunk_map.get(j, "[翻译缺失]"))

        except Exception as e:
            logger.error(
                "Gemini batch translation error in chunk %s after retries: %s",
                chunk_index + 1,
                e,
            )
            # Fallback: append error messages for this chunk
            chunk_results.extend([f"[翻译错误: {str(e)}]"] * len(chunk))

        return chunk_results

    async def _translate_chunk_async(
        self,
        chunk: List[str],
        chunk_index: int,
        target_lang: str,
    ) -> List[str]:
        loop = asyncio.get_running_loop()
        total_attempts = DEFAULT_TRANSLATION_TIMEOUT_RETRIES + 1
        for attempt in range(total_attempts):
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(
                        self.executor,
                        self._process_chunk,
                        chunk,
                        chunk_index,
                        target_lang,
                    ),
                    timeout=self.request_timeout_seconds,
                )
            except asyncio.TimeoutError:
                if attempt + 1 >= total_attempts:
                    logger.error(
                        "Gemini batch translation timed out for chunk %s after %s attempts",
                        chunk_index + 1,
                        total_attempts,
                    )
                    return ["[翻译超时]"] * len(chunk)
                backoff = DEFAULT_TRANSLATION_TIMEOUT_BACKOFF_SECONDS * (2**attempt)
                logger.warning(
                    "Gemini batch translation timed out for chunk %s (attempt %s/%s). "
                    "Retrying in %ss",
                    chunk_index + 1,
                    attempt + 1,
                    total_attempts,
                    backoff,
                )
                await asyncio.sleep(backoff)
        return ["[翻译超时]"] * len(chunk)

    async def translate_batch(self, texts: List[str], target_lang: str = "Chinese") -> List[str]:
        """
        Translates a list of texts concurrently to save time.
        """
        if not self.available:
            logger.warning("Gemini API Key missing. Skipping batch translation.")
            return ["[需要配置 GEMINI_API_KEY]"] * len(texts)

        if not texts:
            return []

        logger.info(f"Starting concurrent batch translation. Total items: {len(texts)}")

        tasks = []

        for i in range(0, len(texts), self.chunk_size):
            chunk = texts[i : i + self.chunk_size]
            chunk_index = i // self.chunk_size
            tasks.append(self._translate_chunk_async(chunk, chunk_index, target_lang))

        # Wait for all chunks to complete
        chunk_results_list = await asyncio.gather(*tasks)

        # Flatten results
        all_results = []
        for chunk_res in chunk_results_list:
            all_results.extend(chunk_res)

        logger.info("Batch translation completed.")
        return all_results
