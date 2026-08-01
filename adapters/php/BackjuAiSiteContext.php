<?php

declare(strict_types=1);

/**
 * Build signed headers for a server-to-server call to the matching API.
 *
 * Resolve $subject from the host site's authenticated/guest session. Never
 * send $siteContextSecret or run this signer in browser JavaScript.
 *
 * @param array{
 *   tenant_id: string,
 *   event_id: string,
 *   profile_id: string,
 *   visit_session_id?: string|null,
 *   user_id?: string|null,
 *   guest_session_id?: string|null
 * } $subject
 * @return array<string, string>
 */
function backjuAiSiteContextHeaders(
    array $subject,
    string $siteContextSecret,
    ?int $timestamp = null
): array {
    $timestamp ??= time();
    $values = [
        'x-tenant-id' => $subject['tenant_id'],
        'x-event-id' => $subject['event_id'],
        'x-profile-id' => $subject['profile_id'],
        'x-visit-session-id' => $subject['visit_session_id'] ?? '',
        'x-user-id' => $subject['user_id'] ?? '',
        'x-guest-session-id' => $subject['guest_session_id'] ?? '',
    ];

    $hasUser = $values['x-user-id'] !== '';
    $hasGuest = $values['x-guest-session-id'] !== '';
    if ($hasUser === $hasGuest) {
        throw new InvalidArgumentException(
            'Exactly one of user_id or guest_session_id is required.'
        );
    }

    $canonicalLines = [(string) $timestamp];
    foreach ($values as $name => $value) {
        $canonicalLines[] = $name . ':' . trim($value);
    }
    $canonicalPayload = implode("\n", $canonicalLines);
    $signature = 'v1=' . hash_hmac(
        'sha256',
        $canonicalPayload,
        $siteContextSecret
    );

    return [
        'X-Tenant-Id' => $values['x-tenant-id'],
        'X-Event-Id' => $values['x-event-id'],
        'X-Profile-Id' => $values['x-profile-id'],
        'X-Visit-Session-Id' => $values['x-visit-session-id'],
        'X-User-Id' => $values['x-user-id'],
        'X-Guest-Session-Id' => $values['x-guest-session-id'],
        'X-Site-Context-Timestamp' => (string) $timestamp,
        'X-Site-Context-Signature' => $signature,
    ];
}
