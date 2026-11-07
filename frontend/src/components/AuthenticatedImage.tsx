import { useEffect, useState } from 'react';
import { fetchAuthenticatedImage } from '../api/client';

type Props = { src: string; alt: string; className?: string };

export default function AuthenticatedImage({ src, alt, className }: Props) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let createdUrl: string | null = null;
    setObjectUrl(null);
    setFailed(false);

    fetchAuthenticatedImage(src, controller.signal)
      .then((blob) => {
        if (controller.signal.aborted) return;
        createdUrl = URL.createObjectURL(blob);
        setObjectUrl(createdUrl);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });

    return () => {
      controller.abort();
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [src]);

  if (failed) return <span className={className} role="img" aria-label={alt}>Image unavailable</span>;
  if (!objectUrl) return <span className={className} aria-label={`Loading ${alt}`} />;
  return <img src={objectUrl} alt={alt} className={className} />;
}
