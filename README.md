# club-ai-agent

## IRTM PA2 – tf-idf vectors

- `pa2.py` – builds `output/dictionary.txt` and `output/<DocID>.txt` from `data/*.txt`, prints `cosine(Doc1, Doc2)`
- `report.md` – report draft (fill in the placeholders, add screenshots, export to `report.pdf`)
- `make_submission.py` – `python make_submission.py <學號>` packs `<學號>.zip` in the required layout

```bash
pip install nltk
# put the 1095 documents in ./data first
python pa2.py
python pa2.py --cosine 1 2
python make_submission.py D14725002
```
