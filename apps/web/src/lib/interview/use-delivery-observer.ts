"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { DeliveryAccumulator, sampleFromLandmarks, type DeliverySummary } from "./delivery";

/** MediaPipe's assets are fetched on opt-in only. Override to self-host. */
const WASM_URL =
  process.env.NEXT_PUBLIC_MEDIAPIPE_WASM_URL ??
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.0.1/wasm";
const MODEL_URL =
  process.env.NEXT_PUBLIC_MEDIAPIPE_FACE_MODEL_URL ??
  "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";

/** Frames are sampled twice a second, analysed in memory and dropped. */
export const SAMPLE_EVERY_MS = 500;

export type ObserverStatus = "off" | "starting" | "on" | "denied" | "unavailable";

interface Landmarker {
  detectForVideo(
    video: HTMLVideoElement,
    ts: number,
  ): { faceLandmarks: { x: number; y: number }[][] };
  close(): void;
}

/**
 * Opt-in camera delivery observer. `start()` asks for the camera (only after the learner ticks
 * the consent box), runs MediaPipe Face Landmarker locally and accumulates three ratios.
 * Nothing is recorded or uploaded here; `summary()` returns the aggregates the caller may send.
 */
export function useDeliveryObserver() {
  const [status, setStatus] = useState<ObserverStatus>("off");
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const landmarkerRef = useRef<Landmarker | null>(null);
  const timerRef = useRef<number | null>(null);
  const accRef = useRef(new DeliveryAccumulator());
  const startedAt = useRef(0);

  const stop = useCallback(() => {
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
    timerRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    landmarkerRef.current?.close();
    landmarkerRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setStatus((s) => (s === "on" || s === "starting" ? "off" : s));
  }, []);

  useEffect(() => stop, [stop]);

  const start = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus("unavailable");
      return;
    }
    setStatus("starting");
    accRef.current = new DeliveryAccumulator();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, facingMode: "user" },
        audio: false,
      });
      streamRef.current = stream;
      const video = videoRef.current;
      if (!video) throw new Error("no video element");
      video.srcObject = stream;
      await video.play();
      const { FaceLandmarker, FilesetResolver } = await import("@mediapipe/tasks-vision");
      const fileset = await FilesetResolver.forVisionTasks(WASM_URL);
      landmarkerRef.current = (await FaceLandmarker.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: MODEL_URL },
        runningMode: "VIDEO",
        numFaces: 1,
      })) as unknown as Landmarker;
      startedAt.current = Date.now();
      timerRef.current = window.setInterval(() => {
        const v = videoRef.current;
        const lm = landmarkerRef.current;
        if (!v || !lm || v.readyState < 2) return;
        try {
          const result = lm.detectForVideo(v, performance.now());
          const face = result.faceLandmarks[0];
          accRef.current.add(face ? sampleFromLandmarks(face) : { box: null, yaw: null });
        } catch {
          // A dropped frame is fine; delivery notes are optional.
        }
      }, SAMPLE_EVERY_MS);
      setStatus("on");
    } catch (e) {
      stop();
      const denied = e instanceof DOMException && e.name === "NotAllowedError";
      setStatus(denied ? "denied" : "unavailable");
    }
  }, [stop]);

  /** Aggregates for the API, or null when there is too little to say. Call before `stop()`. */
  const summary = useCallback(
    (paceWpm: number | null): DeliverySummary | null =>
      accRef.current.summary((Date.now() - startedAt.current) / 1000, paceWpm),
    [],
  );

  /** Callback ref for the (local, muted) preview element. */
  const attachVideo = useCallback((el: HTMLVideoElement | null) => {
    videoRef.current = el;
  }, []);

  return { status, attachVideo, start, stop, summary };
}
