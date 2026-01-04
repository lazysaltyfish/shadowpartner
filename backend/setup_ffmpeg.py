import os
import subprocess
import shutil

def setup_ffmpeg():
    # URL for static build
    url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    bin_dir = os.path.join(base_dir, "bin")
    
    if not os.path.exists(bin_dir):
        os.makedirs(bin_dir)
        
    ffmpeg_exe = os.path.join(bin_dir, "ffmpeg")
    
    if os.path.exists(ffmpeg_exe):
        print(f"FFmpeg found at {ffmpeg_exe}")
        try:
            subprocess.run([ffmpeg_exe, "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print("FFmpeg is operational.")
            return
        except Exception as e:
            print(f"Existing FFmpeg check failed: {e}, reinstalling...")

    print(f"Downloading FFmpeg to {bin_dir}...")
    
    tar_file = os.path.join(bin_dir, "ffmpeg.tar.xz")
    try:
        subprocess.run(["curl", "-L", "-o", tar_file, url], check=True)
    except Exception as e:
        print(f"Download failed: {e}")
        return
    
    print("Extracting...")
    try:
        subprocess.run(["tar", "xf", tar_file, "-C", bin_dir], check=True)
    except Exception as e:
        print(f"Extraction failed: {e}")
        return
    
    # Find the extracted folder
    found = False
    for name in os.listdir(bin_dir):
        if name.startswith("ffmpeg-") and os.path.isdir(os.path.join(bin_dir, name)):
            extracted_dir = os.path.join(bin_dir, name)
            # Move ffmpeg binary
            src = os.path.join(extracted_dir, "ffmpeg")
            if os.path.exists(src):
                if os.path.exists(ffmpeg_exe):
                    os.remove(ffmpeg_exe)
                os.rename(src, ffmpeg_exe)
                found = True
            
            # Move ffprobe
            src_probe = os.path.join(extracted_dir, "ffprobe")
            dst_probe = os.path.join(bin_dir, "ffprobe")
            if os.path.exists(src_probe):
                if os.path.exists(dst_probe):
                    os.remove(dst_probe)
                os.rename(src_probe, dst_probe)
                
            # Cleanup extracted dir
            shutil.rmtree(extracted_dir)
            break
            
    if os.path.exists(tar_file):
        os.remove(tar_file)
    
    if found:
        print(f"FFmpeg installed successfully to {ffmpeg_exe}")
        # Make executable just in case
        os.chmod(ffmpeg_exe, 0o755)
    else:
        print("Failed to find ffmpeg binary in extracted files.")

if __name__ == "__main__":
    setup_ffmpeg()
