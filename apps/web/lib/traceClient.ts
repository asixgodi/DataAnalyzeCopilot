import type { TraceDetail } from "@/components/types";


export async function fetchTrace(
  apiBaseUrl: string,
  traceId: string,
): Promise<TraceDetail> {
  const response = await fetch(`${apiBaseUrl}/api/traces/${encodeURIComponent(traceId)}`);
  if (!response.ok) {
    throw new Error(`Trace API returned ${response.status}`);
  }
  return (await response.json()) as TraceDetail;
}
