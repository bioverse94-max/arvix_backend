from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Device:
    device_id: str
    device_type: str
    os_version: str
    app_version: str
    ip_address: str
    fingerprint: str
    linked_account_id: Optional[str] = None

    def to_dict(self):
        return asdict(self)
