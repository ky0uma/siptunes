from typing import Dict, Any
import threading
import logging
import ffmpeg
import time
import queue

from app.const import (
    SAMPLERATE,
    CHANNELCOUNT,
    SOUND_DIR
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class FFmpegStreamer(threading.Thread):
    def __init__(
        self,
        audio_queue: queue.Queue,
        song_queue: queue.Queue,
        chunk_size: int,
        buffer_size: int,
        dtmf_maps: Dict[str, str],
        cur_theme: str,
        end_event: threading.Event
    ) -> None:
        super().__init__()
        logger.info(f"Initializing class: {self.__class__.__name__}")
        self.audio_queue = audio_queue
        self.song_queue = song_queue
        self.chunk_size = chunk_size
        self.buffer_size = buffer_size
        self.stop_event = threading.Event()
        self.dtmf_maps = dtmf_maps
        self.cur_theme = cur_theme
        self.end_event = end_event
        self.process: Any = None

    def start_stream(self, stream_url: str) -> None:
        """Start the FFmpeg process for the specified stream URL."""
        if self.process:
            self.stop_stream()  # Ensure any existing process is stopped

        logger.info(f"Starting FFmpeg process for stream: {stream_url}")
        try:
            self.process = (
                ffmpeg
                .input(stream_url)
                .filter('volume', 0.2)
                .output(
                    'pipe:1',
                    format='s16le',
                    acodec='pcm_s16le',
                    ar=SAMPLERATE,
                    ac=CHANNELCOUNT
                )
                .run_async(pipe_stdout=True, pipe_stderr=True)
            )
            logger.info("Clearing stop event")
            self.stop_event.clear()

        except ffmpeg.Error as e:
            logger.error(f"Error starting FFmpeg process: {e}")

    def stream_audio(self) -> None:
        """Read audio data from FFmpeg and put it into the audio queue."""
        logger.info("Streaming audio to queue")
        try:
            while not self.stop_event.is_set():
                if self.audio_queue.qsize() >= self.buffer_size:
                    time.sleep(0.01)
                    continue

                audio_data = self.process.stdout.read(self.chunk_size)
                if not audio_data:
                    logger.info("FFmpeg process finished streaming audio, starting default song")
                    self.stop_stream()
                    self.song_queue.put(self.dtmf_maps[self.cur_theme.value]['default'])
                    break

                self.audio_queue.put(audio_data)
                time.sleep(0.01)
                logger.debug(f"Buffered audio chunk. Queue size: {self.audio_queue.qsize()}")

        except Exception as e:
            logger.error(f"Error in streaming audio: {e}")

    def stop_stream(self) -> None:
        """Stop the current FFmpeg process."""
        if self.process:
            logger.info("Stopping FFmpeg process.")
            self.stop_event.set()
            self.process.kill()
            self.process.wait(timeout=1)
            self.process = None
            self.clear_queue()

    def clear_queue(self) -> None:
        """Clear the audio queue."""
        logger.info("Clearing audio queue")
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break
        logger.info(f"Audio queue cleared, buffer size {self.audio_queue.qsize()}")

    def run(self) -> None:
        """Main thread loop for handling the audio stream."""
        try:
            while not self.end_event.is_set():
                if self.process:
                    self.stream_audio()
                    time.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("Process interrupted by user.")
        finally:
            self.stop_stream()
            logger.info(f"Cleaned up class: {self.__class__.__name__}")


class FFmpegStreamManager(threading.Thread):
    def __init__(
        self,
        cur_theme: str,
        song_queue: queue.Queue,
        end_event: threading.Event,
        streamer: FFmpegStreamer
    ) -> None:
        super().__init__()
        logger.info(f"Initializing class: {self.__class__.__name__}")
        self.cur_theme = cur_theme
        self.song_queue = song_queue
        self.end_event = end_event
        self.streamer = streamer

    def run(self) -> None:
        """Main loop to handle dynamic stream switching based on the song queue."""
        try:
            while not self.end_event.is_set():
                try:
                    song: str = self.song_queue.get(timeout=0.1)

                    if '://' in song and not song.startswith('file://'):
                        stream_url = song
                    else:
                        stream_url = f'{SOUND_DIR}/{self.cur_theme.value}/{song}'
                    logger.info(f"Preparing to stream: {stream_url}")

                    self.streamer.start_stream(stream_url)
                except queue.Empty:
                    continue

        except KeyboardInterrupt:
            logger.info("Process interrupted by user.")
        finally:
            self.streamer.stop_stream()
            logger.info(f"Cleaned up class: {self.__class__.__name__}")
