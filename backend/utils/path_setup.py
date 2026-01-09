"""
Common path utilities for ShadowPartner backend.
Handles local binary path setup (ffmpeg, deno, etc.)
"""
import os


def setup_local_bin_path():
    """
    Add local bin directory to PATH if it exists.
    This ensures locally installed binaries (ffmpeg, deno) are available.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_bin = os.path.join(base_dir, "bin")

    if os.path.exists(local_bin) and local_bin not in os.environ["PATH"]:
        os.environ["PATH"] = local_bin + os.pathsep + os.environ["PATH"]
        return local_bin

    return None
