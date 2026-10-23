export function formatTime(seconds: number, decimals = false): string {
  const value = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const ticks = Math.round(value * 10);
  const whole = decimals ? Math.floor(ticks / 10) : Math.floor(value);
  const time = `${String(Math.floor(whole / 60)).padStart(2, '0')}:${String(whole % 60).padStart(2, '0')}`;
  return decimals ? `${time}.${ticks % 10}` : time;
}

export function parseTime(value?: string): number {
  if (!value) return 0;
  if (!value.includes(':')) return Number(value);
  const parts = value.split(':');
  return Number(parts[0]) * 60 + Number(parts[1]);
}

export function formatSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '—';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function fileName(url?: string): string {
  if (!url) return '尚未上传源视频';
  try { return decodeURIComponent(url.split(/[?#]/)[0].split('/').pop() || '源视频'); }
  catch { return '源视频'; }
}

export function mediaUrl(url?: string): string | undefined {
  return url && /^(https?:|blob:)/i.test(url) ? url : undefined;
}

export function aspectRatio(width: number, height: number): string {
  const divisor = (a: number, b: number): number => b ? divisor(b, a % b) : a;
  if (!(width > 0 && height > 0)) return '—';
  const gcd = divisor(width, height);
  return `${width / gcd}:${height / gcd}`;
}

export function readVideoMetadata(file: File): Promise<{ duration: number; width: number; height: number }> {
  return new Promise((resolve) => {
    const video = document.createElement('video');
    const url = URL.createObjectURL(file);
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      resolve({ duration: Number.isFinite(video.duration) ? video.duration : 0, width: video.videoWidth, height: video.videoHeight });
      video.removeAttribute('src');
      video.load();
      URL.revokeObjectURL(url);
    };
    const timer = window.setTimeout(finish, 5000);
    video.preload = 'metadata';
    video.onloadedmetadata = finish;
    video.onerror = finish;
    video.src = url;
  });
}
