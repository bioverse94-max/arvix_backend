from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class Account:
    account_id: str
    holder_name: str
    vpa: str
    bank_name: str
    ifsc: str
    account_type: str
    balance: float
    created_at: datetime
    risk_score: float = 0.0
    status: str = "ACTIVE"

    def to_dict(self):
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d
