from dataclasses import dataclass, asdict

from entities.location import Location


@dataclass
class Merchant:
    merchant_id: str
    name: str
    mcc: str
    category: str
    vpa: str
    location: Location

    def to_dict(self):
        d = asdict(self)
        return d
