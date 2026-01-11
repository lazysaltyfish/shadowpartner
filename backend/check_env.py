try:
    import fastapi  # noqa: F401

    print("fastapi imported successfully")
except ImportError:
    print("fastapi import failed")

try:
    import yt_dlp  # noqa: F401

    print("yt_dlp imported successfully")
except ImportError:
    print("yt_dlp import failed")

try:
    import uvicorn  # noqa: F401

    print("uvicorn imported successfully")
except ImportError:
    print("uvicorn import failed")

try:
    import whisper  # noqa: F401

    print("whisper imported successfully")
except ImportError:
    print("whisper import failed")

try:
    import MeCab  # noqa: F401

    print("MeCab imported successfully")
except ImportError:
    print("MeCab import failed")
