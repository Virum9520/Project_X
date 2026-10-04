/** Future-Self voice (C19): `/v1/future-self/*`. The provider voice id never leaves the server. */

export interface ConsentRecordView {
  id: string;
  consent_version: string;
  created_at: string;
  revoked_at: string | null;
  voice_active: boolean;
}

/** `GET /v1/future-self/consent` */
export interface ConsentStatus {
  consent_version: string;
  statements: string[];
  active: boolean;
  current: ConsentRecordView | null;
  history: ConsentRecordView[];
}

/** `POST /v1/future-self/consent/challenge` */
export interface ConsentChallenge {
  phrase: string;
  challenge_token: string;
  expires_at: string;
  consent_version: string;
  statements: string[];
}

/** `POST /v1/future-self/consent/recording` (raw audio body; challenge and acceptance in headers). */
export interface ConsentRecordingResult {
  verified: boolean;
  similarity: number;
  words_heard: boolean;
  transcript: string;
  status: ConsentStatus;
}

/** `POST /v1/future-self/message` */
export interface FutureSelfMessage {
  script: string;
  audio_base64: string;
  media_type: string;
}
