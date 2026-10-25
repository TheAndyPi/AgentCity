import { ApiError, LiveTransport, type Transport } from "../api/client";
import { failure } from "../api/schemas";
import {
  comparisonRequest,
  comparisonResponse,
  type ComparisonRequest,
} from "./schema";

export class SnowflakeClient {
  constructor(private transport: Transport = new LiveTransport()) {}
  async compare(body: ComparisonRequest, key: string) {
    comparisonRequest.parse(body);
    const raw = await this.transport.request(
      "POST",
      "/integrations/snowflake/comparisons",
      body,
      key,
    );
    const failed = failure.safeParse(raw);
    if (failed.success) {
      if (
        failed.data.error.code === "UNAUTHENTICATED" &&
        typeof window !== "undefined"
      )
        window.dispatchEvent(new Event("agentcity:session-expired"));
      throw new ApiError(
        failed.data.error.code,
        failed.data.error.message,
        failed.data.error.retryable,
      );
    }
    const result = comparisonResponse.parse(raw);
    if (
      result.request_id !== key ||
      ["a", "b"].some((side) => {
        const s = side as "a" | "b";
        return (
          result.data[s].simulation_id !== body[s].simulation_id ||
          result.data[s].revision !== body[s].revision
        );
      })
    )
      throw new ApiError(
        "INVALID_RESPONSE",
        "Comparison provenance does not match the pinned request",
        true,
      );
    return result.data;
  }
}
