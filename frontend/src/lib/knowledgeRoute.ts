import type { RouteTrace } from '../types/api';

export type { RouteTrace };

export function buildRouteTraceLookup(records: RouteTrace[]): Record<string, RouteTrace> {
  const lookup: Record<string, RouteTrace> = {};
  for (const record of records) {
    if (record && record.exchangeId) {
      lookup[String(record.exchangeId)] = record;
    }
  }
  return lookup;
}

export function buildChatRouteExplain(traceRecord?: RouteTrace): {
  topDocument: unknown;
  routeReason: string;
  routeType: string;
} | null {
  if (!traceRecord) {
    return null;
  }
  
  // This extracts the routing logic explaination from the trace
  // We can expand this with explicit interfaces if needed based on the backend
  return {
    topDocument: traceRecord.topDocument || null,
    routeReason: String(traceRecord.routeReason || ''),
    routeType: String(traceRecord.routeType || 'UNKNOWN')
  };
}
