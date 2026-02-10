from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import cv2
import numpy as np


@dataclass(frozen=True)
class RecognizedFace:
    label: int
    confidence: float
    bbox: Tuple[int, int, int, int]


def _to_gray_uint8(image_bgr: np.ndarray) -> np.ndarray:
    if image_bgr is None:
        raise ValueError("Empty image")
    if len(image_bgr.shape) == 2:
        return image_bgr
    return cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)


def _detect_faces(gray: np.ndarray) -> List[Tuple[int, int, int, int]]:
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml")
    faces = detector.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=6, minSize=(60, 60))
    return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]


def detect_faces_count(image_bgr: np.ndarray) -> int:
    gray = _to_gray_uint8(image_bgr)
    return int(len(_detect_faces(gray)))


def _crop_and_resize(gray: np.ndarray, bbox: Tuple[int, int, int, int], size: Tuple[int, int] = (200, 200)) -> np.ndarray:
    x, y, w, h = bbox
    roi = gray[y : y + h, x : x + w]
    roi = cv2.equalizeHist(roi)
    return cv2.resize(roi, size)


def train_lbph(training_images: List[np.ndarray], labels: List[int]) -> "cv2.face.LBPHFaceRecognizer":
    if len(training_images) == 0:
        raise ValueError("No training images")
    if len(training_images) != len(labels):
        raise ValueError("training_images and labels length mismatch")

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(training_images, np.array(labels, dtype=np.int32))
    return recognizer


def build_training_set(images_by_label: Dict[int, List[np.ndarray]]) -> Tuple[List[np.ndarray], List[int]]:
    train_images: List[np.ndarray] = []
    train_labels: List[int] = []

    for label, imgs in images_by_label.items():
        for img_bgr in imgs:
            gray = _to_gray_uint8(img_bgr)
            faces = _detect_faces(gray)
            if not faces:
                continue
            bbox = max(faces, key=lambda b: b[2] * b[3])
            train_images.append(_crop_and_resize(gray, bbox))
            train_labels.append(int(label))

    return train_images, train_labels


def recognize_faces_in_image(
    recognizer: "cv2.face.LBPHFaceRecognizer",
    image_bgr: np.ndarray,
) -> List[RecognizedFace]:
    gray = _to_gray_uint8(image_bgr)
    bboxes = _detect_faces(gray)
    results: List[RecognizedFace] = []

    for bbox in bboxes:
        roi = _crop_and_resize(gray, bbox)
        label, confidence = recognizer.predict(roi)
        results.append(RecognizedFace(label=int(label), confidence=float(confidence), bbox=bbox))

    return results


def detect_eyes_count(image_bgr: np.ndarray) -> int:
    gray = _to_gray_uint8(image_bgr)
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    eyes = detector.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=6, minSize=(18, 18))
    return int(len(eyes))
