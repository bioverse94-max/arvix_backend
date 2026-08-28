import random
from datetime import timedelta

import numpy as np


class RandomProvider:
    """Single seeded source of randomness for the whole pipeline, so a run
    is fully reproducible from --seed alone."""

    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)

    def choice(self, seq):
        return self.rng.choice(seq)

    def sample(self, seq, k):
        return self.rng.sample(list(seq), k)

    def shuffle(self, seq):
        self.rng.shuffle(seq)
        return seq

    def weighted_choice(self, options, weights):
        return self.rng.choices(options, weights=weights, k=1)[0]

    def uniform(self, a, b):
        return self.rng.uniform(a, b)

    def randint(self, a, b):
        return self.rng.randint(a, b)

    def boolean(self, p_true=0.5):
        return self.rng.random() < p_true

    def lognormal_amount(self, mean=6.0, sigma=1.0, min_amount=10, max_amount=200000):
        """Transaction amounts in real payment data are heavily right-skewed
        (lots of small payments, occasional large ones) -- lognormal
        approximates that far better than a uniform distribution."""
        val = self.np_rng.lognormal(mean=mean, sigma=sigma)
        return float(min(max(val, min_amount), max_amount))

    def random_datetime(self, start, end):
        delta = end - start
        seconds = self.rng.uniform(0, delta.total_seconds())
        return start + timedelta(seconds=seconds)

    def jitter_datetime(self, ts, max_seconds):
        return ts + timedelta(seconds=self.rng.uniform(0, max_seconds))
