import uuid

from entities.device import Device
from utils.id_generator import generate_device_id


class DeviceGenerator:
    def __init__(self, rng, config):
        self.rng = rng
        self.config = config

    def _random_ip(self):
        return ".".join(str(self.rng.randint(1, 254)) for _ in range(4))

    def generate_for_accounts(self, accounts):
        """Most account holders use a single phone; a minority have 2-3
        linked devices (tablet, second phone, etc.)."""
        devices = []
        for account in accounts:
            num_devices = 1 if self.rng.boolean(0.8) else self.rng.randint(2, 3)
            for _ in range(num_devices):
                device_type = self.rng.choice(self.config.DEVICE_TYPES)
                device = Device(
                    device_id=generate_device_id(),
                    device_type=device_type,
                    os_version=f"{device_type} {self.rng.randint(10, 17)}.{self.rng.randint(0, 9)}",
                    app_version=f"{self.rng.randint(3, 9)}.{self.rng.randint(0, 9)}.{self.rng.randint(0, 9)}",
                    ip_address=self._random_ip(),
                    fingerprint=uuid.uuid4().hex,
                    linked_account_id=account.account_id,
                )
                devices.append(device)
        return devices
