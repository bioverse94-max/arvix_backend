from dataclasses import dataclass, asdict


@dataclass
class Location:
    city: str
    state: str
    pincode: str
    latitude: float
    longitude: float

    def to_dict(self):
        return asdict(self)
