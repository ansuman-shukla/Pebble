"""Typed shapes of JSONB columns that more than one process reads or writes."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_SPEED = 600  # game seconds per real second (×600 = a game day in 2.4 real minutes)


class ClockChange(BaseModel):
    """Payload of a `clock` engine command (also the admin request body)."""

    model_config = ConfigDict(extra="forbid")

    speed: int | None = Field(default=None, ge=1, le=MAX_SPEED)  # game seconds per real second
    paused: bool | None = None

    @model_validator(mode="after")
    def _check_something(self) -> "ClockChange":
        if self.speed is None and self.paused is None:
            raise ValueError("give speed, paused or both")
        return self
