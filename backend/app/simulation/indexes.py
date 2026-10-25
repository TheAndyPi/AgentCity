"""Transient indexes with immutable snapshot views over append-only records."""

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Mapping, Sequence

from app.simulation.navigation import SpatialIndex


class IndexedLines(Sequence):
    """A prefix view: old heads cannot observe later dialogue appended by a runner."""

    def __init__(self, storage, positions, count):
        self.storage = storage
        self.positions = positions
        self.length = bisect_left(positions, count)

    def __len__(self):
        return self.length

    def __getitem__(self, key):
        if isinstance(key, slice):
            return [self.storage.lines[self.positions[i]] for i in range(*key.indices(self.length))]
        if key < 0:
            key += self.length
        if not 0 <= key < self.length:
            raise IndexError(key)
        return self.storage.lines[self.positions[key]]


class IndexMapping(Mapping):
    def __init__(self, storage, buckets, count):
        self.storage, self.buckets, self.count = storage, buckets, count

    def __getitem__(self, key):
        positions = self.buckets[key]
        if not positions or positions[0] >= self.count:
            raise KeyError(key)
        return IndexedLines(self.storage, positions, self.count)

    def __iter__(self):
        return (key for key, positions in self.buckets.items() if positions and positions[0] < self.count)

    def __len__(self):
        return sum(1 for _ in self)


class IdMapping(Mapping):
    def __init__(self, storage, count, positions=False):
        self.storage, self.count, self.positions_only = storage, count, positions

    def __getitem__(self, key):
        position = self.storage.positions[key]
        if position >= self.count:
            raise KeyError(key)
        return position if self.positions_only else self.storage.lines[position]

    def __iter__(self):
        return (line.id for line in self.storage.lines[: self.count])

    def __len__(self):
        return self.count


class DialogueStorage:
    def __init__(self):
        self.lines = []
        self.positions = {}
        self.by_participant = defaultdict(list)
        self.by_audible = defaultdict(list)
        self.by_interaction = defaultdict(list)
        self.by_speaker = defaultdict(list)
        self.by_pair = defaultdict(list)
        self.pair_meetings = defaultdict(list)
        self.seen_meetings = set()
        self.said = {}

    def append(self, line):
        position = len(self.lines)
        self.lines.append(line)
        self.positions[line.id] = position
        self.by_interaction[line.interaction_id].append(position)
        self.by_speaker[line.speaker_id].append(position)
        for recipient in set(line.recipient_ids):
            pair = (line.speaker_id, recipient)
            self.by_pair[pair].append(position)
            self.said.setdefault((*pair, line.text), position)
            meeting = (*pair, line.interaction_id)
            if meeting not in self.seen_meetings:
                self.seen_meetings.add(meeting)
                self.pair_meetings[pair].append(position)
        participants = {line.speaker_id, *line.recipient_ids}
        for aid in participants:
            self.by_participant[aid].append(position)
        for aid in participants | set(line.audible_to_ids):
            self.by_audible[aid].append(position)


class DialogueIndex:
    def __init__(self):
        self.storage = DialogueStorage()
        self.count = 0

    def __deepcopy__(self, memo):
        # Share append-only storage, but retain this snapshot's visible boundary.
        other = type(self)()
        other.storage, other.count = self.storage, self.count
        return other

    def update(self, lines):
        if self.count > len(lines) or (
            self.count and self.storage.lines[self.count - 1].id != lines[self.count - 1].id
        ):
            self.__init__()
        for position in range(self.count, len(lines)):
            line = lines[position]
            if position < len(self.storage.lines):
                if self.storage.lines[position].id != line.id or self.storage.lines[position] != line:
                    # A command/fork diverged from the runner's append-only lineage.
                    self.__init__()
                    for existing in lines[:position]:
                        self.storage.append(existing)
            if position == len(self.storage.lines):
                self.storage.append(line)
        self.count = len(lines)
        return self

    @property
    def by_id(self):
        return IdMapping(self.storage, self.count)

    @property
    def positions(self):
        return IdMapping(self.storage, self.count, positions=True)

    def _mapping(self, name):
        return IndexMapping(self.storage, getattr(self.storage, name), self.count)

    @property
    def by_participant(self):
        return self._mapping("by_participant")

    @property
    def by_audible(self):
        return self._mapping("by_audible")

    @property
    def by_interaction(self):
        return self._mapping("by_interaction")

    @property
    def by_speaker(self):
        return self._mapping("by_speaker")

    def pair_lines(self, speaker, recipient):
        return IndexedLines(self.storage, self.storage.by_pair.get((speaker, recipient), []), self.count)

    def meeting_count(self, speaker, recipient):
        return bisect_left(self.storage.pair_meetings.get((speaker, recipient), []), self.count)

    def has_said(self, speaker, recipient, text):
        return self.storage.said.get((speaker, recipient, text), self.count) < self.count


class EvidenceIndex:
    """Constant-time duplicate checks with snapshot-safe append boundaries."""

    def __init__(self):
        self.keys = []
        self.positions = {}
        self.count = 0

    def __deepcopy__(self, memo):
        other = type(self)()
        other.keys, other.positions, other.count = self.keys, self.positions, self.count
        return other

    def update(self, keys):
        if self.count > len(keys) or (self.count and self.keys[self.count - 1] != keys[self.count - 1]):
            self.__init__()
        for position in range(self.count, len(keys)):
            key = keys[position]
            if position < len(self.keys) and self.keys[position] != key:
                self.__init__()
                for earlier in keys[:position]:
                    self.positions[earlier] = len(self.keys)
                    self.keys.append(earlier)
            if position == len(self.keys):
                self.positions.setdefault(key, position)
                self.keys.append(key)
        self.count = len(keys)
        return self

    def __contains__(self, key):
        return self.positions.get(key, self.count) < self.count


class TickContext:
    def __init__(self, state=None):
        self.spatial = SpatialIndex(state.citizens) if state is not None else None
        self.hazards = {}
        self.blocked = None
        self.buildings = {b.id: b for b in state.map.buildings} if state is not None and state.map else {}

    def __deepcopy__(self, memo):
        return type(self)()


def spatial_index(state):
    context = state._tick_context
    if context is None:
        return SpatialIndex(state.citizens)
    if context.spatial is None:
        context.spatial = SpatialIndex(state.citizens)
    return context.spatial


def buildings_by_id(state):
    context = state._tick_context
    if context is not None:
        return context.buildings
    return {building.id: building for building in state.map.buildings}
