/**
 * The renderer's own library, driven directly instead of through its CLI.
 *
 * Two things the CLI cannot give us, both of which the library exports:
 *
 *   1. **The measured document.** `outputs: { json: true }` returns every entity's final box and
 *      every connection's ROUTED POINTS. Without it "no arrow crosses a component" is an opinion
 *      formed by looking at a PNG; with it, it is a check. The CLI exposes png and html only.
 *   2. **The icon transform.** `normalizeFetchedIcon` inlines style classes, sanitises, ensures a
 *      viewBox and prefixes every internal id. The renderer applies it to what IT fetches and
 *      returns a cache hit verbatim — so icons we put in the cache ourselves are the only ones
 *      that skip it. Every official AWS SVG declares `<rect id="Rectangle">`; several on one page
 *      collide, and a `url(#id)` gradient then resolves to whichever icon loaded first. Calling
 *      the renderer's own function means our normalisation cannot drift from theirs.
 *
 * One request object on stdin, one report on stdout. Both modes stay in one file because they
 * share the only hard part: finding the pinned install and importing out of it.
 *
 *   echo '{"mode":"render", ...}' | node render.mjs
 *   echo '{"mode":"normalize","icons":[{"name":"s3","svg":"<svg .../>"}]}' | node render.mjs
 *
 * Exit 0 when the report says `ok`, 1 otherwise. Never throws past main: the diagram is a
 * required output and a stack trace on stderr is not a diagnosis.
 */

import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

/** The pinned install, imported by absolute path: this file does not sit above its node_modules. */
async function library(rendererDir) {
  const entry = join(rendererDir, 'node_modules', '@eraserlabs', 'diagrams', 'dist', 'index.js')
  return import(pathToFileURL(entry).href)
}

async function readStdin() {
  const chunks = []
  for await (const chunk of process.stdin) chunks.push(chunk)
  return Buffer.concat(chunks).toString('utf8')
}

async function normalize(request) {
  const { normalizeFetchedIcon } = await library(request.rendererDir)
  const icons = {}
  for (const icon of request.icons ?? []) {
    icons[icon.name] = normalizeFetchedIcon(icon.svg, icon.name)
  }
  return { ok: true, mode: 'normalize', icons }
}

async function render(request) {
  const { createRenderer, createEraserIconLoader, stockLibrary } = await library(request.rendererDir)

  const options = {
    chromiumPath: request.chromiumPath,
    onUnknownIcon: request.unknownIcon ?? 'error',
    deviceScaleFactor: request.scale ?? 2,
  }

  // The design system, sections E-G. Most of it is authored per entity — fill, border, radius,
  // title chip, font size, label colour are all real props — but weight, letter-spacing, case,
  // the shadow and the icon caption are hardcoded in the stock templates with no prop behind
  // them. `library.baseCss` is the renderer's own theming channel: it is injected unscoped and
  // unlinted, so bare selectors reach inside every template. Appending rather than replacing
  // means an upgrade keeps its own base and only our overrides ride on top.
  if (request.theme?.baseCss) {
    options.library = { ...stockLibrary, baseCss: stockLibrary.baseCss + '\n' + request.theme.baseCss }
  }
  if (request.theme?.fonts) {
    options.fonts = request.theme.fonts
  }
  if (request.cacheDir) {
    await mkdir(request.cacheDir, { recursive: true })
    // A long TTL because the cache is authoritative here. The loader re-fetches a stale entry from
    // Eraser's own bucket, which 404s for every name we injected — harmless (it falls back to the
    // cached bytes) but it is a doomed request per icon per render.
    options.iconLoader = createEraserIconLoader({
      cacheDir: request.cacheDir,
      cacheTtlMs: request.cacheTtlMs ?? 30 * 24 * 60 * 60 * 1000,
    })
  }

  const document = request.document ?? JSON.parse(await readFile(request.documentPath, 'utf8'))
  const outputs = { png: Boolean(request.png), html: Boolean(request.html), json: Boolean(request.json) }

  const renderer = await createRenderer(options)
  try {
    const result = await renderer.render({ ...document, outputs })
    if (!result.ok) {
      return { ok: false, mode: 'render', errors: result.errors, warnings: result.warnings }
    }
    if (request.png) await writeFile(request.png, result.png)
    if (request.html) await writeFile(request.html, result.html, 'utf8')
    if (request.json) {
      await writeFile(request.json, JSON.stringify(result.json, null, 2) + '\n', 'utf8')
    }
    return {
      ok: true,
      mode: 'render',
      warnings: result.warnings,
      degradedFonts: renderer.degradedFonts,
      scene: result.json?.scene ?? null,
      fonts: options.fonts ? Object.values(options.fonts.roles ?? {}) : null,
      themed: Boolean(options.library),
      timingsMs: result.timingsMs,
    }
  } finally {
    await renderer.close()
  }
}

async function main() {
  let request
  try {
    request = JSON.parse(await readStdin())
  } catch (err) {
    process.stdout.write(JSON.stringify({ ok: false, error: `unreadable request: ${err.message}` }))
    return 1
  }
  let report
  try {
    report = request.mode === 'normalize' ? await normalize(request) : await render(request)
  } catch (err) {
    report = { ok: false, mode: request.mode ?? 'render', error: String(err?.message ?? err) }
  }
  process.stdout.write(JSON.stringify(report))
  return report.ok ? 0 : 1
}

process.exitCode = await main()
