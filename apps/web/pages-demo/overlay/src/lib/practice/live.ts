import type { LiveGrowthEvent } from "@sg/contracts";

/**
 * Live growth between tabs of this browser. A practice session posts each provisional and
 * confirmed growth event here, and every open garden (this tab or another) glows, the same way
 * the full app's growth stream reaches every tab of a learner.
 */
const CHANNEL = "sg-live-growth";

export const liveGrowthSupported = () => typeof BroadcastChannel !== "undefined";

export function broadcastGrowth(event: LiveGrowthEvent) {
  if (!liveGrowthSupported()) return;
  const channel = new BroadcastChannel(CHANNEL);
  channel.postMessage(JSON.stringify(event));
  channel.close();
}

/** Calls `onData` with each event's JSON text, the shape the SSE stream delivers. */
export function listenGrowth(onData: (data: string) => void): () => void {
  if (!liveGrowthSupported()) return () => {};
  const channel = new BroadcastChannel(CHANNEL);
  channel.onmessage = (message: MessageEvent<unknown>) => {
    if (typeof message.data === "string") onData(message.data);
  };
  return () => channel.close();
}
