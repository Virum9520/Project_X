import { LogLevel, setLogLevel } from "livekit-client";

/**
 * LiveKit logs "error reading from signal stream" via console.error whenever a call ends and the
 * signal socket closes. That is expected on every session end, and Next's dev overlay shows it as
 * a runtime error. Real failures still reach us through the conversation's `onError`.
 */
setLogLevel(LogLevel.silent);
