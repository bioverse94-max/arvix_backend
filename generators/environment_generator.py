from dataclasses import dataclass, field
from typing import Dict, List

from entities.account import Account
from entities.device import Device
from entities.merchant import Merchant
from generators.account_generator import AccountGenerator
from generators.device_generator import DeviceGenerator
from generators.merchant_generator import MerchantGenerator


@dataclass
class Environment:
    """The synthetic 'world' -- the population of accounts, devices, and
    merchants that both normal-transaction generation and every fraud
    scenario draw from."""

    accounts: List[Account]
    devices: List[Device]
    merchants: List[Merchant]
    account_devices: Dict[str, List[Device]] = field(default_factory=dict)

    def devices_for(self, account_id: str) -> List[Device]:
        return self.account_devices.get(account_id, [])


class EnvironmentGenerator:
    def __init__(self, rng, config):
        self.rng = rng
        self.config = config

    def build(self) -> Environment:
        accounts = AccountGenerator(self.rng, self.config).generate(self.config.NUM_ACCOUNTS)
        devices = DeviceGenerator(self.rng, self.config).generate_for_accounts(accounts)
        merchants = MerchantGenerator(self.rng, self.config).generate(self.config.NUM_MERCHANTS)

        account_devices: Dict[str, List[Device]] = {}
        for d in devices:
            account_devices.setdefault(d.linked_account_id, []).append(d)

        return Environment(accounts=accounts, devices=devices, merchants=merchants, account_devices=account_devices)
