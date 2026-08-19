/**
 * Two build modes:
 *
 *  - Development / server mode (default): `npm run dev`, API on a separate origin.
 *  - Desktop mode (`RRG_DESKTOP_BUILD=1`): a static export written to `out/`, which the
 *    FastAPI process serves itself. This is what removes Node from the runtime entirely and
 *    makes a single-file .exe possible.
 *
 * In desktop mode NEXT_PUBLIC_API_BASE is deliberately the empty string, so the client
 * issues same-origin relative requests ("/api/rrg") to whichever port the packaged app
 * happens to bind. Note the `??` in the fallback below rather than `||`: an empty string is
 * a meaningful value here and must not be replaced by the localhost default.
 */

const desktop = process.env.RRG_DESKTOP_BUILD === "1";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  ...(desktop
    ? {
        output: "export",
        // The exported files are served from the filesystem, so directory-style URLs
        // ("/index.html") are what StaticFiles resolves.
        trailingSlash: true,
        images: { unoptimized: true },
      }
    : {}),
  env: {
    NEXT_PUBLIC_API_BASE: desktop
      ? ""
      : (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000"),
  },
};

export default nextConfig;
