export type Value =
  string | number | boolean | null | Value[] | { [key: string]: Value };
export type Configuration = Record<string, Record<string, Value>>;
export type ConfigEnvelope = { data: Configuration; version: string };
export type Step = {
  id: string;
  description: string;
  status: string;
  progress: number;
  elapsed: number;
  error_message: string | null;
};
export type LiveState = {
  running: boolean;
  current_step: string | null;
  steps: Step[];
  logs: string[];
  catalog_revision: number;
  config_version: string;
};
export type Earthquake = {
  id: string | number;
  latitude: number;
  longitude: number;
  depth_km: number | null;
  magnitude: number | null;
  time_str: string | null;
  source: string;
};
export type Station = {
  network: string;
  station: string;
  latitude: number;
  longitude: number;
  elevation: number | null;
};
export type Catalog = { events: Earthquake[]; stations: Station[] };
export type Case = {
  name: string;
  path: string;
  active: boolean;
  exists: boolean;
};

export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const result = await response.json().catch(() => null);
    throw new Error(
      typeof result?.detail === "string"
        ? result.detail
        : `Request failed (${response.status}).`,
    );
  }
  return response.json();
}
