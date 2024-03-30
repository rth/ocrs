#!/usr/bin/env python

from argparse import ArgumentParser
from pathlib import Path
from subprocess import run
import datasets
import time
import tempfile
from tqdm import tqdm

from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics import f1_score, precision_score, recall_score

try:
    import pytesseract
except ImportError:
    pytesseract = None


def build_ocrs() -> None:
    run("cargo build --release -p ocrs-cli", shell=True, check=True, text=True)


def extract_text(image_path: str) -> str:
    """Extract text from an image using ocrs."""
    result = run(
        # We run the binary directly here rather than use `cargo run` as it
        # is slightly faster.
        [f"target/release/ocrs", image_path],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout


def run_global_retrieval_eval(max_samples: int) -> bool:
    """
    Evaluate OCR performance, by computing precision, recall and F1 score
    for the detected tokens globally on the whole document

    Here we use scikit-learn's tokenizer to split the text into tokens
    """

    # Evaluate the SROIE dataset
    dataset = datasets.load_dataset("rth/sroie-2019-v2", split="test")
    true_text = ["\n".join(el["objects"]["text"]) for el in dataset]
    print("Evaluating on SROIE 2019 dataset...")

    # Build the vocabulary on the ground truth
    vectorizer = CountVectorizer(input="content", binary=True)

    X_true = vectorizer.fit_transform(true_text[:max_samples])

    # Evaluate with orcs
    text_pred_orcs = []
    time_orcs = 0

    # Use a tempfs if available (Linux, MacOS) to reduce disk I/O overhead
    TMP_DIR = Path("/dev/shm")
    if not TMP_DIR.exists():
        TMP_DIR = None

    for idx, data_el in tqdm(enumerate(dataset)):
        if idx >= max_samples:
            break

        with tempfile.NamedTemporaryFile(
            dir=TMP_DIR, suffix=".jpg", delete=False
        ) as tmp_file:
            data_el["image"].save(tmp_file, format="JPEG")

            t0 = time.perf_counter()
            text_pred_orcs.append(extract_text(tmp_file.name))
            time_orcs += time.perf_counter() - t0

    X_orcs = vectorizer.transform(text_pred_orcs)

    print(
        " - ORCS: {:.2f} s / image, precision {:.2f}, recall {:.2f}, F1 {:.2f}".format(
            time_orcs / max_samples,
            precision_score(X_true, X_orcs, average="micro"),
            recall_score(X_true, X_orcs, average="micro"),
            f1_score(X_true, X_orcs, average="micro"),
        )
    )
    if pytesseract is not None:
        # Optionally evaluate with pytesseract
        text_pred_tesseract = []
        time_tesseract = 0
        for idx, data_el in tqdm(enumerate(dataset)):
            if idx >= max_samples:
                break

            t0 = time.perf_counter()
            # Neural nets LSTM engine only.
            text_pred_tesseract.append(
                pytesseract.image_to_string(tmp_file.name, lang="eng", config="--oem 1")
            )
            time_tesseract += time.perf_counter() - t0

        X_tesseract = vectorizer.transform(text_pred_tesseract)

        print(
            " - Tesseract: {:.2f} s / image, precision {:.2f}, recall {:.2f}, F1 {:.2f}".format(
                time_tesseract / max_samples,
                precision_score(X_true, X_tesseract, average="micro"),
                recall_score(X_true, X_tesseract, average="micro"),
                f1_score(X_true, X_tesseract, average="micro"),
            )
        )


parser = ArgumentParser(
    description="""
Evaluate orcs on the benchmark datasets

To run this script, you need, to install dependencies:
    pip install scikit-learn datasets tqdm

Optionally, you can install pytesseract to compare with tesseract.
"""
)
parser.add_argument(
    "--max-samples", type=int, default=100, help="Number of samples to evaluate"
)
args = parser.parse_args()

print("Building ocrs...")
build_ocrs()
run_global_retrieval_eval(max_samples=args.max_samples)