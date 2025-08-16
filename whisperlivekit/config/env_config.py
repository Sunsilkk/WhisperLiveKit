import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

HF_TOKEN = os.getenv("HF_TOKEN")
HF_CACHE_DIR = os.getenv("HF_CACHE_DIR")
WHISPER_CACHE_DIR = os.getenv("WHISPER_CACHE_DIR")
MODEL_CACHE_DIR = os.getenv("MODEL_CACHE_DIR")

# Set HuggingFace environment variables if provided
if HF_TOKEN:
    os.environ["HUGGINGFACE_HUB_TOKEN"] = HF_TOKEN
if HF_CACHE_DIR:
    os.environ["HF_HOME"] = HF_CACHE_DIR
    os.environ["HUGGINGFACE_HUB_CACHE"] = HF_CACHE_DIR
