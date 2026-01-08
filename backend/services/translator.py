import os
import asyncio
from google import genai
from typing import List
import time
import logging

# Setup Logger
logger = logging.getLogger(__name__)
# Ensure logging level is set to at least INFO so we can see the logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Setup API Key from environment variable
# Note: In main.py we load dotenv, so this should be populated if main.py is entry point.
# If running standalone, might need load_dotenv() here too.
API_KEY = os.environ.get("GEMINI_API_KEY")

class Translator:
    def __init__(self):
        self.client = None
        if API_KEY:
            self.client = genai.Client(api_key=API_KEY)
        self.available = bool(API_KEY)
        self.model_id = os.environ.get("GEMINI_MODEL_ID", "gemini-3-flash-preview")
        self.chunk_size = int(os.environ.get("TRANSLATE_BATCH_CHUNK_SIZE", 50))
        logger.info(f"Translator initialized with model: {self.model_id}, chunk size: {self.chunk_size}")

    def translate(self, text: str, target_lang: str = "Chinese") -> str:
        if not self.available:
            logger.warning("Gemini API Key missing. Skipping translation.")
            return "[需要配置 GEMINI_API_KEY]"
        
        if not text.strip():
            return ""

        logger.info(f"Starting single translation. Length: {len(text)}")
        try:
            prompt = f"Translate the following Japanese text to {target_lang}. Only output the translation, no explanation:\n\n{text}"
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt
            )
            logger.info("Single translation completed.")
            return response.text.strip()
        except Exception as e:
            logger.error(f"Gemini translation error: {e}")
            return f"[翻译失败: {str(e)}]"
            
    def _process_chunk(self, chunk: List[str], chunk_index: int, target_lang: str) -> List[str]:
        """
        Process a single chunk of text for translation.
        """
        logger.info(f"Processing chunk {chunk_index + 1} ({len(chunk)} items)...")
        
        # Format:
        # 1. <text>
        # 2. <text>
        joined_text = "\n".join([f"{idx+1}. {t}" for idx, t in enumerate(chunk)])
        
        prompt = (
            f"Translate the following Japanese sentences to {target_lang} (Simplified Chinese). "
            f"Output strictly as a numbered list corresponding to the input numbers (e.g., '1. translation'). "
            f"Do not merge sentences. Maintain the original tone.\n\n{joined_text}"
        )
        
        chunk_results = []
        try:
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt
            )
            response_text = response.text.strip()
            
            # Parse logic
            lines = response_text.split('\n')
            chunk_map = {}
            for line in lines:
                line = line.strip()
                if not line: continue
                # Look for "1. " pattern
                parts = line.split('.', 1)
                if len(parts) >= 2 and parts[0].strip().isdigit():
                    idx = int(parts[0].strip()) - 1
                    trans = parts[1].strip()
                    chunk_map[idx] = trans
            
            # Reconstruct chunk results
            for j in range(len(chunk)):
                chunk_results.append(chunk_map.get(j, "[翻译缺失]"))
                
        except Exception as e:
            logger.error(f"Gemini batch translation error in chunk {chunk_index + 1}: {e}")
            # Fallback: append error messages for this chunk
            chunk_results.extend([f"[翻译错误: {str(e)}]"] * len(chunk))
            
        return chunk_results

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
        
        loop = asyncio.get_running_loop()
        tasks = []
        
        for i in range(0, len(texts), self.chunk_size):
            chunk = texts[i:i + self.chunk_size]
            chunk_index = i // self.chunk_size
            # Run the synchronous _process_chunk in a thread pool
            tasks.append(loop.run_in_executor(None, self._process_chunk, chunk, chunk_index, target_lang))
            
        # Wait for all chunks to complete
        chunk_results_list = await asyncio.gather(*tasks)
        
        # Flatten results
        all_results = []
        for chunk_res in chunk_results_list:
            all_results.extend(chunk_res)
            
        logger.info("Batch translation completed.")
        return all_results
