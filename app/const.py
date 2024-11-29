from dotenv import load_dotenv
import os

# Get configration from .env
load_dotenv('.env')
SIP_DOMAIN   = os.getenv('SIP_DOMAIN')
SIP_USERNAME = os.getenv('SIP_USERNAME')
SIP_PASSWORD = os.getenv('SIP_PASSWORD')
SIP_OUTBOUND = os.getenv('SIP_OUTBOUND')
THEMES        = os.getenv('THEMES')
CODEC        = os.getenv('CODEC')
SAMPLERATE   = int(os.getenv('SAMPLERATE'))

themes_list = THEMES.split(",") if THEMES else []

# Define codec specs
CHANNELCOUNT = 1  # Mono channel
BITPERSAMPLE = 16 #16  # Set bit depth to 32
FRAMETIME = 20000  # Frametime usec
FRMAEDURATION = FRAMETIME / 1_000_000  # Convert FRAMETIME from microseconds to seconds - 20,000 microseconds = 0.02 seconds
CHUNKSIZE = int(SAMPLERATE * FRMAEDURATION * CHANNELCOUNT * (BITPERSAMPLE / 8)) # Calculate the frame size (chunk size)
BUFFERSIZE=50 # Used to maintain a buffer of frames for smoother playback

SOUND_DIR = f'./sound'
LOGS_DIR = f'./logs'



