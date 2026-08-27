#!/usr/bin/env python3
# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""Push Play Store LISTING assets to the Google Play Edits API.

The universal-play-deploy workflow uploads the AAB via the standard
marketplace action; this script covers what that action does not — the
store listing's marketing assets — by driving the Google Play Developer
(Edits) API directly with google-api-python-client. Deliberately Python,
not fastlane, matching the rest of this repo's tooling (see the comment
above the AAB upload step in universal-play-deploy.yml).

Convention over configuration — assets are discovered in the calling
app's checkout, exactly where the tour pipeline writes them:

  marketing/tour/store/*.png|jpg|jpeg|webp
      Classified by DIMENSIONS, never by filename:
        - exactly 1024x500  -> featureGraphic (first in filename order
          wins when several qualify; the rest are logged and skipped)
        - exactly 512x512   -> icon (the tour pipeline renders
          store/icon-512.png; first in filename order wins, the rest
          are logged and skipped)
        - portrait (taller than wide), every side within Play's
          320-3840px screenshot bounds -> phoneScreenshots, uploaded in
          sorted filename order, capped at Play's limit of 8 with every
          skipped file named in the log (no silent caps)
      Anything else (wrong shape, out of bounds, over Play's 15MB image
      limit, unreadable) is logged and skipped — one bad file never
      fails the deploy.

  marketing/tour/tablet/store/*.png|jpg|jpeg|webp
      The tour pipeline's TABLET leg writes its styled stills here
      (1600x2560, a 10-inch portrait canvas) — classified by DIRECTORY:
      every portrait image within Play's 320-3840px bounds ->
      tenInchScreenshots, uploaded in sorted filename order, capped at
      Play's limit of 8 with every skipped file named. The tablet leg
      never writes a feature graphic or icon here (those exist once per
      listing and come from the phone dir above); anything non-portrait
      or out of bounds is logged and skipped. Mapped to
      tenInchScreenshots only, NOT sevenInchScreenshots: the tablet leg
      runs a 10-inch-class geometry (1600x2560 at 320dpi, sw800dp), and
      the phone set at 1080x1920 already shows the handset/7-inch-class
      content — duplicating the 10-inch layouts into the sevenInch slot
      would misrepresent what a 7-inch device renders.

  marketing/store/screenshots.txt
      Optional curated pick-list for the phoneScreenshots: one still
      key per line (a marketing/tour/store/ filename, with or without
      its extension), blank lines and '#' comment lines ignored. The
      listed order IS the Play order; keys that match no discovered
      portrait screenshot are logged and skipped; over 8 keys, the
      first 8 win (logged). When the file is absent, holds no
      effective lines, or matches nothing, the default first-8-by-
      filename behavior above applies unchanged.

  marketing/store/listing/<locale>/title.txt
                            /short_description.txt
                            /full_description.txt
      The listing's TEXT, one directory per BCP-47 locale (en-US now;
      drop in more locale directories later for translations — every
      locale directory found is pushed). title.txt and
      short_description.txt are single-line: blank lines and '#'
      comment lines are ignored, the first remaining line is the
      value. full_description.txt is multi-line: only LEADING blank
      and '#' comment lines are stripped, the rest of the body is kept
      verbatim. Play's limits are validated per field (title 30,
      short 80, full 4000 chars) — an over-limit field is skipped with
      a loud log, never truncated silently. Only fields with content
      are patched (existing listing fetched first); a field whose file
      is absent or placeholder-only is left exactly as it is in Play —
      nothing is ever blanked.

  marketing/store/video.txt
      Holds the YouTube URL for the listing's promo-video slot: blank
      lines and '#' comment lines are ignored, the first remaining line
      is the URL (the tour pipeline seeds a comment-only placeholder). Play does NOT accept video file uploads through the API —
      the reel itself must be published to YouTube once, by a human;
      this script only points the listing at it, patching ONLY the
      `video` field of the existing listing (titles/descriptions are
      fetched first and left untouched).

Edits flow: edits.insert -> per locale with listing text:
listings.patch (only the fields with repo content) -> per image type
with local candidates: images.deleteall then upload in sorted order ->
listings.patch (video only, when video.txt exists) -> edits.commit.

Exits 0 with a clear log when the checkout ships no store assets (apps
without marketing assets deploy unchanged). Exits non-zero, loudly, on
API/auth errors. --dry-run prints exactly what would be uploaded and
needs neither credentials nor the Google API packages installed.
"""

import argparse
import os
import sys

STORE_DIR = os.path.join("marketing", "tour", "store")
# The tablet leg's store stills live in their own directory precisely so
# they can be classified by location (tenInchScreenshots) instead of by
# dimensions — a 1600x2560 still is otherwise indistinguishable from a
# large phone screenshot.
TABLET_STORE_DIR = os.path.join("marketing", "tour", "tablet", "store")
VIDEO_FILE = os.path.join("marketing", "store", "video.txt")
SCREENSHOTS_FILE = os.path.join("marketing", "store", "screenshots.txt")
LISTING_DIR = os.path.join("marketing", "store", "listing")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
# Play Developer API listing-image rules.
MAX_IMAGE_BYTES = 15 * 1024 * 1024  # any listing image: at most 15MB
FEATURE_W, FEATURE_H = 1024, 500    # featureGraphic: exactly 1024x500
ICON_W, ICON_H = 512, 512           # icon: exactly 512x512
PHONE_MIN_PX, PHONE_MAX_PX = 320, 3840  # screenshots: every side in bounds
PHONE_MAX_COUNT = 8                 # at most 8 screenshots per type
# Play Console listing-text limits (characters), per field.
LISTING_TEXT_FIELDS = (
    # (API field, filename, char limit, single-line?)
    ("title", "title.txt", 30, True),
    ("shortDescription", "short_description.txt", 80, True),
    ("fullDescription", "full_description.txt", 4000, False),
)
OAUTH_SCOPE = "https://www.googleapis.com/auth/androidpublisher"


def log(message):
    print(f"[listing-assets] {message}", flush=True)


def warn(message):
    """Loud skip: a GitHub Actions warning annotation, never fatal."""
    print(f"::warning::[listing-assets] {message}", flush=True)


def fail(message):
    print(f"::error::[listing-assets] {message}", file=sys.stderr, flush=True)
    sys.exit(1)


def effective_lines(path):
    """The file's stripped lines minus blanks and '#' comments, or None.

    None means the file could not be read (already logged); an empty
    list means it exists but holds no effective content (placeholder).
    """
    try:
        with open(path, encoding="utf-8") as handle:
            return [
                stripped
                for line in handle
                if (stripped := line.strip()) and not stripped.startswith("#")
            ]
    except OSError as e:
        log(f"could not read {path} ({e})")
        return None


def image_size(path):
    """(width, height) of the image, or None (logged) when unreadable."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except OSError as e:
        log(f"skipping {path}: unreadable as an image ({e})")
        return None


def read_curated_keys(app_dir):
    """The screenshots.txt pick-list as a list of keys, or None.

    None means no curation (file absent, unreadable, or holding only
    blank/comment lines — the seeded placeholder state): the default
    first-8-by-filename ordering applies.
    """
    path = os.path.join(app_dir, SCREENSHOTS_FILE)
    if not os.path.isfile(path):
        return None
    keys = effective_lines(path)
    if not keys:
        log(
            f"{path} holds no screenshot keys (blank/comment lines only) — "
            "using the default first-8-by-filename screenshot order"
        )
        return None
    return keys


def curate_screenshots(screenshots, curated_keys, store_dir):
    """Order `screenshots` by the pick-list; unmatched keys skip-and-log.

    Keys match a discovered portrait screenshot's filename with or
    without its extension. Returns the curated list (uncapped), or None
    when nothing matched — the caller falls back to the default order.
    """
    by_key = {}
    for path in screenshots:
        name = os.path.basename(path)
        by_key[name] = path
        by_key[os.path.splitext(name)[0]] = path
    ordered = []
    for key in curated_keys:
        path = by_key.get(key)
        if path is None:
            warn(
                f"screenshots.txt: no portrait screenshot named {key!r} "
                f"in {store_dir} — key skipped"
            )
        elif path in ordered:
            log(f"screenshots.txt: duplicate key {key!r} — already listed, skipped")
        else:
            ordered.append(path)
    if not ordered:
        warn(
            "screenshots.txt matched none of the discovered screenshots — "
            "falling back to the default first-8-by-filename order"
        )
        return None
    log(
        f"screenshots.txt curates {len(ordered)} of {len(screenshots)} "
        "discovered screenshots (listed order wins)"
    )
    return ordered


def discover_images(store_dir, curated_keys=None):
    """Classify the store dir's images: {imageType: [paths in upload order]}.

    Classification is by dimensions only (the feature graphic and icon
    are excluded from the screenshots by their shape, not their names).
    Invalid files are logged and skipped, never fatal. The
    phoneScreenshots order is the screenshots.txt pick-list when one is
    in effect, else sorted filename order; either way the list is
    capped at Play's limit of {PHONE_MAX_COUNT} with every skipped file
    named.
    """
    feature_graphics = []
    icons = []
    screenshots = []
    for name in sorted(os.listdir(store_dir)):
        path = os.path.join(store_dir, name)
        if not os.path.isfile(path) or not name.lower().endswith(IMAGE_EXTENSIONS):
            continue
        size_bytes = os.path.getsize(path)
        if size_bytes > MAX_IMAGE_BYTES:
            log(
                f"skipping {path}: {size_bytes / 1_000_000:.1f} MB exceeds "
                f"Play's {MAX_IMAGE_BYTES // (1024 * 1024)}MB listing-image limit"
            )
            continue
        dimensions = image_size(path)
        if dimensions is None:
            continue
        width, height = dimensions
        if (width, height) == (FEATURE_W, FEATURE_H):
            feature_graphics.append(path)
        elif (width, height) == (ICON_W, ICON_H):
            icons.append(path)
        elif height > width and all(
            PHONE_MIN_PX <= side <= PHONE_MAX_PX for side in (width, height)
        ):
            screenshots.append(path)
        else:
            log(
                f"skipping {path}: {width}x{height} is neither a portrait "
                f"phone screenshot ({PHONE_MIN_PX}-{PHONE_MAX_PX}px per side), "
                f"a {FEATURE_W}x{FEATURE_H} feature graphic, nor a "
                f"{ICON_W}x{ICON_H} icon"
            )

    assets = {}
    if feature_graphics:
        assets["featureGraphic"] = feature_graphics[:1]
        for extra in feature_graphics[1:]:
            log(
                f"skipping {extra}: already using "
                f"{feature_graphics[0]} as the feature graphic"
            )
    if icons:
        assets["icon"] = icons[:1]
        for extra in icons[1:]:
            log(f"skipping {extra}: already using {icons[0]} as the icon")
    if curated_keys and screenshots:
        curated = curate_screenshots(screenshots, curated_keys, store_dir)
        if curated is not None:
            screenshots = curated
    if screenshots:
        assets["phoneScreenshots"] = screenshots[:PHONE_MAX_COUNT]
        for over_cap in screenshots[PHONE_MAX_COUNT:]:
            log(
                f"skipping {over_cap}: over Play's {PHONE_MAX_COUNT}-image "
                "phoneScreenshots cap (first "
                f"{PHONE_MAX_COUNT} in the order above win)"
            )
    return assets


def discover_tablet_screenshots(tablet_store_dir):
    """The tablet store dir's stills, in upload order: tenInchScreenshots.

    Classification is by DIRECTORY, not dimensions — the tour pipeline's
    tablet leg writes only its styled portrait stills here (never a
    feature graphic or icon; those stay with the phone run). Every
    portrait image within Play's 320-3840px per-side bounds qualifies;
    anything else (wrong shape, out of bounds, over the 15MB limit,
    unreadable) is logged and skipped, never fatal. Sorted filename
    order, capped at Play's per-type limit of 8 with every skipped file
    named — the same overflow logging as phoneScreenshots. The
    screenshots.txt pick-list stays phone-only: its keys name
    marketing/tour/store/ files, and the tablet stills mirror the same
    step keys/order anyway.
    """
    screenshots = []
    for name in sorted(os.listdir(tablet_store_dir)):
        path = os.path.join(tablet_store_dir, name)
        if not os.path.isfile(path) or not name.lower().endswith(IMAGE_EXTENSIONS):
            continue
        size_bytes = os.path.getsize(path)
        if size_bytes > MAX_IMAGE_BYTES:
            log(
                f"skipping {path}: {size_bytes / 1_000_000:.1f} MB exceeds "
                f"Play's {MAX_IMAGE_BYTES // (1024 * 1024)}MB listing-image limit"
            )
            continue
        dimensions = image_size(path)
        if dimensions is None:
            continue
        width, height = dimensions
        if height > width and all(
            PHONE_MIN_PX <= side <= PHONE_MAX_PX for side in (width, height)
        ):
            screenshots.append(path)
        else:
            log(
                f"skipping {path}: {width}x{height} is not a portrait tablet "
                f"screenshot ({PHONE_MIN_PX}-{PHONE_MAX_PX}px per side)"
            )
    capped = screenshots[:PHONE_MAX_COUNT]
    for over_cap in screenshots[PHONE_MAX_COUNT:]:
        log(
            f"skipping {over_cap}: over Play's {PHONE_MAX_COUNT}-image "
            "tenInchScreenshots cap (first "
            f"{PHONE_MAX_COUNT} in filename order win)"
        )
    return capped


def discover_listing_texts(app_dir):
    """The repo's listing text: {locale: {API field: text}}.

    One marketing/store/listing/<locale>/ directory per locale — every
    locale directory found is pushed (the seam for translations).
    Placeholder-only and over-limit fields are skipped (logged); a
    locale contributes only the fields that have valid content.
    """
    listing_root = os.path.join(app_dir, LISTING_DIR)
    if not os.path.isdir(listing_root):
        return {}
    texts = {}
    for locale in sorted(os.listdir(listing_root)):
        locale_dir = os.path.join(listing_root, locale)
        if not os.path.isdir(locale_dir):
            continue
        fields = {}
        for api_field, filename, limit, single_line in LISTING_TEXT_FIELDS:
            path = os.path.join(locale_dir, filename)
            if not os.path.isfile(path):
                continue
            if single_line:
                lines = effective_lines(path)
                if lines is None:
                    continue
                value = lines[0] if lines else ""
                if len(lines) > 1:
                    log(
                        f"{path} has {len(lines)} non-empty lines; "
                        "using the first (this field is single-line)"
                    )
            else:
                # Strip only LEADING blank/comment lines; keep the body
                # verbatim (a full description may legitimately contain
                # '#' lines and blank paragraph breaks).
                try:
                    with open(path, encoding="utf-8") as handle:
                        body_lines = handle.readlines()
                except OSError as e:
                    log(f"could not read {path} ({e})")
                    continue
                start = 0
                while start < len(body_lines) and (
                    not body_lines[start].strip()
                    or body_lines[start].lstrip().startswith("#")
                ):
                    start += 1
                value = "".join(body_lines[start:]).rstrip("\n")
            if not value:
                log(
                    f"no {api_field} set yet: {path} holds only blank/comment "
                    "lines — add the real copy to push it to the Play listing"
                )
                continue
            if len(value) > limit:
                warn(
                    f"SKIPPING {api_field} ({locale}): {len(value)} characters "
                    f"exceeds Play's {limit}-character limit for this field — "
                    f"shorten {path} (nothing was truncated or pushed)"
                )
                continue
            fields[api_field] = value
        if fields:
            texts[locale] = fields
    return texts


def discover_video(app_dir):
    """The promo video's YouTube URL from marketing/store/video.txt, or None.

    Blank lines and '#' comment lines are ignored; the first remaining
    line is the URL. A blank/comment-only file (the placeholder the tour
    pipeline seeds) is a clean "not set yet", never an error.
    """
    video_path = os.path.join(app_dir, VIDEO_FILE)
    if not os.path.isfile(video_path):
        return None
    lines = effective_lines(video_path)
    if lines is None:
        log(f"skipping promo video: could not read {video_path}")
        return None
    if not lines:
        log(
            f"no video URL set yet: {video_path} holds only blank/comment "
            "lines - add the promo reel's YouTube URL to fill the listing's "
            "video slot"
        )
        return None
    url = lines[0]
    if len(lines) > 1:
        log(f"{video_path} has {len(lines)} non-empty lines; using the first")
    if not url.startswith(("http://", "https://")) or not any(
        host in url for host in ("youtube.com", "youtu.be")
    ):
        log(
            f"skipping promo video: {url!r} does not look like a YouTube URL "
            "(Play only accepts YouTube links in the listing's video field)"
        )
        return None
    return url


def describe(path):
    dimensions = image_size(path)
    width, height = dimensions if dimensions else ("?", "?")
    return f"{path} ({width}x{height}, {os.path.getsize(path) / 1_000_000:.2f} MB)"


def upload_assets(
    package_name, service_account_json, language, assets, video_url, listing_texts
):
    """Run the edits flow for real. Raises on API/auth errors."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    credentials = service_account.Credentials.from_service_account_file(
        service_account_json, scopes=[OAUTH_SCOPE]
    )
    service = build(
        "androidpublisher", "v3", credentials=credentials, cache_discovery=False
    )
    edits = service.edits()
    edit_id = edits.insert(packageName=package_name, body={}).execute()["id"]
    log(f"opened edit {edit_id} for {package_name}")

    def get_listing(locale):
        """The locale's existing listing dict, or None when Play has none."""
        try:
            return (
                edits.listings()
                .get(packageName=package_name, editId=edit_id, language=locale)
                .execute()
            )
        except HttpError as e:
            if e.resp.status == 404:
                return None
            raise

    for locale, fields in listing_texts.items():
        # Fetch the existing listing first: fields without a repo file
        # keep whatever Play already has — the patch below carries ONLY
        # the fields with repo content, so nothing is ever blanked.
        listing = get_listing(locale)
        if listing is None:
            required = {api_field for api_field, _, _, _ in LISTING_TEXT_FIELDS}
            missing = sorted(required - set(fields))
            if missing:
                warn(
                    f"no {locale} listing exists in Play Console yet and the "
                    f"repo is missing {', '.join(missing)} — a new listing "
                    "needs title, short and full descriptions; add the "
                    f"missing files under {LISTING_DIR}/{locale}/ (or create "
                    "the listing once by hand); skipping its text"
                )
                continue
            edits.listings().update(
                packageName=package_name,
                editId=edit_id,
                language=locale,
                body={"language": locale, **fields},
            ).execute()
            log(f"listing text ({locale}): created listing with {', '.join(sorted(fields))}")
            continue
        unchanged = [f for f, v in fields.items() if listing.get(f) == v]
        to_patch = {f: v for f, v in fields.items() if listing.get(f) != v}
        for api_field in unchanged:
            log(f"listing text ({locale}): {api_field} already up to date")
        if to_patch:
            edits.listings().patch(
                packageName=package_name,
                editId=edit_id,
                language=locale,
                body={"language": locale, **to_patch},
            ).execute()
            log(
                f"listing text ({locale}): patched "
                f"{', '.join(sorted(to_patch))} from the repo"
            )

    for image_type, paths in assets.items():
        edits.images().deleteall(
            packageName=package_name,
            editId=edit_id,
            language=language,
            imageType=image_type,
        ).execute()
        log(f"{image_type} ({language}): cleared existing images")
        for path in paths:
            media = MediaFileUpload(
                path, mimetype=MIME_TYPES[os.path.splitext(path)[1].lower()]
            )
            edits.images().upload(
                packageName=package_name,
                editId=edit_id,
                language=language,
                imageType=image_type,
                media_body=media,
            ).execute()
            log(f"{image_type} ({language}): uploaded {describe(path)}")

    if video_url:
        # Fetch the current listing first: this both confirms a listing
        # exists for the language and documents that titles/descriptions
        # are left alone — the patch below carries ONLY the video field.
        listing = get_listing(language)
        if listing is None:
            log(
                f"no {language} listing exists in Play Console yet — "
                "create it (title/description) once by hand before the "
                "promo-video URL can be set; skipping the video patch"
            )
        elif listing.get("video") == video_url:
            log(f"promo video already set to {video_url}; nothing to patch")
        else:
            edits.listings().patch(
                packageName=package_name,
                editId=edit_id,
                language=language,
                body={"language": language, "video": video_url},
            ).execute()
            log(f"promo video ({language}): set to {video_url}")

    edits.commit(packageName=package_name, editId=edit_id).execute()
    log(f"committed edit {edit_id} — listing assets are live on {package_name}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--package-name",
        default=os.environ.get("PACKAGE_NAME", ""),
        help="Android applicationId (or env PACKAGE_NAME)",
    )
    parser.add_argument(
        "--service-account-json",
        default=os.environ.get("PLAY_STORE_SERVICE_ACCOUNT_JSON_FILE", ""),
        help="Path to the service account JSON key file "
        "(or env PLAY_STORE_SERVICE_ACCOUNT_JSON_FILE)",
    )
    parser.add_argument(
        "--app-dir",
        default=".",
        help="App checkout root holding marketing/ (default: current dir)",
    )
    parser.add_argument(
        "--language",
        default="en-US",
        help="BCP-47 listing language the image assets and promo video belong "
        "to (default: en-US); listing TEXT is per-locale from "
        "marketing/store/listing/<locale>/ regardless",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover, validate and print what would be uploaded, then exit "
        "without touching the API (no credentials needed)",
    )
    args = parser.parse_args()

    store_dir = os.path.join(args.app_dir, STORE_DIR)
    if os.path.isdir(store_dir):
        assets = discover_images(store_dir, read_curated_keys(args.app_dir))
    else:
        log(f"no store assets directory at {store_dir} — no listing images to push")
        assets = {}
    tablet_store_dir = os.path.join(args.app_dir, TABLET_STORE_DIR)
    if os.path.isdir(tablet_store_dir):
        tablet_screenshots = discover_tablet_screenshots(tablet_store_dir)
        if tablet_screenshots:
            assets["tenInchScreenshots"] = tablet_screenshots
    else:
        log(
            f"no tablet store directory at {tablet_store_dir} — "
            "no tenInchScreenshots to push"
        )
    video_url = discover_video(args.app_dir)
    listing_texts = discover_listing_texts(args.app_dir)

    if not assets and not video_url and not listing_texts:
        log("no valid listing assets found — nothing to upload; deploy continues")
        return

    for locale, fields in listing_texts.items():
        log(f"listing text ({locale}): {len(fields)} field(s) to push:")
        for api_field, _, limit, _ in LISTING_TEXT_FIELDS:
            if api_field in fields:
                log(
                    f"  {api_field}: {len(fields[api_field])}/{limit} chars — "
                    f"{fields[api_field][:60]!r}"
                )
    for image_type, paths in assets.items():
        log(f"{image_type} ({args.language}): {len(paths)} image(s) to upload:")
        for index, path in enumerate(paths, start=1):
            log(f"  {index}. {describe(path)}")
    if video_url:
        log(f"promo video ({args.language}): will point the listing at {video_url}")

    if args.dry_run:
        log("DRY RUN — stopping before any Play API call; nothing was uploaded")
        return

    if not args.package_name:
        fail("missing --package-name (or PACKAGE_NAME env)")
    if not args.service_account_json or not os.path.isfile(args.service_account_json):
        fail(
            "missing --service-account-json (or PLAY_STORE_SERVICE_ACCOUNT_JSON_FILE "
            f"env): {args.service_account_json!r} is not a file"
        )

    try:
        upload_assets(
            args.package_name,
            args.service_account_json,
            args.language,
            assets,
            video_url,
            listing_texts,
        )
    except Exception as e:  # loud, non-zero: auth failures, HttpError, IO
        fail(f"Play Edits API upload failed: {e}")


if __name__ == "__main__":
    main()
