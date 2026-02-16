import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel

from vars import APP_NAME

DEV_MODE = os.getenv("DEV")
ROOT_DIR = Path(os.path.realpath(__file__)).parent
SOCKET_DIR = (ROOT_DIR / ".sock") if DEV_MODE else Path("/run") / APP_NAME
SOCKET_PATH = str(SOCKET_DIR / "ll-connect-wireless.sock")

# ==============================
# DATA MODELS
# ==============================
class Fan(BaseModel):
    mac: str
    master_mac: str
    channel: int
    rx_type: int
    fan_count: int
    pwm: int
    rpm: List[int]
    target_pwm: int
    is_bound: bool

class SystemStatus(BaseModel):
    timestamp: float
    cpu_temp: Optional[float] = None
    fans: List[Fan]

class VersionStatus(BaseModel):
    latest_ver: str
    checked: bool