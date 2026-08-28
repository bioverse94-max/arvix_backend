"""
graph_builder.py — Graph-Based Detection Module

Two representations are built from the same cleaned transaction stream,
because the two families of graph feature need different things:

1. TemporalTransactionGraph — an event-ordered structure that answers
   "as of this exact moment, what does this account's network position
   look like" — used for real-time features (in/out-degree in the last
   24h, pass-through ratio, time-to-forward, new-counterparty ratio,
   cycle participation). This is what a live streaming system would
   actually query per incoming transaction (Section 3.5, step 2 of the
   full context doc).

2. The aggregated static graph (a networkx.DiGraph collapsing all edges
   between the same pair of accounts into one weighted edge) — used for
   structural properties that a real system would recompute periodically
   rather than per-transaction (clustering coefficient, degree
   centrality, multi-hop downstream funnel concentration). Recomputing
   these globally on every single transaction would be wasteful; real
   fraud-graph systems (Neo4j GDS, as noted in Section 3.8) refresh
   these on a schedule, not inline.
"""

import bisect
from collections import defaultdict

import networkx as nx

from .config import COL_TIMESTAMP


class TemporalTransactionGraph:
    """
    Maintains, per account, a time-ordered list of (timestamp, counterparty,
    direction, amount) events, plus the set of counterparties ever seen.

    All window queries use bisect over the sorted timestamp list, so a
    24h-window lookup is O(log n) instead of a full re-scan.
    """

    def __init__(self):
        # account_id -> list of (timestamp, counterparty_id, amount) for INCOMING edges
        self.incoming = defaultdict(list)
        # account_id -> list of (timestamp, counterparty_id, amount) for OUTGOING edges
        self.outgoing = defaultdict(list)
        # account_id -> sorted list of incoming timestamps (kept parallel to `incoming`)
        self.incoming_ts = defaultdict(list)
        self.outgoing_ts = defaultdict(list)
        # account_id -> set of counterparties ever paid TO this account (history)
        self.known_senders = defaultdict(set)
        # account_id -> set of counterparties this account has ever paid (history)
        self.known_receivers = defaultdict(set)
        # direct edge existence for cycle / reciprocity checks: (a, b) -> True if a paid b at least once
        self.edge_seen = set()

    def add_edge(self, sender, receiver, timestamp, amount):
        self.outgoing[sender].append((timestamp, receiver, amount))
        self.outgoing_ts[sender].append(timestamp)
        self.incoming[receiver].append((timestamp, sender, amount))
        self.incoming_ts[receiver].append(timestamp)
        self.known_senders[receiver].add(sender)
        self.known_receivers[sender].add(receiver)
        self.edge_seen.add((sender, receiver))

    # ---- window helpers (state INCLUDES the current edge, matching
    #      real-time "score as it arrives" semantics) ----

    def _window_slice(self, ts_list, events, end_time, hours):
        start_time = end_time - _hours_delta(hours)
        lo = bisect.bisect_left(ts_list, start_time)
        hi = bisect.bisect_right(ts_list, end_time)
        return events[lo:hi]

    def incoming_in_window(self, account, end_time, hours):
        return self._window_slice(
            self.incoming_ts[account], self.incoming[account], end_time, hours
        )

    def outgoing_in_window(self, account, end_time, hours):
        return self._window_slice(
            self.outgoing_ts[account], self.outgoing[account], end_time, hours
        )

    def has_reverse_edge(self, a, b):
        """Has b ever paid a? (used for reciprocity / round-trip / cycle checks)."""
        return (b, a) in self.edge_seen


def _hours_delta(hours):
    import pandas as pd
    return pd.Timedelta(hours=hours)


def build_temporal_graph(df) -> TemporalTransactionGraph:
    """
    Replays the cleaned, chronologically-sorted transaction frame edge by
    edge to build the temporal graph. This replay order is what makes the
    later window queries valid "as of now" snapshots rather than
    look-ahead (future-leaking) computations.
    """
    tg = TemporalTransactionGraph()
    for row in df.itertuples(index=False):
        sender = getattr(row, "sender_id_resolved")
        receiver = getattr(row, "receiver_id_resolved")
        ts = getattr(row, COL_TIMESTAMP)
        amount = getattr(row, "amount")
        tg.add_edge(sender, receiver, ts, amount)
    return tg


def build_aggregated_graph(df) -> nx.DiGraph:
    """
    Collapse the full transaction history into a directed graph where each
    (sender, receiver) pair is a single weighted edge. This is the graph
    the dashboard's "Graph Explorer" screen (Section 4, Frontend screens)
    would render, and the one structural features are computed on.
    """
    G = nx.DiGraph()
    grouped = df.groupby(["sender_id_resolved", "receiver_id_resolved"]).agg(
        txn_count=("amount", "count"),
        total_amount=("amount", "sum"),
        first_ts=(COL_TIMESTAMP, "min"),
        last_ts=(COL_TIMESTAMP, "max"),
    ).reset_index()

    for row in grouped.itertuples(index=False):
        G.add_edge(
            row.sender_id_resolved,
            row.receiver_id_resolved,
            weight=row.txn_count,
            total_amount=row.total_amount,
            first_ts=row.first_ts,
            last_ts=row.last_ts,
        )
    return G
