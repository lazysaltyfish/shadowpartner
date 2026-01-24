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
