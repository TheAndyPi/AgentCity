"""Explicit paid opt-in. Uses a unique schema or --existing-schema; retains records.

From backend: .venv/bin/python -m scripts.snowflake_smoke --live
Load backend/.env into the environment first (secrets are never printed).
"""

import argparse
import asyncio
import json
from dataclasses import replace
from uuid import uuid4

from app.snowflake.comparison import canonical, digest
from app.snowflake.config import SnowflakeConfig
from app.snowflake.transport import SnowflakeTransport, VendorUnavailable


async def smoke(existing_schema=False):
    config = replace(SnowflakeConfig.from_env(), enabled=True)
    config.validate()
    # Default mode creates a unique schema. Existing-schema mode uses the
    # configured namespace and leaves smoke records for inspection.
    schema = "AGENTCITY_SMOKE_" + uuid4().hex.upper()
    transport = SnowflakeTransport(config)
    payload = dict(
        simulation_id="smoke",
        revision=3,
        endpoint_tick=2,
        metrics=dict(happiness=61.25, cooperation_count=4),
        evidence=["decision_smoke"],
    )
    try:
        # Identifier is bound; only this explicitly invoked operator script calls DDL.
        if not existing_schema:
            await transport.execute("smoke_schema", (config.database + "." + schema,))
        transport.config = replace(config, schema=config.schema if existing_schema else schema, deadline=30)
        await transport.execute("001_setup")
        values = ("smoke_owner", "smoke", 3, digest(payload), canonical(payload))
        await transport.execute("ingest", values)
        await transport.execute("ingest", values)
        rows = await transport.execute("query", values[:3])
        assert len(rows) == 1 and json.loads(rows[0][0]) == payload and rows[0][1] == digest(payload)
        print("SQL setup, repeated MERGE, exact read-back: passed (smoke records retained)")
        rows = await transport.execute(
            "explain",
            (
                config.model,
                'Return {"fact_ids":["cooperation_count","B:decision:decision_smoke"]}. '
                "These are approved recorded fact IDs. Do not add any fields.",
            ),
        )
        selected = json.loads(rows[0][0])
        assert set(selected) == {"fact_ids"}
        assert set(selected["fact_ids"]) == {"cooperation_count", "B:decision:decision_smoke"}
        print("Snowflake AI_COMPLETE structured selection: passed")
        return True
    except Exception as error:
        print(
            "Live smoke unverified/failed:",
            type(error).__name__,
            error.reason if isinstance(error, VendorUnavailable) else "local_validation",
        )
        return False
    finally:
        await transport.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument(
        "--existing-schema",
        action="store_true",
        help="Use the configured schema without requiring CREATE SCHEMA",
    )
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(smoke(args.existing_schema)) else 1)


if __name__ == "__main__":
    main()
