"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { authApiUrl, fetchVerifiedSession } from "@/lib/auth-state";

type Challenge = {
  challenge_id: string;
  public_options: Record<string, unknown>;
};

function decode(value: string): ArrayBuffer {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const bytes = Uint8Array.from(atob(normalized), (character) => character.charCodeAt(0));
  return bytes.buffer;
}

function encode(value: ArrayBuffer): string {
  const bytes = new Uint8Array(value);
  let binary = "";
  bytes.forEach((byte) => (binary += String.fromCharCode(byte)));
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function creationOptions(raw: Record<string, unknown>): PublicKeyCredentialCreationOptions {
  const user = raw.user as Record<string, unknown>;
  const excluded = (raw.excludeCredentials ?? []) as Array<Record<string, unknown>>;
  return {
    ...(raw as unknown as PublicKeyCredentialCreationOptions),
    challenge: decode(raw.challenge as string),
    user: { ...(user as unknown as PublicKeyCredentialUserEntity), id: decode(user.id as string) },
    excludeCredentials: excluded.map((item) => ({
      ...(item as unknown as PublicKeyCredentialDescriptor),
      id: decode(item.id as string),
    })),
  };
}

function requestOptions(raw: Record<string, unknown>): PublicKeyCredentialRequestOptions {
  const allowed = (raw.allowCredentials ?? []) as Array<Record<string, unknown>>;
  return {
    ...(raw as unknown as PublicKeyCredentialRequestOptions),
    challenge: decode(raw.challenge as string),
    allowCredentials: allowed.map((item) => ({
      ...(item as unknown as PublicKeyCredentialDescriptor),
      id: decode(item.id as string),
    })),
  };
}

function serializeRegistration(credential: PublicKeyCredential) {
  const response = credential.response as AuthenticatorAttestationResponse;
  return {
    id: credential.id,
    rawId: encode(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment,
    response: {
      clientDataJSON: encode(response.clientDataJSON),
      attestationObject: encode(response.attestationObject),
      transports: response.getTransports?.() ?? [],
    },
  };
}

function serializeAuthentication(credential: PublicKeyCredential) {
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    id: credential.id,
    rawId: encode(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment,
    response: {
      clientDataJSON: encode(response.clientDataJSON),
      authenticatorData: encode(response.authenticatorData),
      signature: encode(response.signature),
      userHandle: response.userHandle ? encode(response.userHandle) : null,
    },
  };
}

export default function MfaPage() {
  const router = useRouter();
  const [state, setState] = useState<string | null>(null);
  const [csrf, setCsrf] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);

  useEffect(() => {
    fetchVerifiedSession().then((session) => {
      setState(session.state);
      setCsrf(session.csrfToken);
      if (session.state === "ANONYMOUS") router.replace("/auth/exchange");
      if (session.state === "AUTHENTICATED") router.replace("/dashboard");
    });
  }, [router]);

  async function post(path: string, body: unknown) {
    const response = await fetch(authApiUrl(`/auth${path}`), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf ?? "" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message ?? "MFA 요청에 실패했습니다.");
    return payload;
  }

  async function verify() {
    if (!csrf || !window.PublicKeyCredential) {
      setError("이 브라우저에서 WebAuthn을 사용할 수 없습니다.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const enrollment = state === "MFA_ENROLLMENT_REQUIRED";
      const challenge = (await post(
        enrollment ? "/mfa/enrollments" : "/mfa/challenges",
        enrollment ? { method: "WEBAUTHN" } : { purpose: "STEP_UP", method: "WEBAUTHN" },
      )) as Challenge;
      const credential = enrollment
        ? await navigator.credentials.create({ publicKey: creationOptions(challenge.public_options) })
        : await navigator.credentials.get({ publicKey: requestOptions(challenge.public_options) });
      if (!(credential instanceof PublicKeyCredential)) throw new Error("인증이 취소되었습니다.");
      const proof = enrollment
        ? serializeRegistration(credential)
        : serializeAuthentication(credential);
      const result = await post(`/mfa/challenges/${challenge.challenge_id}/verify`, {
        webauthn_response: proof,
      });
      setRecoveryCodes(result.recovery_codes ?? null);
      if (!result.recovery_codes) {
        router.replace("/dashboard");
        router.refresh();
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "MFA 인증에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-5 p-6">
      <h1 className="text-2xl font-semibold">관리자 WebAuthn 인증</h1>
      <p className="text-sm text-[var(--color-text-muted)]">
        Windows Hello·Touch ID·보안키 등 사용자 확인 가능 인증기로 AAL2를 확립합니다.
      </p>
      {error ? <p role="alert" className="text-sm text-[var(--color-danger)]">{error}</p> : null}
      {recoveryCodes ? (
        <section className="rounded-lg border border-[var(--color-border)] p-4">
          <h2 className="font-semibold">복구 코드를 안전하게 보관하세요</h2>
          <p className="my-2 text-sm">이 화면에서 한 번만 표시됩니다.</p>
          <ol className="grid grid-cols-2 gap-2 font-mono text-sm">
            {recoveryCodes.map((code) => <li key={code}>{code}</li>)}
          </ol>
          <button type="button" onClick={() => router.replace("/dashboard")} className="mt-4 rounded-md bg-[var(--color-brand)] px-4 py-2 text-[var(--color-brand-contrast)]">
            보관했습니다
          </button>
        </section>
      ) : (
        <button type="button" disabled={busy || !csrf} onClick={() => void verify()} className="tap-target rounded-md bg-[var(--color-brand)] px-4 py-3 font-medium text-[var(--color-brand-contrast)] disabled:opacity-50">
          {busy ? "인증 중…" : state === "MFA_ENROLLMENT_REQUIRED" ? "WebAuthn 등록" : "WebAuthn으로 인증"}
        </button>
      )}
    </main>
  );
}
