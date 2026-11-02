import { useEffect, useRef } from 'react';
import { oauthApi } from '../services/oauthApi';

// Google Identity Services (GSI) — loads the official `gsi/client` script
// once and renders the Google-branded button via `google.accounts.id.
// renderButton`. We use GSI's `id_token` flow (not OAuth2 access token) so
// the backend can keep its `aud === GOOGLE_CLIENT_ID` check — any other
// flow would require backend changes to stay secure.
//
// The old flow used gapi auth2 + a custom-styled button; gapi auth2 was
// sunset by Google in 2023-03, so we replaced the whole thing.
const GSI_SRC = 'https://accounts.google.com/gsi/client';
const GSI_SCRIPT_ID = 'gsi-client-sdk';

type GoogleProfile = { email: string; name?: string };

type Props = {
  onSuccess: (accessToken: string, profile: GoogleProfile) => void;
  onError: (message: string) => void;
  /** 'signin' | 'signup' — changes the button label via GSI's `text` prop. */
  intent?: 'signin' | 'signup';
  locale?: string;
};

// GSI returns a standard JWT id_token in `credential`. We only need its
// payload (middle segment) for the email, so a plain base64 decode is
// enough — no signature verification on the client, since the backend
// already re-verifies via oauth2.googleapis.com/tokeninfo.
function decodeGsiProfile(credential: string): GoogleProfile | null {
  try {
    const payload = credential.split('.')[1];
    const padded = payload.replace(/-/g, '+').replace(/_/g, '/');
    const json = atob(padded);
    const claims = JSON.parse(json);
    if (!claims.email) return null;
    return { email: claims.email, name: claims.name };
  } catch {
    return null;
  }
}

function ensureGsiScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if ((window as any).google?.accounts?.id) {
      resolve();
      return;
    }
    const existing = document.getElementById(GSI_SCRIPT_ID) as HTMLScriptElement | null;
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true });
      existing.addEventListener('error', () => reject(new Error('GSI script failed to load')), { once: true });
      return;
    }
    const script = document.createElement('script');
    script.id = GSI_SCRIPT_ID;
    script.src = GSI_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('GSI script failed to load'));
    document.head.appendChild(script);
  });
}

export function GoogleSignInButton({ onSuccess, onError, intent = 'signin', locale }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;
    if (!clientId) {
      onError('VITE_GOOGLE_CLIENT_ID is not configured');
      return;
    }

    let cancelled = false;

    ensureGsiScript()
      .then(() => {
        if (cancelled || !containerRef.current) return;
        const google = (window as any).google;

        google.accounts.id.initialize({
          client_id: clientId,
          callback: async (response: { credential?: string }) => {
            if (!response?.credential) {
              onError('Google login failed');
              return;
            }
            const profile = decodeGsiProfile(response.credential);
            if (!profile) {
              onError('Google login failed: invalid credential');
              return;
            }
            try {
              const res = await oauthApi.googleLogin(response.credential);
              onSuccess(res.access_token, profile);
            } catch (err) {
              onError(err instanceof Error ? err.message : 'Google login failed');
            }
          },
        });

        // renderButton requires a fixed pixel width. Use the container's
        // live width so the button matches the surrounding form width.
        const width = Math.min(Math.max(containerRef.current.offsetWidth || 320, 240), 400);
        google.accounts.id.renderButton(containerRef.current, {
          theme: 'outline',
          size: 'large',
          type: 'standard',
          shape: 'rectangular',
          text: intent === 'signup' ? 'signup_with' : 'continue_with',
          logo_alignment: 'center',
          width,
          locale,
        });
      })
      .catch((err: Error) => {
        if (!cancelled) onError(err.message);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intent, locale]);

  return <div ref={containerRef} className="flex justify-center" />;
}
