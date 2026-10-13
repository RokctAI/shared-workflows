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

"""People job: find faces in photos and match them to the user's people.

Models (both from opencv_zoo, licences safe for a paid app; InsightFace's
pretrained models are research-only and are deliberately NOT used):
  - YuNet face detector, face_detection_yunet_2023mar.onnx (MIT)
  - SFace face recogniser, face_recognition_sface_2021dec.onnx (Apache-2.0),
    128-d embeddings compared by cosine similarity.
The phone must use the SAME SFace model for faces it finds itself, or the
embeddings are not comparable. Both files are pinned by SHA-256 below.

Files (depot/CONTRACT.md):
  depot/people/registry.json          the user's people, written by the app:
      {"version": 1, "model": "sface_2021dec", "threshold": 0.363,
       "people": {"<person_id>": {"name": "...", "embeddings": ["<b64>", ...]}}}
  depot/people/faces/<aa>/<sha256>.json   per photo, written here:
      {"model": ..., "faces": [{"box": [x, y, w, h], "score": s,
                                "embedding": "<b64>", "person_id": id|null,
                                "similarity": s|null}]}
Index tags written: `faces_scanned` true, `face_count`, `people` [ids].
A face below the threshold gets person_id null: the app asks the user who
it is and adds the answer to the registry, which the next run uses.
"""

import base64
import hashlib
import json
import os
import urllib.request

from . import enrich, gitops, layout

JOB = "people"
MODEL_NAME = "sface_2021dec"
DEFAULT_THRESHOLD = 0.363  # SFace's published cosine match threshold
MIN_FACE_SCORE = 0.9
MAX_SIDE = 1600

_ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/47534e27c9851bb1128ccc0102f1145e27f23f98"
MODELS = {
    "detector": (
        f"{_ZOO}/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "recognizer": (
        f"{_ZOO}/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
}
REGISTRY_PATH = f"{layout.PEOPLE_DIR}/registry.json"


# --- embeddings and matching (numpy only; testable without the models) ----


def encode_embedding(vec):
    import numpy as np

    return base64.b64encode(np.asarray(vec, dtype="<f4").tobytes()).decode("ascii")


def decode_embedding(text):
    import numpy as np

    return np.frombuffer(base64.b64decode(text), dtype="<f4")


def normalise(vec):
    import numpy as np

    v = np.asarray(vec, dtype="float32").reshape(-1)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


class Registry:
    """The user's confirmed people. Read-only here: only the app names faces."""

    def __init__(self, doc=None):
        doc = doc or {}
        self.threshold = float(doc.get("threshold", DEFAULT_THRESHOLD))
        self.people = {}
        for pid, person in (doc.get("people") or {}).items():
            embs = [
                normalise(decode_embedding(e)) for e in person.get("embeddings", [])
            ]
            if embs:
                self.people[pid] = embs

    @classmethod
    def load(cls, root):
        path = os.path.join(root, REGISTRY_PATH)
        if not os.path.exists(path):
            return cls()
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def match(self, embedding):
        """(person_id, similarity) of the closest person at or above the
        threshold, else (None, best similarity or None)."""
        import numpy as np

        q = normalise(embedding)
        best_id, best = None, None
        for pid, embs in self.people.items():
            sim = max(float(np.dot(q, e)) for e in embs)
            if best is None or sim > best:
                best_id, best = pid, sim
        if best is not None and best >= self.threshold:
            return best_id, round(best, 4)
        return None, (round(best, 4) if best is not None else None)


# --- models ----------------------------------------------------------------


def fetch_models(cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    paths = {}
    for role, (url, sha) in MODELS.items():
        path = os.path.join(cache_dir, os.path.basename(url))
        if not (os.path.exists(path) and _sha_file(path) == sha):
            urllib.request.urlretrieve(url, path)
            got = _sha_file(path)
            if got != sha:
                os.remove(path)
                raise RuntimeError(f"{role} model checksum mismatch: {got}")
        paths[role] = path
    return paths


def _sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class FaceEngine:
    def __init__(self, model_paths):
        import cv2  # ty: ignore[unresolved-import]  # installed by the workflow

        self._cv2 = cv2
        self._detector = cv2.FaceDetectorYN.create(
            model_paths["detector"], "", (320, 320), MIN_FACE_SCORE, 0.3, 5000
        )
        self._recognizer = cv2.FaceRecognizerSF.create(model_paths["recognizer"], "")

    def faces(self, data):
        """[(box, score, embedding)] for every face in the image bytes."""
        cv2 = self._cv2
        import numpy as np

        img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return []
        h, w = img.shape[:2]
        scale = min(1.0, MAX_SIDE / max(h, w))
        if scale < 1.0:
            img = cv2.resize(img, (int(w * scale), int(h * scale)))
            h, w = img.shape[:2]
        self._detector.setInputSize((w, h))
        _, found = self._detector.detect(img)
        out = []
        for face in found if found is not None else []:
            aligned = self._recognizer.alignCrop(img, face)
            feat = normalise(self._recognizer.feature(aligned))
            box = [int(round(v / scale)) for v in face[:4]]
            out.append((box, round(float(face[-1]), 4), feat))
        return out


# --- the job -----------------------------------------------------------------


def wants(entry):
    return enrich.has_image(entry) and not entry.get("tags", {}).get("faces_scanned")


def describe(found, registry):
    faces, people = [], []
    for box, score, emb in found:
        pid, sim = registry.match(emb)
        faces.append(
            {
                "box": box,
                "score": score,
                "embedding": encode_embedding(emb),
                "person_id": pid,
                "similarity": sim,
            }
        )
        if pid and pid not in people:
            people.append(pid)
    return faces, sorted(people)


def run(root, *, engine=None, cache_dir=None, **kw):
    engine = engine or FaceEngine(
        fetch_models(cache_dir or os.path.expanduser("~/.cache/depot-models"))
    )
    registry = Registry.load(root)

    def analyse(entry, version):
        return engine.faces(gitops.read_blob(root, version["path"]))

    def apply_result(idx, day, entry, found):
        sha = layout.current_version(entry)["sha256"]
        faces, people = describe(found, registry)
        rel = layout.faces_path(sha)
        gitops.write_file(
            root, rel, layout.encode_json({"model": MODEL_NAME, "faces": faces})
        )
        tags = dict(entry.get("tags") or {})
        tags.update(faces_scanned=True, face_count=len(faces), people=people)
        entry["tags"] = tags
        idx.put(day, entry)
        return [rel]

    return enrich.run(
        root,
        job=JOB,
        kind="people",
        wants=wants,
        analyse=analyse,
        apply_result=apply_result,
        message=lambda n: f"Look for people in {n} photo{'s' if n != 1 else ''}",
        **kw,
    )
