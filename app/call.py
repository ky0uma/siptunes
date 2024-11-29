import pjsua2 as pj
import logging
import multiprocessing as mp
import uuid
from queue import Queue
from multiprocessing import Event
from typing import Dict, List, Any

from app.const import (
    SAMPLERATE,
    CHANNELCOUNT,
    FRAMETIME,
    BITPERSAMPLE,
    CHUNKSIZE,
    BUFFERSIZE,
)
from app.audio import FFmpegStreamer, FFmpegStreamManager

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1
DEFAULT_BIT_DEPTH = 16

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MyAudioMediaPort(pj.AudioMediaPort):
    def __init__(self, audio_queue: Queue, sample_rate: int = DEFAULT_SAMPLE_RATE, channels: int = DEFAULT_CHANNELS, bit_depth: int = DEFAULT_BIT_DEPTH):
        super().__init__()
        self.audio_queue = audio_queue  # Queue for receiving audio data
        self.sample_rate = sample_rate  # Sample rate (e.g., 16000 Hz)
        self.channels = channels        # Number of audio channels (e.g., 1 for mono)
        self.bit_depth = bit_depth      # Bit depth (e.g., 16 bits)
        self.frame_size = (self.sample_rate * self.channels * self.bit_depth) // 8  # Frame size in bytes
    
    def onFrameRequested(self, frame: Any) -> None:
        """Called when a frame is requested by the media transport."""
        frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO
        
        # Check if there is audio data in the queue
        if not self.audio_queue.empty():
            audio_data = self.audio_queue.get()
            frame.buf.resize(len(audio_data))
            frame.buf[:] = audio_data
        else:
            # If no data, provide an empty frame (silent frame)
            frame.buf.resize(self.frame_size)  # Use the calculated frame size
            frame.buf[:] = [0] * self.frame_size  # Silent frame (all zeroes)

    def onFrameReceived(self, frame: Any) -> None:
        pass  # Not used in this implementation

