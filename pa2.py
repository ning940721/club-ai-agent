"""IRTM Programming Assignment 2: convert documents into tf-idf unit vectors.

Usage:
    python pa2.py                 # build output/dictionary.txt and output/<DocID>.txt
    python pa2.py --cosine 1 2    # only compute cosine similarity of two built vectors

Pipeline (tokenization reused from PA1):
    lowercase -> strip possessive / punctuation / digits -> split on whitespace
    -> remove stopwords -> Porter stemming -> remove stopwords / 1-char tokens again

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

DATA_DIR = "./data"
OUTPUT_DIR = "./output"
DICTIONARY_FILE = os.path.join(OUTPUT_DIR, "dictionary.txt")


# --------------------------------------------------------------------------
# Stopwords (English, based on the NLTK / SMART lists)
# --------------------------------------------------------------------------
STOPWORDS = set("""
a about above across after afterwards again against ago all almost alone along
already also although always am among amongst an and another any anybody anyhow
anyone anything anyway anywhere are aren around as aside at away back be became
because become becomes becoming been before beforehand behind being below beside
besides between beyond both but by can cannot cant could couldn did didn do does
doesn doing don done down due during each eg eight either eleven else elsewhere
enough etc even ever every everyone everything everywhere except few fifteen fifty
first five for former formerly forty four from further get gets getting give given
gives go goes going gone got had hadn has hasn have haven having he hence her here
hereafter hereby herein hereupon hers herself him himself his how however hundred
i ie if in inc indeed into is isn it its itself just keep last latter latterly
least less let like ll made make makes many may maybe me meanwhile might mine more
moreover most mostly mr mrs ms much must mustn my myself namely neither never
nevertheless next nine no nobody none noone nor not nothing now nowhere of off
often on once one only onto or other others otherwise our ours ourselves out over
own per perhaps please put quite rather re really s said same say says second see
seem seemed seeming seems seven several shall shan she should shouldn since six
sixty so some somehow someone something sometime sometimes somewhere still such t
take taken ten than that the their theirs them themselves then thence there
thereafter thereby therefore therein thereupon these they third thirty this those
though three through throughout thru thus to together too toward towards twelve
twenty two under until up upon us use used using ve very via was wasn we well were
weren what whatever when whence whenever where whereafter whereas whereby wherein
whereupon wherever whether which while whither who whoever whole whom whose why
will with within without won would wouldn yet you your yours yourself yourselves
""".split())


# --------------------------------------------------------------------------
# Porter stemmer (M.F. Porter, 1980), self-contained so no pip install needed
# --------------------------------------------------------------------------
class PorterStemmer:
    def _cons(self, w, i):
        ch = w[i]
        if ch in "aeiou":
            return False
        if ch == "y":
            return i == 0 or not self._cons(w, i - 1)
        return True

    def _m(self, stem):
        """Measure of a stem: number of VC sequences."""
        n, i, length = 0, 0, len(stem)
        while i < length and self._cons(stem, i):
            i += 1
        while i < length:
            while i < length and not self._cons(stem, i):
                i += 1
            if i >= length:
                break
            n += 1
            while i < length and self._cons(stem, i):
                i += 1
        return n

    def _has_vowel(self, stem):
        return any(not self._cons(stem, i) for i in range(len(stem)))

    def _double_cons(self, w):
        return len(w) >= 2 and w[-1] == w[-2] and self._cons(w, len(w) - 1)

    def _cvc(self, w):
        """consonant-vowel-consonant ending, last consonant not w, x or y."""
        if len(w) < 3:
            return False
        if not self._cons(w, len(w) - 1) or self._cons(w, len(w) - 2) or not self._cons(w, len(w) - 3):
            return False
        return w[-1] not in "wxy"

    def _replace(self, w, rules, min_m):
        """Apply the first matching suffix rule whose stem has measure > min_m."""
        for suffix, repl in rules:
            if w.endswith(suffix):
                stem = w[: len(w) - len(suffix)]
                if self._m(stem) > min_m:
                    return stem + repl
                return w
        return w

    def _step1a(self, w):
        if w.endswith("sses"):
            return w[:-2]
        if w.endswith("ies"):
            return w[:-2]
        if w.endswith("ss"):
            return w
        if w.endswith("s"):
            return w[:-1]
        return w

    def _step1b(self, w):
        if w.endswith("eed"):
            return w[:-1] if self._m(w[:-3]) > 0 else w
        for suffix in ("ed", "ing"):
            if w.endswith(suffix):
                stem = w[: -len(suffix)]
                if not self._has_vowel(stem):
                    return w
                w = stem
                if w.endswith(("at", "bl", "iz")):
                    return w + "e"
                if self._double_cons(w) and w[-1] not in "lsz":
                    return w[:-1]
                if self._m(w) == 1 and self._cvc(w):
                    return w + "e"
                return w
        return w

    def _step1c(self, w):
        if w.endswith("y") and self._has_vowel(w[:-1]):
            return w[:-1] + "i"
        return w

    _STEP2 = [
        ("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"),
        ("izer", "ize"), ("abli", "able"), ("alli", "al"), ("entli", "ent"),
        ("eli", "e"), ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"),
        ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"),
        ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"),
    ]
    _STEP3 = [
        ("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"),
        ("ical", "ic"), ("ful", ""), ("ness", ""),
    ]
    _STEP4 = [
        "al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment",
        "ent", "ion", "ou", "ism", "ate", "iti", "ous", "ive", "ize",
    ]

    def _step2(self, w):
        # Rules are matched by longest suffix, as in the original algorithm
        rules = sorted(self._STEP2, key=lambda r: -len(r[0]))
        return self._replace(w, rules, 0)

    def _step3(self, w):
        rules = sorted(self._STEP3, key=lambda r: -len(r[0]))
        return self._replace(w, rules, 0)

    def _step4(self, w):
        for suffix in sorted(self._STEP4, key=len, reverse=True):
            if w.endswith(suffix):
                stem = w[: -len(suffix)]
                if self._m(stem) > 1:
                    if suffix == "ion" and not (stem and stem[-1] in "st"):
                        return w
                    return stem
                return w
        return w

    def _step5(self, w):
        if w.endswith("e"):
            stem = w[:-1]
            m = self._m(stem)
            if m > 1 or (m == 1 and not self._cvc(stem)):
                w = stem
        if self._m(w) > 1 and self._double_cons(w) and w[-1] == "l":
            w = w[:-1]
        return w

    def stem(self, word):
        if len(word) <= 2:
            return word
        for step in (self._step1a, self._step1b, self._step1c,
                     self._step2, self._step3, self._step4, self._step5):
            word = step(word)
        return word


# --------------------------------------------------------------------------
# Tokenization (PA1)
# --------------------------------------------------------------------------
_stemmer = PorterStemmer()


def tokenize(text):
    text = text.lower()
    text = re.sub(r"'s\b", " ", text)          # possessive: reagan's -> reagan
    text = text.replace("'", "")                # don't -> dont
    text = re.sub(r"[^a-z]+", " ", text)        # drop punctuation and digits
    tokens = []
    for tok in text.split():
        if tok in STOPWORDS:
            continue
        tok = _stemmer.stem(tok)
        if len(tok) <= 1 or tok in STOPWORDS:
            continue
        tokens.append(tok)
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
