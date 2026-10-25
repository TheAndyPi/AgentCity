import type { Transport } from "../api/client";
import { ApiError } from "../api/client";
import { failure } from "../api/schemas";
import { behaviorResponse } from "./schema";

export async function readBehavior(
  transport: Transport,
  sid: string,
  revision: number,
) {
  if (transport.mode === "mock") return null;
  const raw = await transport.request(
    "GET",
    `/integrations/behavior/v2/simulations/${encodeURIComponent(sid)}?revision=${revision}`,
  );
  const failed = failure.safeParse(raw);
  if (failed.success)
    throw new ApiError(failed.data.error.code, failed.data.error.message);
  const result = behaviorResponse.parse(raw).data;
  if (result.simulation_id !== sid || result.ref.revision !== revision)
    throw new Error("Behavior revision does not match the displayed world");
  return result;
}
