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
        elif source_type == "reaction":
            record = next((r for r in state.reactions if r.id == source_id), None)
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
            # Reserve even absent/deceased and removed-pool identities. A child must
            # never give a historical speaker's voice to a newly added citizen.
            additions = {aid: voice for aid, voice in inherited.items() if aid not in assigned}
            assigned.update(additions)
            available = [voice for voice in pool if voice not in assigned.values()]
            for aid in agents:
                if aid not in assigned and available:
                    additions[aid] = assigned[aid] = available.pop(0)
            try:
                db.executemany(
                    "INSERT INTO character_voices VALUES (?,?,?,?)",
                    [(owner, sid, aid, voice) for aid, voice in additions.items()],
                )
                db.commit()
            except BaseException:
                db.rollback()
                raise
        require(
            agent_id in assigned,
            "SERVICE_UNAVAILABLE",
            "Not enough distinct ElevenLabs voices; this citizen's voice is unavailable. "
            "Configure more ELEVENLABS_CHARACTER_VOICE_IDS; existing voices remain usable",
            503,
        )
        require(
            assigned[agent_id] in pool,
            "SERVICE_UNAVAILABLE",
            "This assigned citizen voice is missing from ELEVENLABS_CHARACTER_VOICE_IDS; "
            "restore authorized access without remapping the citizen",
            503,
        )
        return assigned[agent_id]
