"""IRTM Programming Assignment 2: convert documents into tf-idf unit vectors.

Usage:
    python pa2.py                 # build output/dictionary.txt and output/<DocID>.txt
    python pa2.py --cosine 1 2    # only compute cosine similarity of two built vectors

Requires: pip install nltk   (only nltk.stem.PorterStemmer is used, as in PA1)

Pipeline (tokenization continued from PA1):
    lowercase -> remove contractions ('s, n't, 're, 'm ...) -> keep letters only
    -> split on whitespace -> remove stopwords -> Porter stemming
    -> remove stopwords / 1-char tokens again

tf-idf is computed by hand (no sklearn etc.):
    tf(t, d)    = raw count of term t in document d
    df(t)       = number of documents containing t
    idf(t)      = log10(N / df(t))
    w(t, d)     = tf(t, d) * idf(t), then each document vector is L2-normalized
"""

import argparse
import glob
import math
import os
import re

from nltk.stem import PorterStemmer

DATA_DIR = "./data"
OUTPUT_DIR = "./output"
DICTIONARY_FILE = os.path.join(OUTPUT_DIR, "dictionary.txt")


# --------------------------------------------------------------------------
# Tokenization (continued from PA1)
# --------------------------------------------------------------------------
# PA1 stopword list, extended with words that were still left over in the PA1
# result (also, will, just, now, can, may, ...) and contraction remnants.
STOPWORDS = {
    'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and',
    'any', 'are', 'as', 'at', 'be', 'because', 'been', 'before', 'being',
    'below', 'between', 'both', 'but', 'by', 'cannot', 'could',
    'did', 'do', 'does', 'doing', 'down', 'during',
    'each', 'few', 'for', 'from', 'further', 'had', 'has',
    'have', 'having', 'he', 'her', 'here',
    'hers', 'herself', 'him', 'himself', 'his', 'how', 'i',
    'if', 'in', 'into', 'is', 'it',
    'its', 'itself', 'me', 'more', 'most', 'my',
    'myself', 'no', 'nor', 'not', 'of', 'off', 'on', 'once', 'only', 'or', 'other',
    'ought', 'our', 'ours', 'ourselves', 'out', 'over', 'own', 'same',
    'she', 'should', 'so', 'some',
    'such', 'than', 'that', 'the', 'their', 'theirs', 'them', 'themselves',
    'then', 'there', 'these', 'they',
    'this', 'those', 'through', 'to', 'too', 'under', 'until', 'up',
    'very', 'was', 'we', 'were',
    'what', 'when', 'where', 'which',
    'while', 'who', 'whom', 'why', 'with', 'would',
    'you', 'your', 'yours', 'yourself', 'yourselves',
    # added for PA2
    'also', 'although', 'among', 'another', 'anyone', 'anything', 'around',
    'away', 'can', 'either', 'else', 'even', 'ever', 'every',
    'get', 'gets', 'got', 'however', 'just', 'least', 'less', 'like', 'many',
    'may', 'might', 'much', 'must', 'neither', 'never', 'now', 'often',
    'one', 'onto', 'per', 'perhaps', 'quite', 'rather', 'really', 'said',
    'say', 'says', 'several', 'shall', 'since', 'still', 'though', 'thus',
    'toward', 'towards', 'upon', 'us', 'via', 'well', 'whether', 'will',
    'within', 'without', 'yet', 'mr', 'mrs', 'ms',
}

stemmer = PorterStemmer()


def tokenize(text):
    # Step 1: Lowercasing
    text = text.lower()
    # Step 2: remove contractions / possessives so they don't leave s, t, re, m ...
    text = re.sub(r"[\u2019']s\b", " ", text)                     # serbia's -> serbia
    text = re.sub(r"n[\u2019']t\b", " not", text)                 # don't -> do not
    text = re.sub(r"[\u2019'](re|m|ve|ll|d)\b", " ", text)        # we're / i'm -> we / i
    # Step 3: Tokenization -- keep letters only (numbers such as 292, 10,000 are dropped)
    raw_tokens = re.sub(r"[^a-z\s]", " ", text).split()
    # Step 4: Stopword removal & Stemming, then drop 1-char tokens and stopwords again
    tokens = []
    for token in raw_tokens:
        if token in STOPWORDS:
            continue
        token = stemmer.stem(token)
        if len(token) <= 1 or token in STOPWORDS:
            continue
        tokens.append(token)
    return tokens


