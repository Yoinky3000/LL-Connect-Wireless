import re
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    gpu_temp: Optional[float] = None
    fans: List[Fan]


class VersionInfo(BaseModel):
    semver: str
    rc: int
    release: int
    compile_ver: str
    raw_tag: str
    release_note: Optional[str]
    installer_url: Optional[str]
    last_notified: Optional[float]


class VersionStatus(BaseModel):
    data: VersionInfo
    notified: bool
    outdated: bool


class LinearMode(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    min_temp: int = Field(default=35, ge=20, le=100)
    max_temp: int = Field(default=80, ge=20, le=100)

    min_pwm: int = Field(default=10, ge=0, le=100)
    max_pwm: int = Field(default=70, ge=0, le=100)

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.min_temp >= self.max_temp:
            raise ValueError("min_temp must be less than max_temp")
        if self.min_pwm > self.max_pwm:
            raise ValueError("min_pwm must be less than or equal to max_pwm")
        return self


def default_gpu_linear() -> "LinearMode":
    return LinearMode(min_temp=35, max_temp=75, min_pwm=25, max_pwm=90)


class CurvePoint(BaseModel):
    temp_c: int = Field(ge=20, le=120)
    percent: int = Field(ge=0, le=100)


class CurveMode(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    points: List[CurvePoint]

    @model_validator(mode="after")
    def validate_points(self):
        if len(self.points) != 4:
            raise ValueError("curve mode requires exactly 4 mappings")

        for i in range(1, len(self.points)):
            prev = self.points[i - 1]
            cur = self.points[i]
            if cur.temp_c <= prev.temp_c:
                raise ValueError("curve temperatures must be strictly increasing")
            if cur.percent < prev.percent:
                raise ValueError("curve pwm percentages must be non-decreasing")
        return self


def default_cpu_curve() -> CurveMode:
    return CurveMode(
        points=[
            CurvePoint(temp_c=50, percent=27),
            CurvePoint(temp_c=60, percent=37),
            CurvePoint(temp_c=90, percent=70),
            CurvePoint(temp_c=95, percent=100),
        ]
    )


def default_gpu_curve() -> CurveMode:
    return CurveMode(
        points=[
            CurvePoint(temp_c=35, percent=30),
            CurvePoint(temp_c=60, percent=40),
            CurvePoint(temp_c=70, percent=60),
            CurvePoint(temp_c=75, percent=90),
        ]
    )


class FanMode(str, Enum):
    linear = "linear"
    curve = "curve"


MAC_RE = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")


def _normalize_mac_list(values: List[str]) -> List[str]:
    normalized: List[str] = []
    for raw in values:
        mac = raw.strip().lower()
        if not MAC_RE.fullmatch(mac):
            raise ValueError(f"invalid MAC address: {raw}")
        if mac not in normalized:
            normalized.append(mac)
    return normalized


class Settings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    mode: FanMode = FanMode.curve
    linear: LinearMode = LinearMode()
    gpu_linear: LinearMode = Field(default_factory=default_gpu_linear)
    cpu_curve: CurveMode = Field(default_factory=default_cpu_curve)
    gpu_curve: CurveMode = Field(default_factory=default_gpu_curve)
    gpu_macs: List[str] = Field(default_factory=list)
    mix_macs: List[str] = Field(default_factory=list)

    @field_validator("gpu_macs", "mix_macs")
    @classmethod
    def validate_mac_lists(cls, values: List[str]):
        return _normalize_mac_list(values)

    @model_validator(mode="after")
    def validate_no_mac_overlap(self):
        overlap = set(self.gpu_macs) & set(self.mix_macs)
        if overlap:
            raise ValueError(
                f"MAC(s) cannot be in both gpu and mix groups: {', '.join(sorted(overlap))}"
            )
        return self
