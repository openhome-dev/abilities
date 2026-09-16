"""Stages 1 and 2: YAMNet, then the purpose-trained verifier head.

Stage 1 runs Google's YAMNet (AudioSet, 521 classes) on the gated segment and
reads the Fart score plus the 1024-dim embedding. Stage 2 is a logistic
regression on the mean-pooled embedding, trained by training/train_head.py and
exported as models/head.npz. Until a head exists, Stage 2 returns a neutral
0.5 so the pipeline still runs on YAMNet alone.
"""
from __future__ import annotations

import math

import numpy as np

MIN_SAMPLES = 15600          # one YAMNet patch (0.975 s at 16 kHz)
STAGE1_MIN_SCORE = 0.05
STAGE1_TOP_K = 5
FART = "Fart"
NEAR_MISS_CLASSES = {"Burping, eructation", "Hiccup", "Whoop", "Breathing", "Cough", "Squeak"}


def parse_class_map(text: str) -> list[str]:
    """yamnet_class_map.csv contents -> display names. Column 3, quoted names allowed."""
    names = []
    for line in text.splitlines()[1:]:
        if not line.strip():
            continue
        parts = line.split(",", 2)
        names.append(parts[2].strip().strip('"'))
    return names


class YamNet:
    def __init__(self, model_path: str, classes: list[str]):
        from ai_edge_litert.interpreter import Interpreter  # lazy: heavy import
        self.it = Interpreter(model_path=model_path, num_threads=2)
        self.inp = self.it.get_input_details()[0]["index"]
        outs = {d["shape"][-1]: d["index"] for d in self.it.get_output_details()}
        self.scores_idx = outs[521]
        self.embed_idx = outs[1024]
        self.classes = classes
        self.fart_idx = self.classes.index(FART)
        self._allocated_len = -1

    def run(self, audio: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Returns (scores[frames,521], embeddings[frames,1024])."""
        wav = np.asarray(audio, dtype=np.float32).reshape(-1)
        if wav.size < MIN_SAMPLES:
            wav = np.pad(wav, (0, MIN_SAMPLES - wav.size))
        if wav.size != self._allocated_len:
            self.it.resize_tensor_input(self.inp, [wav.size])
            self.it.allocate_tensors()
            self._allocated_len = wav.size
        self.it.set_tensor(self.inp, wav)
        self.it.invoke()
        return self.it.get_tensor(self.scores_idx).copy(), self.it.get_tensor(self.embed_idx).copy()

    def summarize(self, scores: np.ndarray) -> dict:
        """Max-over-frames Fart score, whether it made top-k, and the top classes."""
        fart = float(scores[:, self.fart_idx].max())
        top_any = False
        for row in scores:
            if self.fart_idx in np.argsort(row)[::-1][:STAGE1_TOP_K]:
                top_any = True
                break
        mean = scores.mean(axis=0)
        top = [(self.classes[i], round(float(mean[i]), 3)) for i in np.argsort(mean)[::-1][:5]]
        return {"yamnet_fart": round(fart, 3), "fart_in_topk": top_any, "top": top}


class VerifierHead:
    """Logistic regression on a mean-pooled YAMNet embedding.
    `weights` is the dict loaded from head.npz (w, b, mu, sd) or None."""

    def __init__(self, weights: dict | None = None):
        self.loaded = False
        self.w = None
        self.b = 0.0
        self.mu = None
        self.sd = None
        if weights is not None:
            self.w, self.b = np.asarray(weights["w"], dtype=np.float64), float(weights["b"])
            self.mu, self.sd = np.asarray(weights["mu"], dtype=np.float64), np.asarray(weights["sd"], dtype=np.float64)
            self.loaded = True

    def prob(self, embeddings: np.ndarray) -> float:
        if not self.loaded:
            return 0.5
        x = embeddings.mean(axis=0).astype(np.float64)
        x = (x - self.mu) / (self.sd + 1e-8)
        z = float(x @ self.w + self.b)
        return 1.0 / (1.0 + math.exp(-z))


class Detector:
    """Stage 1 + Stage 2. `decide` returns a dict with the scores and verdict."""

    def __init__(self, model_path: str, classes: list[str], head_weights: dict | None = None,
                 threshold: float = 0.4):
        self.yamnet = YamNet(model_path, classes)
        self.head = VerifierHead(head_weights)
        self.threshold = threshold

    def decide(self, audio: np.ndarray) -> dict:
        scores, emb = self.yamnet.run(audio)
        s1 = self.yamnet.summarize(scores)
        passed_s1 = s1["yamnet_fart"] >= STAGE1_MIN_SCORE or s1["fart_in_topk"]
        p2 = self.head.prob(emb) if passed_s1 else 0.0
        if not passed_s1:
            score = 0.0
        elif self.head.loaded:
            score = s1["yamnet_fart"] * p2
        else:
            score = s1["yamnet_fart"]   # YAMNet alone until a head is trained
        top_names = {n for n, _ in s1["top"]}
        near_miss = (not passed_s1 or score < self.threshold) and (
            passed_s1 or bool(top_names & NEAR_MISS_CLASSES))
        return {
            "yamnet_fart": s1["yamnet_fart"],
            "top": s1["top"],
            "verifier_p": round(p2, 3),
            "score": round(score, 3),
            "detected": score >= self.threshold,
            "near_miss": near_miss and score < self.threshold,
            "head_loaded": self.head.loaded,
        }
