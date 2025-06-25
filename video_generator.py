import os
import json
import requests
import shutil
from moviepy.editor import *
from moviepy.audio.fx.all import volumex
import azure.cognitiveservices.speech as speechsdk

# === CONFIGURATION ===
PEXELS_API_KEY = 'SAVFMWYY1ki2FieFyWJSq5gUVci3uhmSXqV3LGTl0ISieAS6IGCYdeg0'
SPEECH_KEY = 'BgH1C7YmFgudKD5FXEyTKP94D2roS4lRTNmsgyiBrKDh4cLFVmSvJQQJ99BFACGhslBXJ3w3AAAYACOGd80X'
REGION = 'centralindia'

SCENES_DIR = 'scenes'
OUT_DIR = 'output'
BG_MUSIC = 'bg_music.mp3'
MUTED_OVERLAY = 'Muted_Video.mp4'
IMAGE_COUNT_PER_SCENE = 3

os.makedirs(OUT_DIR, exist_ok=True)

# === Download images ===
def download_images(query, scene_index, image_dir):
    scene_dir = os.path.join(image_dir, f"scene{scene_index+1}")
    os.makedirs(scene_dir, exist_ok=True)

    url = f"https://api.pexels.com/v1/search?query={query}&per_page={IMAGE_COUNT_PER_SCENE}&orientation=portrait"
    headers = {"Authorization": PEXELS_API_KEY}
    response = requests.get(url, headers=headers)
    data = response.json()
    photos = data.get('photos', [])

    if not photos:
        print(f"❌ No images found for: {query}")
        return

    for i, photo in enumerate(photos[:IMAGE_COUNT_PER_SCENE]):
        image_url = photo['src'].get('portrait') or photo['src'].get('original')
        img_data = requests.get(image_url).content
        with open(os.path.join(scene_dir, f'img{i+1}.jpg'), 'wb') as f:
            f.write(img_data)

    print(f"✅ Downloaded {len(photos)} images for '{query}' → {scene_dir}")

# === Azure TTS ===
def generate_tts(text, out_path):
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=REGION)
    audio_config = speechsdk.audio.AudioOutputConfig(filename=out_path)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)

    ssml = f"""
    <speak version='1.0' xml:lang='te-IN'>
        <voice name='te-IN-MohanNeural'>
            <prosody rate='+30.00%' pitch='+5%'>{text}</prosody>
        </voice>
    </speak>
    """
    result = synthesizer.speak_ssml_async(ssml).get()
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        raise Exception(f"TTS failed: {result.reason}")

# === Process scenes ===
SCENES_FILES = [f for f in os.listdir(SCENES_DIR) if f.endswith('.json')]

for scene_file in SCENES_FILES:
    base_name = os.path.splitext(scene_file)[0]
    print(f"\n🚀 Processing {scene_file}...")

    SCENES_FILE = os.path.join(SCENES_DIR, scene_file)
    IMAGE_DIR = f'images_{base_name}'
    AUDIO_DIR = f'audio_{base_name}'
    OUTPUT_SUBDIR = os.path.join(OUT_DIR, base_name)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(OUTPUT_SUBDIR, exist_ok=True)
    FULL_AUDIO = os.path.join(AUDIO_DIR, 'full_audio.mp3')
    OUT_VIDEO = os.path.join(OUTPUT_SUBDIR, 'final_video.mp4')

    with open(SCENES_FILE, 'r', encoding='utf-8') as f:
        content = json.load(f)

    scenes = content.get("scenes", [])
    if not scenes:
        print(f"⚠️ No scenes found in {scene_file}")
        continue

    scene_texts = [scene.get('text', '') for scene in scenes]
    full_script = ' '.join(scene_texts)

    print("🖼️ Downloading images...")
    for idx, scene in enumerate(scenes):
        keyword = scene.get("image_keyword", "")
        if keyword:
            download_images(keyword, idx, IMAGE_DIR)

    print("🔊 Generating TTS...")
    generate_tts(full_script, FULL_AUDIO)
    tts_audio = AudioFileClip(FULL_AUDIO)
    total_audio_duration = tts_audio.duration

    scene_word_counts = [len(text.split()) for text in scene_texts]
    total_words = sum(scene_word_counts)
    scene_durations = [(count / total_words) * total_audio_duration for count in scene_word_counts]

    print("🎞️ Creating image-based scene clips...")
    scene_clips = []
    for idx, (scene, duration) in enumerate(zip(scenes, scene_durations)):
        scene_path = os.path.join(IMAGE_DIR, f"scene{idx+1}")
        images = sorted([
            os.path.join(scene_path, f)
            for f in os.listdir(scene_path)
            if f.lower().endswith(('.jpg', '.jpeg', '.png'))
        ])

        if not images:
            raise Exception(f"No images found for scene {idx+1}")

        per_img_duration = max(duration / len(images), 2.5)

        img_clips = [
            ImageClip(img)
                .resize(height=1920)
                .crop(width=1080, height=1920, x_center=540, y_center=960)
                .set_duration(per_img_duration)
                .set_fps(24)
            for img in images
        ]

        scene_video = concatenate_videoclips(img_clips).set_duration(duration)
        scene_clips.append(scene_video)

    print("📹 Combining scenes...")
    video_without_audio = concatenate_videoclips(scene_clips, method="compose").set_duration(tts_audio.duration)

    # === Overlay background video ===
    overlay_video = VideoFileClip(MUTED_OVERLAY, audio=False)

    # Step 1: Resize by height to 1920 (this makes width > 1080)
    overlay_video = overlay_video.resize(height=1920)

    # Step 2: Crop width to center-crop to 1080x1920 (portrait)
    overlay_video = overlay_video.crop(width=1080, x_center=overlay_video.w / 2)

    # Step 3: Loop to match the TTS audio duration
    overlay_video = overlay_video.loop(duration=tts_audio.duration).set_duration(tts_audio.duration)

    # Step 4: Set slight opacity to see image scenes over it
    overlay_video = overlay_video.set_opacity(0.50)

    # Make image layer semi-transparent
    image_layer = video_without_audio.set_opacity(0.80).set_position("center")

    # Combine layers
    final_visual = CompositeVideoClip([overlay_video, image_layer])

    print("🎵 Adding background music + TTS audio...")
    bg_music = AudioFileClip(BG_MUSIC).volumex(0.45).audio_loop(duration=tts_audio.duration)
    final_audio = CompositeAudioClip([bg_music, tts_audio])
    final_video = final_visual.set_audio(final_audio)

    print(f"💾 Saving final video → {OUT_VIDEO}")
    final_video.write_videofile(OUT_VIDEO, codec="libx264", audio_codec="aac", fps=24)

    print(f"✅ Done: {OUT_VIDEO}")

    shutil.rmtree(IMAGE_DIR)
    shutil.rmtree(AUDIO_DIR)
