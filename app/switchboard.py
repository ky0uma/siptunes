import pjsua2 as pj
import logging
import json
import signal
import sys
import multiprocessing as mp
import os
import functools
import uuid
from dataclasses import dataclass
from typing import Dict

from app.call import MyAccount
from app.const import (
    SAMPLERATE,
    CHANNELCOUNT,
    FRAMETIME,
    SIP_USERNAME,
    SIP_DOMAIN,
    SIP_OUTBOUND,
    SIP_PASSWORD,
    CODEC,
    SOUND_DIR,
    LOGS_DIR,
    themes_list
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

logger.info(f"Using {SAMPLERATE}Hz sample rate, {CHANNELCOUNT}-channel audio, with {FRAMETIME / 1000}ms frame time.")

# Define SipConfig dataclass
@dataclass(frozen=True)
class SipConfig:
    username: str
    domain: str
    outbound: str
    password: str

# Initialize the SIP configuration
sip_config = SipConfig(
    username=SIP_USERNAME,
    domain=SIP_DOMAIN,
    outbound=SIP_OUTBOUND,
    password=SIP_PASSWORD
)

def signal_handler(sig, frame, event_manager: Dict[uuid.UUID, mp.Event], ep: pj.Endpoint):
    logger.info('Shutting down...')
    for id in event_manager:
        logger.info(f"Setting stop event for {id}")
        event_manager[id].set()
    ep.libDestroy()
    sys.exit(0)

def codec_priority(ep: pj.Endpoint):
    codec_info = ep.codecEnum2()
    codec_found = False

    # Look for Opus codec by name and enable it
    for codec in codec_info:
        if CODEC.lower() in codec.codecId.lower():
            ep.codecSetPriority(codec.codecId, 255)
            codec_found = True
            logger.info(f"{CODEC} codec enabled.")
        else:
            ep.codecSetPriority(codec.codecId, 0)

    if not codec_found:
        logger.error(f"{CODEC} codec not found in the codec list!")

    for codec in ep.codecEnum2():
        logger.debug(f"codec: {codec.codecId}, priority: {codec.priority}")

def configure_sip_account():
    acc_cfg = pj.AccountConfig()
    acc_cfg.idUri = f"sip:{sip_config.username}@{sip_config.domain}"
    acc_cfg.regConfig.registrarUri = f"sip:{sip_config.domain}"
    acc_cfg.sipConfig.proxies.append(f"sip:{sip_config.outbound};lr")
    
    # Use the credentials from the SipConfig class
    cred = pj.AuthCredInfo("digest", "*", sip_config.username, 0, sip_config.password)
    acc_cfg.sipConfig.authCreds.append(cred)

    return acc_cfg

def load_dtmf_maps(themes: list, sound_dir: str) -> dict:
    """Load DTMF mappings from JSON files for multiple themes."""
    dtmf_maps = {}
    
    for theme in themes:
        dtmf_map_path = os.path.join(sound_dir, f'dtmf_map_{theme}.json')
        try:
            with open(dtmf_map_path, 'r') as f:
                dtmf_maps[theme] = json.load(f)
            logger.info(f"Loaded DTMF Map for theme '{theme}':")
            logger.info(json.dumps(dtmf_maps[theme], indent=4))
        except FileNotFoundError:
            logger.warning(f"DTMF map file for theme '{theme}' not found at {dtmf_map_path}.")
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON format in DTMF map file for theme '{theme}'.")

    return dtmf_maps


def main():
    # Setup parent stop event
    parent_id = uuid.uuid4()
    stop_event = mp.Event()

    # Create event manager dictionary
    event_manager = {
        parent_id: stop_event
    }

    # Load DTMF mappings from JSON file
    dtmf_maps = load_dtmf_maps(themes_list, SOUND_DIR)
    themes = list(dtmf_maps.keys())

    # Check if themes is empty, exit if so
    if not themes:
        logger.error("No themes found. Exiting...")
        sys.exit(1)  # Exit with a non-zero status code indicating failure

    # Create and initialize the library
    ep_cfg = pj.EpConfig()
    ep = pj.Endpoint()

    # Configure logging to a file
    log_cfg = ep_cfg.logConfig
    log_cfg.level = 5  # Set the desired log level
    log_cfg.consoleLevel = 0  # Disable console logging
    log_cfg.filename = f"{LOGS_DIR}/pjsua.log"  # Log to a file

    ep.libCreate()
    ep.libInit(ep_cfg)

    # Enable Opus (only)
    codec_priority(ep)

    # Create SIP transport
    sip_tp_config = pj.TransportConfig()
    sip_tp_config.port = 5060
    ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, sip_tp_config)

    # Start the library
    ep.libStart()

    # Set null audio device
    ep.audDevManager().setNullDev()

    # Create the SIP account using the strongly-typed config
    acc_cfg = configure_sip_account()

    # Create the account
    acc = MyAccount(dtmf_maps=dtmf_maps, themes=themes, event_manager=event_manager)
    acc.create(acc_cfg)

    handler = functools.partial(signal_handler, event_manager=event_manager, ep=ep)
    signal.signal(signal.SIGINT, handler)

    # Wait for calls indefinitely
    logger.info("Waiting for incoming calls...")

    while not stop_event.is_set():
        ep.libHandleEvents(1000)

if __name__ == "__main__":
    main()
