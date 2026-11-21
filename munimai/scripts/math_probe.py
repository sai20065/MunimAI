"""
Quick, honest probe: can each model do small business-finance arithmetic with the reasoning shown?
Ten problems with exact answers computed in Python; 1% tolerance. Not a benchmark, a sanity check that
decides which model the Math agent should ask for formula ideas. Models never do the real arithmetic
in the product; this only measures their reasoning.
"""
import json, re, sys, time
from concurrent.futures import ThreadPoolExecutor
import requests

sys.stdout.reconfigure(encoding="utf-8")
P = [
 ("Fixed costs are Rs 60000 a month. Each unit sells for Rs 250 and costs Rs 150 to make. How many units must be sold to break even?", 60000 / (250 - 150)),
 ("Sales Rs 480000, purchases Rs 312000. What is the gross margin as a percentage of sales?", (480000 - 312000) / 480000 * 100),
 ("Cash in hand is Rs 90000 and monthly expenses are Rs 135000. How many days of expenses does the cash cover (30-day month)?", 90000 / 135000 * 30),
 ("Sales grew from Rs 200000 to Rs 288000 over 2 years. What is the compound annual growth rate in percent?", ((288000 / 200000) ** 0.5 - 1) * 100),
 ("Output GST is Rs 54000 and input tax credit is Rs 38250. What is the net GST payable in rupees?", 54000 - 38250),
 ("Days inventory 40, days sales outstanding 25, days payable 30. What is the cash conversion cycle in days?", 40 + 25 - 30),
 ("A loan of Rs 100000 at 12% per year for 12 months. What is the monthly EMI in rupees (standard reducing-balance formula)?", 100000 * 0.01 * 1.01 ** 12 / (1.01 ** 12 - 1)),
 ("Monthly sales rose from Rs 120000 to Rs 138000. What is the growth in percent?", (138000 - 120000) / 120000 * 100),
 ("Cost of goods sold is Rs 360000 and average inventory is Rs 60000. What is the inventory turnover?", 360000 / 60000),
 ("Product A is 60% of sales with a 30% margin. Product B is 40% of sales with a 20% margin. What is the overall margin in percent?", 0.6 * 30 + 0.4 * 20),
]
MODELS = {"qwen2.5-7b (boss)": ("http://100.86.188.31:8077/v1", "qwen2.5-7b"),
          "gemma-3-4b (worker)": ("http://100.86.188.31:8090/v1", "gemma-3-4b-it"),
          "gemma-3n-e4b (math)": ("http://100.86.188.31:8092/v1", "gemma-3n-math")}
PROMPT = "Solve step by step, briefly. End with a final line exactly like: ANSWER: <number only>.\n\n"


def ask(base, name, q):
    t = time.time()
    r = requests.post(base + "/chat/completions", json={"model": name, "temperature": 0, "max_tokens": 500,
                      "messages": [{"role": "user", "content": PROMPT + q}]}, timeout=600)
    txt = r.json()["choices"][0]["message"]["content"]
    m = re.findall(r"ANSWER:\s*(?:Rs\.?\s*)?([-\d,\.]+)", txt)
    try:
        v = float(m[-1].replace(",", "").rstrip(".")) if m else None
    except ValueError:
        v = None
    return v, time.time() - t


def run(label):
    base, name = MODELS[label]
    ok, secs = 0, 0.0
    rows = []
    for q, truth in P:
        try:
            v, dt = ask(base, name, q)
        except Exception as e:
            v, dt = None, 0
        good = v is not None and abs(v - truth) <= 0.01 * abs(truth)
        ok += good; secs += dt
        rows.append((good, v, round(truth, 2)))
    return label, ok, secs / len(P), rows


if __name__ == "__main__":
    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(run, MODELS))
    for label, ok, avg, rows in res:
        print(f"{label}: {ok}/{len(P)} correct, {avg:.1f}s per problem")
        print("   misses:", [(r[1], r[2]) for r in rows if not r[0]])
