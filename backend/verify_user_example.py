import sys
import os

# Ensure backend directory is in python path to import services
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.subtitle_linearizer import SubtitleLinearizer

USER_DATA = """
1
00:00:00,960 --> 00:00:09,070
 
最高です。よ、ありがとうございます。

2
00:00:09,070 --> 00:00:09,080
 
 

3
00:00:09,080 --> 00:00:14,350
 
いや、本当にすごいなと思って、この2つ

4
00:00:14,350 --> 00:00:14,360
いや、本当にすごいなと思って、この2つ
 

5
00:00:14,360 --> 00:00:17,590
いや、本当にすごいなと思って、この2つ
のアーティストが集うこの会場で2つの

6
00:00:17,590 --> 00:00:17,600
のアーティストが集うこの会場で2つの
 

7
00:00:17,600 --> 00:00:20,990
のアーティストが集うこの会場で2つの
アーティストのファンが都どうこの会場で

8
00:00:20,990 --> 00:00:21,000
アーティストのファンが都どうこの会場で
 

9
00:00:21,000 --> 00:00:24,509
アーティストのファンが都どうこの会場で
なんかこんなに1つになってみんなで一緒

10
00:00:24,509 --> 00:00:24,519
なんかこんなに1つになってみんなで一緒
 

11
00:00:24,519 --> 00:00:28,070
なんかこんなに1つになってみんなで一緒
に飛び跳ねたり歌ったり楽しい時間を一緒

12
00:00:28,070 --> 00:00:28,080
に飛び跳ねたり歌ったり楽しい時間を一緒
 

13
00:00:28,080 --> 00:00:32,310
に飛び跳ねたり歌ったり楽しい時間を一緒
に作っているって感覚がすごく今実感でき

14
00:00:32,310 --> 00:00:32,320
に作っているって感覚がすごく今実感でき
 

15
00:00:32,320 --> 00:00:35,470
に作っているって感覚がすごく今実感でき
ててなんか

16
00:00:35,470 --> 00:00:35,480
ててなんか
"""

def main():
    linearizer = SubtitleLinearizer()
    
    # Parse
    # Note: parse_srt filters out empty segments
    raw_segments = linearizer.parse_srt(USER_DATA)
    print(f"Original valid segments count: {len(raw_segments)}")
    
    # Linearize
    linearized_segments = linearizer.linearize(raw_segments)
    print(f"Linearized segments count: {len(linearized_segments)}")
    
    print("\n--- Linearized Content ---")
    full_text = ""
    for seg in linearized_segments:
        # Format time to string for display
        print(f"[{seg['start']:.2f} -> {seg['end']:.2f}] {seg['text']}")
        full_text += seg['text']
        
    print("\n--- Combined Text ---")
    print(full_text)

if __name__ == "__main__":
    main()