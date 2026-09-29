#!/usr/bin/env bash
# Assembles the website (https://elkayem.github.io/swingscribe/) into $1,
# default _site. The landing page lives here in site/; the user guide, the
# README's images and the app icon are copied from where they already live,
# so each keeps one source. .github/workflows/pages.yml runs this; run it by
# hand to preview the site locally.
set -euo pipefail

out="${1:-_site}"
root="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$out/guide" "$out/images"
cp "$root/site/index.html" "$root/site/sitemap.xml" "$out/"
cp "$root/src/swingscribe/gui/guide/index.html" "$root/src/swingscribe/gui/guide/user-guide.md" "$out/guide/"
cp "$root"/docs/images/*.png "$out/images/"
cp "$root/assets/swingscribe.ico" "$out/favicon.ico"
