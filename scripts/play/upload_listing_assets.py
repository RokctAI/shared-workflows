#!/usr/bin/env python3
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
        - portrait (taller than wide), every side within Play's
          320-3840px screenshot bounds -> phoneScreenshots, uploaded in
          sorted filename order, capped at Play's limit of 8 with every
          skipped file named in the log (no silent caps)
      Anything else (wrong shape, out of bounds, over Play's 15MB image
      limit, unreadable) is logged and skipped — one bad file never
      fails the deploy.

  marketing/store/video.txt
      Single line holding a YouTube URL for the listing's promo-video
      slot. Play does NOT accept video file uploads through the API —
      the reel itself must be published to YouTube once, by a human;
      this script only points the listing at it, patching ONLY the
      `video` field of the existing listing (titles/descriptions are
      fetched first and left untouched).

Edits flow: edits.insert -> per image type with local candidates:
images.deleteall then upload in sorted order -> listings.patch (video
only, when video.txt exists) -> edits.commit.

Exits 0 with a clear log when the checkout ships no store assets (apps
without marketing assets deploy unchanged). Exits non-zero, loudly, on
API/auth errors. --dry-run prints exactly what would be uploaded and
needs neither credentials nor the Google API packages installed.
"""

import argparse
import os
import sys

STORE_DIR = os.path.join("marketing", "tour", "store")
VIDEO_FILE = os.path.join("marketing", "store", "video.txt")
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
PHONE_MIN_PX, PHONE_MAX_PX = 320, 3840  # screenshots: every side in bounds
PHONE_MAX_COUNT = 8                 # at most 8 screenshots per type
OAUTH_SCOPE = "https://www.googleapis.com/auth/androidpublisher"


def log(message):
    print(f"[listing-assets] {message}", flush=True)


def fail(message):
    print(f"::error::[listing-assets] {message}", file=sys.stderr, flush=True)
    sys.exit(1)


def image_size(path):
    """(width, height) of the image, or None (logged) when unreadable."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except OSError as e:
        log(f"skipping {path}: unreadable as an image ({e})")
        return None


def discover_images(store_dir):
    """Classify the store dir's images: {imageType: [paths in upload order]}.

    Classification is by dimensions only (the feature graphic is excluded
    from the screenshots by its shape, not its name). Invalid files are
    logged and skipped, never fatal. The phoneScreenshots list is capped
    at Play's limit of {PHONE_MAX_COUNT} with every skipped file named.
    """
    feature_graphics = []
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
        elif height > width and all(
            PHONE_MIN_PX <= side <= PHONE_MAX_PX for side in (width, height)
        ):
            screenshots.append(path)
        else:
            log(
                f"skipping {path}: {width}x{height} is neither a portrait "
                f"phone screenshot ({PHONE_MIN_PX}-{PHONE_MAX_PX}px per side) "
                f"nor a {FEATURE_W}x{FEATURE_H} feature graphic"
            )

    assets = {}
    if feature_graphics:
        assets["featureGraphic"] = feature_graphics[:1]
        for extra in feature_graphics[1:]:
            log(
                f"skipping {extra}: already using "
                f"{feature_graphics[0]} as the feature graphic"
            )
    if screenshots:
        assets["phoneScreenshots"] = screenshots[:PHONE_MAX_COUNT]
        for over_cap in screenshots[PHONE_MAX_COUNT:]:
            log(
                f"skipping {over_cap}: over Play's {PHONE_MAX_COUNT}-image "
                "phoneScreenshots cap (first "
                f"{PHONE_MAX_COUNT} in filename order win)"
            )
    return assets


def discover_video(app_dir):
    """The promo video's YouTube URL from marketing/store/video.txt, or None."""
    video_path = os.path.join(app_dir, VIDEO_FILE)
    if not os.path.isfile(video_path):
        return None
    try:
        with open(video_path, encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip()]
    except OSError as e:
        log(f"skipping promo video: could not read {video_path} ({e})")
        return None
    if not lines:
        log(f"skipping promo video: {video_path} is empty")
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


def upload_assets(package_name, service_account_json, language, assets, video_url):
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
        try:
            listing = (
                edits.listings()
                .get(packageName=package_name, editId=edit_id, language=language)
                .execute()
            )
        except HttpError as e:
            if e.resp.status == 404:
                log(
                    f"no {language} listing exists in Play Console yet — "
                    "create it (title/description) once by hand before the "
                    "promo-video URL can be set; skipping the video patch"
                )
                listing = None
            else:
                raise
        if listing is not None:
            if listing.get("video") == video_url:
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
        help="BCP-47 listing language the assets belong to (default: en-US)",
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
        assets = discover_images(store_dir)
    else:
        log(f"no store assets directory at {store_dir} — no listing images to push")
        assets = {}
    video_url = discover_video(args.app_dir)

    if not assets and not video_url:
        log("no valid listing assets found — nothing to upload; deploy continues")
        return

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
        )
    except Exception as e:  # loud, non-zero: auth failures, HttpError, IO
        fail(f"Play Edits API upload failed: {e}")


if __name__ == "__main__":
    main()
