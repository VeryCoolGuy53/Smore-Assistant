import os
import subprocess
import tempfile
from pathlib import Path
from tools.base import Tool
from core.tools import register_tool

# Set up cuDNN library path for faster-whisper GPU support
VENV_PATH = Path(__file__).parent.parent / "venv"
CUDNN_LIB = VENV_PATH / "lib/python3.12/site-packages/nvidia/cudnn/lib"
CUBLAS_LIB = VENV_PATH / "lib/python3.12/site-packages/nvidia/cublas/lib"

if CUDNN_LIB.exists():
    os.environ['LD_LIBRARY_PATH'] = f"{CUDNN_LIB}:{CUBLAS_LIB}:" + os.environ.get('LD_LIBRARY_PATH', '')

# Force STT to use GPU 1 (RTX 3060) - keep GPU 0 (4070 Ti) for LLM inference
os.environ['CUDA_VISIBLE_DEVICES'] = '1'

# Lazy-loaded Whisper model
_whisper_model = None

# Audio device config
MIC_DEVICE = "plughw:1,0"
SAMPLE_RATE = 16000

def get_whisper_model():
    """Lazy load the Whisper model to avoid slow startup."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel('medium', device='cuda', compute_type='float16')
    return _whisper_model


def record_audio(duration: int = 5) -> str:
    """Record audio from microphone."""
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        output_path = f.name
    
    cmd = [
        'arecord',
        '-D', MIC_DEVICE,
        '-f', 'S16_LE',
        '-r', str(SAMPLE_RATE),
        '-c', '1',
        '-d', str(duration),
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Recording failed: {result.stderr}")
    
    return output_path


def transcribe_audio(audio_path: str) -> str:
    """Transcribe audio file using Whisper."""
    model = get_whisper_model()
    segments, info = model.transcribe(audio_path, language='en')
    
    text = ' '.join(segment.text.strip() for segment in segments)
    return text.strip()


@register_tool
class ListenTool(Tool):
    name = "listen"
    description = "Record audio from microphone and transcribe to text. Params: duration in seconds (default 5, max 30)"

    async def run(self, params: str) -> str:
        try:
            duration = int(params.strip()) if params.strip() else 5
            duration = min(max(1, duration), 30)  # Clamp between 1-30 seconds
        except ValueError:
            duration = 5
        
        try:
            audio_path = record_audio(duration)
            text = transcribe_audio(audio_path)
            
            # Clean up temp file
            os.unlink(audio_path)
            
            if not text:
                return "[No speech detected]"
            
            return f"Heard: {text}"
            
        except Exception as e:
            return f"Error: {str(e)}"


@register_tool
class TranscribeTool(Tool):
    name = "transcribe"
    description = "Transcribe an existing audio file. Params: path to audio file"

    async def run(self, params: str) -> str:
        audio_path = params.strip()
        
        if not os.path.exists(audio_path):
            return f"Error: File not found: {audio_path}"
        
        try:
            text = transcribe_audio(audio_path)
            
            if not text:
                return "[No speech detected in file]"
            
            return f"Transcription: {text}"
            
        except Exception as e:
            return f"Error: {str(e)}"
