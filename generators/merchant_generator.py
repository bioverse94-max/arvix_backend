from faker import Faker

from entities.location import Location
from entities.merchant import Merchant
from utils.id_generator import generate_merchant_id, generate_vpa


class MerchantGenerator:
    def __init__(self, rng, config):
        self.rng = rng
        self.config = config
        self.faker = Faker("en_IN")

    def generate(self, n: int):
        merchants = []
        for _ in range(n):
            mcc, category = self.rng.choice(self.config.MCC_CATEGORIES)
            name = f"{self.faker.company()} {category.split()[0]}"
            city, state = self.rng.choice(self.config.CITIES)

            location = Location(
                city=city,
                state=state,
                pincode=str(self.rng.randint(100000, 699999)),
                latitude=round(self.rng.uniform(8.0, 34.0), 6),
                longitude=round(self.rng.uniform(68.0, 97.0), 6),
            )
            _, handle = self.rng.choice(self.config.BANK_HANDLES)

            merchant = Merchant(
                merchant_id=generate_merchant_id(),
                name=name,
                mcc=mcc,
                category=category,
                vpa=generate_vpa(name.split()[0], handle),
                location=location,
            )
            merchants.append(merchant)
        return merchants