class MyCall(pj.Call):
    def __init__(self, acc: pj.Account, dtmf_maps: Dict[str, str], themes: List[str], event_manager: Dict[uuid.UUID, Event], call_id: int = pj.PJSUA_INVALID_ID):
        super().__init__(acc, call_id)
        self.med_port: MyAudioMediaPort | None = None
        self.aud_med: pj.AudioMedia | None = None
        self.remote_media: pj.AudioMedia | None = None
        self.acc = acc
        self.dtmf_maps = dtmf_maps
        self.themes = themes
        self.event_manager = event_manager      
        self.song_queue: Queue[str] = mp.Queue()
        self.audio_queue: Queue[bytes] = mp.Queue()
        self.end_event: Event = mp.Event()
        self.id = uuid.uuid4()
        event_manager[self.id] = self.end_event

        # Set theme to first in dictionary
        manager = mp.Manager()
        self.cur_theme = manager.Value('s', self.themes[0])

        # Initialize and start the streamer and manager threads
        self.streamer = FFmpegStreamer(audio_queue=self.audio_queue, song_queue=self.song_queue, chunk_size=CHUNKSIZE, buffer_size=BUFFERSIZE, dtmf_maps=self.dtmf_maps, cur_theme=self.cur_theme, end_event=self.end_event)
        self.manager = FFmpegStreamManager(cur_theme=self.cur_theme, song_queue=self.song_queue, end_event=self.end_event, streamer=self.streamer)

        self.streamer.start()
        self.manager.start()

    def _create_media_state(self) -> None:
        """Creates a new media state or clears the existing one before setting up a new one."""
        logger.info("Setting up new media state.")
        self.remote_media = pj.AudioMedia.typecastFromMedia(self.aud_med)

        # Adjust the format to match the higher quality
        fmt = pj.MediaFormatAudio()
        fmt.type = pj.PJMEDIA_TYPE_AUDIO
        fmt.clockRate = SAMPLERATE
        fmt.channelCount = CHANNELCOUNT
        fmt.bitsPerSample = BITPERSAMPLE
        fmt.frameTimeUsec = FRAMETIME

        # Setup media port
        self.med_port = MyAudioMediaPort(
            audio_queue=self.audio_queue, 
            sample_rate=SAMPLERATE, 
            channels=CHANNELCOUNT, 
            bit_depth=BITPERSAMPLE
        )
        self.med_port.createPort("med_port", fmt)

        # Start transmitting media
        self.remote_media.startTransmit(self.med_port)
        self.med_port.startTransmit(self.remote_media)

    def _cleanup_resources(self) -> None:
        logger.info("Cleaning up resources.")
        self.end_event.set()
        del self.event_manager[self.id]
        self.streamer.join()
        self.manager.join()

    def onDtmfDigit(self, prm: pj.OnDtmfDigitParam) -> None:
        digits = prm.digit
        audio_file = None
        logger.info(f"Received DTMF: {digits}")

        if digits == '*':
            # Move to the previous theme in the list
            current_index = self.themes.index(self.cur_theme.value)
            previous_index = (current_index - 1) % len(self.themes)  # Handle wrap-around
            self.cur_theme.value = self.themes[previous_index]
            audio_file = self.dtmf_maps[self.cur_theme.value]['default']
            logger.info(f"Changed to previous theme: {self.cur_theme.value}")

        elif digits == '#':
            # Move to the next theme in the list
            current_index = self.themes.index(self.cur_theme.value)
            next_index = (current_index + 1) % len(self.themes)  # Handle wrap-around
            self.cur_theme.value = self.themes[next_index]
            audio_file = self.dtmf_maps[self.cur_theme.value]['default']
            logger.info(f"Changed to next theme: {self.cur_theme.value}")

        elif digits in self.dtmf_maps[self.cur_theme.value]:
            # Regular case where the DTMF digit maps to an audio file
            audio_file = self.dtmf_maps[self.cur_theme.value].get(digits)
        else:
            logger.warning(f"No mapping found for DTMF: {digits}")
        
        if audio_file:
            logger.info(f"Playing file: {audio_file}")
            self.song_queue.put(audio_file)


    def onCallState(self, prm: pj.OnCallStateParam) -> None:
        ci = self.getInfo()
        logger.info(f"*** onCallMediaState state: id={ci.id}, state={ci.stateText}")

        if ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            logger.info("Setting stop event to tear down FFMPEG threads")
            self._cleanup_resources()
            self.acc.calls.remove(self)  # Remove the call instance

        if ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
            self.song_queue.put(self.dtmf_maps[self.cur_theme.value]['default'])
            for i, media in enumerate(ci.media):
                if media.type == pj.PJMEDIA_TYPE_AUDIO:
                    self.aud_med = self.getAudioMedia(i)
                    break

            if self.aud_med:
                self._create_media_state()

class MyAccount(pj.Account):
    def __init__(self, dtmf_maps: Dict[str, str], themes: List[str], event_manager: Dict[uuid.UUID, Event]):
        super().__init__()
        self.dtmf_maps = dtmf_maps
        self.themes = themes
        self.event_manager = event_manager
        self.calls: list[MyCall] = []

    def onIncomingCall(self, prm: pj.OnIncomingCallParam) -> None:
        logger.info(f"Incoming call from {prm.rdata.info}")
        call = MyCall(self, dtmf_maps=self.dtmf_maps, themes=self.themes, event_manager=self.event_manager, call_id=prm.callId)
        self.calls.append(call)
        call_prm = pj.CallOpParam()
        call_prm.statusCode = pj.PJSIP_SC_OK
        call.answer(call_prm)

    def onRegState(self, prm: pj.OnRegStateParam) -> None:
        if self.getInfo().regIsActive:
            logger.info("Successfully registered with the SIP server.")
        else:
            logger.warning("Not registered with the SIP server.")
