import os
import platform
import shutil
import subprocess
import tarfile
import zipfile


def setup_ffmpeg():
    system = platform.system()
    machine = platform.machine().lower()
    
    print(f"Detected System: {system}, Machine: {machine}")

    # Determine URL based on OS
    if system == "Linux":
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        archive_name = "ffmpeg.tar.xz"
    elif system == "Windows":
        url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        archive_name = "ffmpeg.zip"
    elif system == "Darwin": # macOS
        url = "https://evermeet.cx/ffmpeg/ffmpeg-6.0.zip" # Example URL, might need dynamic checking
        print(
            "MacOS automatic setup not fully implemented, please install ffmpeg manually "
            "(e.g. brew install ffmpeg)"
        )
        return
    else:
        print(f"Unsupported OS: {system}")
        return
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    bin_dir = os.path.join(base_dir, "bin")
    
    if not os.path.exists(bin_dir):
        os.makedirs(bin_dir)
        
    ffmpeg_exe_name = "ffmpeg.exe" if system == "Windows" else "ffmpeg"
    ffprobe_exe_name = "ffprobe.exe" if system == "Windows" else "ffprobe"
    
    ffmpeg_exe = os.path.join(bin_dir, ffmpeg_exe_name)
    ffprobe_exe = os.path.join(bin_dir, ffprobe_exe_name)
    
    if os.path.exists(ffmpeg_exe):
        print(f"FFmpeg found at {ffmpeg_exe}")
        try:
            subprocess.run(
                [ffmpeg_exe, "-version"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            print("FFmpeg is operational.")
            return
        except Exception as e:
            print(f"Existing FFmpeg check failed: {e}, reinstalling...")

    print(f"Downloading FFmpeg to {bin_dir}...")
    
    archive_file = os.path.join(bin_dir, archive_name)
    try:
        if shutil.which("curl"):
             subprocess.run(["curl", "-L", "-o", archive_file, url], check=True)
        else:
            import urllib.request
            urllib.request.urlretrieve(url, archive_file)
            print("Downloaded using urllib.")
    except Exception as e:
        print(f"Download failed: {e}")
        return
    
    print("Extracting...")
    try:
        if archive_name.endswith(".zip"):
             with zipfile.ZipFile(archive_file, 'r') as zip_ref:
                zip_ref.extractall(bin_dir)
        else:
             # Python's tarfile supports xz
             with tarfile.open(archive_file, "r:xz") as tar_ref:
                tar_ref.extractall(bin_dir)
    except Exception as e:
        print(f"Extraction failed: {e}")
        # Try system tar if python fails (sometimes needed for specific compression)
        if system != "Windows":
             try:
                 subprocess.run(["tar", "xf", archive_file, "-C", bin_dir], check=True)
                 print("Extracted using system tar.")
             except Exception as e2:
                 print(f"System tar extraction also failed: {e2}")
                 return
        else:
             return
    
    # Find the extracted folder and move binaries
    found = False
    for root, dirs, files in os.walk(bin_dir):
        if ffmpeg_exe_name in files:
            src_ffmpeg = os.path.join(root, ffmpeg_exe_name)
            
            # If we found it in a subdirectory (not directly in bin_dir if we already moved it)
            if os.path.dirname(src_ffmpeg) != bin_dir:
                 if os.path.exists(ffmpeg_exe):
                    os.remove(ffmpeg_exe)
                 shutil.move(src_ffmpeg, ffmpeg_exe)
                 found = True

        if ffprobe_exe_name in files:
            src_ffprobe = os.path.join(root, ffprobe_exe_name)
            if os.path.dirname(src_ffprobe) != bin_dir:
                if os.path.exists(ffprobe_exe):
                    os.remove(ffprobe_exe)
                shutil.move(src_ffprobe, ffprobe_exe)

    # Cleanup: Remove subdirectories created during extraction
    for item in os.listdir(bin_dir):
        item_path = os.path.join(bin_dir, item)
        if os.path.isdir(item_path):
             shutil.rmtree(item_path)
             
    if os.path.exists(archive_file):
        os.remove(archive_file)
    
    if found or os.path.exists(ffmpeg_exe):
        print(f"FFmpeg installed successfully to {ffmpeg_exe}")
        # Make executable just in case (Linux/Mac)
        if system != "Windows":
            os.chmod(ffmpeg_exe, 0o755)
            if os.path.exists(ffprobe_exe):
                 os.chmod(ffprobe_exe, 0o755)
    else:
        print("Failed to find ffmpeg binary in extracted files.")

if __name__ == "__main__":
    setup_ffmpeg()


