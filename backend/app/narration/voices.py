"""Stable, collision-free citizen voices; no cloning or synthesized voice identities."""

from app.infrastructure.errors import require


class VoiceAssignments:
    def __init__(self, store):
        self.store = store
        with store.lock:
            store.db.execute("""
                CREATE TABLE IF NOT EXISTS character_voices (
                  owner TEXT NOT NULL, simulation_id TEXT NOT NULL,
                  agent_id TEXT NOT NULL, voice_id TEXT NOT NULL,
                  PRIMARY KEY(owner, simulation_id, agent_id),
                  UNIQUE(owner, simulation_id, voice_id))
            """)
            store.db.commit()

    def resolve(self, state, source_type, source_id, config):
        if source_type == "event":
            return config.voice_id
        if source_type == "decision":
            record = next((d for d in state.decisions if d.id == source_id), None)
            agent_id = record.agent_id if record else None
        else:
            record = next((d for d in state.dialogue if d.id == source_id), None)
            agent_id = record.speaker_id if record else None
        require(agent_id in state.citizens, "NOT_FOUND", "Recorded speaker not found in this simulation", 404)
        pool = config.character_voice_ids
        owner, sid = state.owner_id, state.simulation.id
        agents = sorted(state.citizens)
        with self.store.lock:
            db = self.store.db
            assigned = dict(
                db.execute(
                    "SELECT agent_id,voice_id FROM character_voices WHERE owner=? AND simulation_id=?",
                    (owner, sid),
                )
            )
            # A changed pool must not silently change already-established identities.
            require(
                all(v in pool for v in assigned.values()),
                "SERVICE_UNAVAILABLE",
                "An assigned citizen voice is missing from ELEVENLABS_CHARACTER_VOICE_IDS",
                503,
            )
            missing = [aid for aid in agents if aid not in assigned]
            available = [voice for voice in pool if voice not in assigned.values()]
            require(
                len(available) >= len(missing),
                "SERVICE_UNAVAILABLE",
                "Not enough distinct ElevenLabs voices for every citizen; configure more "
                "ELEVENLABS_CHARACTER_VOICE_IDS or use a smaller city",
                503,
            )
            parent = state.simulation.parent_simulation_id
            inherited = (
                dict(
                    db.execute(
                        "SELECT agent_id,voice_id FROM character_voices WHERE owner=? AND simulation_id=?",
                        (owner, parent),
                    )
                )
                if parent
                else {}
            )
            # Copy all inherited assignments first so new citizens cannot take them.
            for aid in missing:
                voice = inherited.get(aid)
                if voice in available:
                    assigned[aid] = voice
                    available.remove(voice)
            for aid in missing:
                if aid not in assigned:
                    assigned[aid] = available.pop(0)
            try:
                db.executemany(
                    "INSERT INTO character_voices VALUES (?,?,?,?)",
                    [(owner, sid, aid, assigned[aid]) for aid in missing],
                )
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return assigned[agent_id]
