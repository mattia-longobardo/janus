/** A post-login target: only same-origin relative paths ("/x"); anything else becomes "/". */
export function safeCallbackUrl(url: string | undefined): string {
  if (!url || !url.startsWith("/") || url.startsWith("//") || url.startsWith("/\\")) return "/";
  // Browsers strip tabs and newlines from URLs, so "/\t/x" would turn into "//x".
  if (/[\u0000-\u001f\u007f]/.test(url)) return "/";
  return url;
}
