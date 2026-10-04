"use client";

import { accountability } from "./client";
import { urlBase64ToUint8Array } from "./helpers";

export type PushSupport = "unsupported" | "denied" | "default" | "granted";

export function pushSupport(): PushSupport {
  if (
    typeof window === "undefined" ||
    !("serviceWorker" in navigator) ||
    !("PushManager" in window) ||
    !("Notification" in window)
  ) {
    return "unsupported";
  }
  return Notification.permission;
}

export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator)) return null;
  try {
    return await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  } catch {
    return null;
  }
}

/** The subscription this browser already holds, if any. */
export async function currentSubscription(): Promise<PushSubscription | null> {
  if (pushSupport() === "unsupported") return null;
  const registration = await registerServiceWorker();
  if (!registration) return null;
  await navigator.serviceWorker.ready;
  return registration.pushManager.getSubscription();
}

/**
 * Ask permission (must be called from a user gesture), subscribe with the server's VAPID public
 * key and register the subscription with the API. Throws a readable message on failure.
 */
export async function enablePush(vapidPublicKey: string | null): Promise<PushSubscription> {
  if (pushSupport() === "unsupported") throw new Error("This browser does not support push.");
  if (!vapidPublicKey) throw new Error("Push is not configured on the server yet.");
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Notifications are blocked for this site.");
  const registration = await registerServiceWorker();
  if (!registration) throw new Error("Could not start the background service.");
  await navigator.serviceWorker.ready;
  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
    }));
  await accountability.subscribePush(subscription.toJSON());
  return subscription;
}

export async function disablePush(): Promise<void> {
  const subscription = await currentSubscription();
  if (!subscription) return;
  await accountability.revokePush(subscription.endpoint).catch(() => undefined);
  await subscription.unsubscribe().catch(() => undefined);
}