# --------------------------------------------------------------------------
# tf / df / idf (hand-written)
# --------------------------------------------------------------------------
def doc_id_of(path):
    name = os.path.splitext(os.path.basename(path))[0]
    return int(name) if name.isdigit() else name


def load_documents(data_dir=DATA_DIR):
    paths = glob.glob(os.path.join(data_dir, "*.txt"))
    paths.sort(key=lambda p: (not isinstance(doc_id_of(p), int), str(doc_id_of(p)).zfill(10)))
    docs = {}
    for path in paths:
        with open(path, encoding="utf-8", errors="ignore") as f:
            docs[doc_id_of(path)] = f.read()
    return docs


def term_frequency(tokens):
    tf = {}
    for tok in tokens:
        tf[tok] = tf.get(tok, 0) + 1
    return tf


def document_frequency(tf_per_doc):
    df = {}
    for tf in tf_per_doc.values():
        for term in tf:
            df[term] = df.get(term, 0) + 1
    return df


def build_dictionary(df):
    """Terms in ascending order -> (t_index starting from 1, df)."""
    return {term: (i, df[term]) for i, term in enumerate(sorted(df), start=1)}


def write_dictionary(dictionary, path=DICTIONARY_FILE):
    with open(path, "w", encoding="utf-8") as f:
        f.write("t_index\tterm\tdf\n")
        for term, (t_index, df) in dictionary.items():
            f.write(f"{t_index}\t{term}\t{df}\n")


def tfidf_unit_vector(tf, dictionary, n_docs):
    """Return [(t_index, weight)] sorted by t_index, with unit L2 length."""
    vec = []
    for term, count in tf.items():
        t_index, df = dictionary[term]
        vec.append((t_index, count * math.log10(n_docs / df)))
    norm = math.sqrt(sum(w * w for _, w in vec))
    if norm > 0:
        vec = [(i, w / norm) for i, w in vec]
    vec.sort()
    return vec


def write_vector(vec, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{len(vec)}\n")
        f.write("t_index\ttf-idf\n")
        for t_index, w in vec:
            f.write(f"{t_index}\t{w:.6f}\n")


# --------------------------------------------------------------------------
# Cosine similarity
# --------------------------------------------------------------------------
def load_vector(doc_id, output_dir=OUTPUT_DIR):
    vec = {}
    with open(os.path.join(output_dir, f"{doc_id}.txt"), encoding="utf-8") as f:
        f.readline()  # number of terms
        f.readline()  # header
        for line in f:
            parts = line.split()
            if len(parts) == 2:
                vec[int(parts[0])] = float(parts[1])
    return vec


def cosine(Docx, Docy):
    """Load the tf-idf vectors of documents x and y and return their cosine similarity."""
    x, y = load_vector(Docx), load_vector(Docy)
    if len(x) > len(y):
        x, y = y, x
    dot = sum(w * y[i] for i, w in x.items() if i in y)
    norm_x = math.sqrt(sum(w * w for w in x.values()))
    norm_y = math.sqrt(sum(w * w for w in y.values()))
    if norm_x == 0 or norm_y == 0:
        return 0.0
    return dot / (norm_x * norm_y)


# --------------------------------------------------------------------------
def build_all():
    docs = load_documents()
    if not docs:
        raise SystemExit(f"No documents found in {DATA_DIR}/*.txt")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    tf_per_doc = {doc_id: term_frequency(tokenize(text)) for doc_id, text in docs.items()}
    df = document_frequency(tf_per_doc)
    dictionary = build_dictionary(df)
    write_dictionary(dictionary)

    n_docs = len(docs)
    for doc_id, tf in tf_per_doc.items():
        vec = tfidf_unit_vector(tf, dictionary, n_docs)
        write_vector(vec, os.path.join(OUTPUT_DIR, f"{doc_id}.txt"))

    print(f"Documents: {n_docs}")
    print(f"Dictionary size: {len(dictionary)} terms -> {DICTIONARY_FILE}")
    print(f"Vectors written to {OUTPUT_DIR}/<DocID>.txt")


def main():
    parser = argparse.ArgumentParser(description="IRTM PA2: tf-idf vectors")
    parser.add_argument("--cosine", nargs=2, metavar=("DOCX", "DOCY"),
                        help="only compute cosine similarity of two existing vectors")
    args = parser.parse_args()

    if args.cosine:
        x, y = args.cosine
    else:
        build_all()
        x, y = 1, 2
    print(f"cosine(Doc{x}, Doc{y}) = {cosine(x, y):.6f}")


if __name__ == "__main__":
    main()
