import re
from urllib.parse import urlsplit
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkin_time: str = "21:00_23:30"
    log: Literal["info", "error", "warning", "debug"] = "info"
    bark_url: str = Field(default="", max_length=2048)

    @field_validator("bark_url")
    @classmethod
    def notification_url(cls, value):
        value = value.strip()
        if value:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or any(c.isspace() or ord(c) < 32 for c in value)
            ):
                raise ValueError(
                    "Use an absolute HTTP(S) destination URL without credentials"
                )
        return value

    @field_validator("checkin_time")
    @classmethod
    def valid_window(cls, value):
        if not re.fullmatch(
            r"(?:[01]\d|2[0-3]):[0-5]\d_(?:[01]\d|2[0-3]):[0-5]\d", value
        ):
            raise ValueError("Use HH:mm_HH:mm")
        start, end = value.split("_")
        if start >= end:
            raise ValueError("Start must precede end on the same Shanghai calendar day")
        return value


class AccountAlias(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alias: str | None = Field(default=None, min_length=1, max_length=80)
    checkin_time: str | None = None

    @field_validator("checkin_time")
    @classmethod
    def valid_window(cls, value):
        return Config.valid_window(value) if value is not None else None

    @field_validator("alias")
    @classmethod
    def nonblank(cls, value):
        if value is None:
            raise ValueError("Alias cannot be null")
        if not value.strip():
            raise ValueError("Alias cannot be blank")
        return value.strip()


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alias: str = Field(default="", max_length=80)
    username: str = Field(min_length=1, max_length=100, pattern=r"^\S+$")
    password: SecretStr | None = Field(default=None, min_length=1, max_length=512)
    save_password: bool = False
    new_browser_fingerprint: bool = False
    login_target: Literal["both", "school", "wechat"] = "both"


class LocationChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str | None = Field(default=None, max_length=200)


class SMSCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: SecretStr = Field(min_length=4, max_length=10)

    @field_validator("code")
    @classmethod
    def digits_only(cls, value):
        if not re.fullmatch(r"[0-9]{4,10}", value.get_secret_value()):
            raise ValueError("Enter the numeric SMS code")
        return value


class CaptchaPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    t: int = Field(ge=0, le=15000, strict=True)


class CaptchaGesture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: str = Field(min_length=1, max_length=100)
    points: list[CaptchaPoint] = Field(min_length=2, max_length=300)

    @field_validator("points")
    @classmethod
    def chronological(cls, points):
        if (
            points[0].t != 0
            or points[-1].t < 50
            or any(b.t < a.t for a, b in zip(points, points[1:]))
        ):
            raise ValueError("Invalid drag timing; drag the slider again")
        return points
