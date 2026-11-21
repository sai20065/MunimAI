"""
Technical explainer video for SaralcreditAI, written for people who do not know AI.
Animated infographic scenes (HTML, recorded with Playwright) + free neural narration (edge-tts) + ffmpeg.
Nothing here touches the running app; every number on screen comes from the project facts.
Usage: python make_tech.py [preview]   (preview = only screenshots, no recording)
"""
import asyncio, base64, json, re, subprocess, sys, time
from pathlib import Path
import edge_tts, imageio_ffmpeg
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"; OUT.mkdir(exist_ok=True)
AS = HERE / "assets"; AS.mkdir(exist_ok=True)
FF = imageio_ffmpeg.get_ffmpeg_exe()
VOICE = "en-IN-NeerjaNeural"
PREVIEW = len(sys.argv) > 1 and sys.argv[1] == "preview"


def b64(p):
    return "data:image/png;base64," + base64.b64encode((HERE / "deckimg" / p).read_bytes()).decode()


def run(*a):
    r = subprocess.run([FF, "-y", "-loglevel", "error", *map(str, a)], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr[-800:])


def duration(p):
    r = subprocess.run([FF, "-i", str(p)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def arrow():
    return '<div class="arr r" data-at="{a}">&#10132;</div>'


# ---------------------------------------------------------------- scenes
S = []

S.append(dict(id="idea", kick="The idea", title="A helper that listens, reads and prepares", narr=
 "This is how SaralcreditAI works under the hood, explained without jargon. The idea is simple. A small business owner speaks, in Kannada, Hindi or English. The assistant listens, reads their bills, checks the government's rules, and prepares the paperwork a bank needs. The owner always decides.",
 html="""
<div class="row" style="margin-top:60px;gap:40px;align-items:center;justify-content:center">
 <div class="big r" data-at=".30" style="background:#BFE3FF"><div class="em">🗣️</div><b>Owner</b><span>speaks in their own language</span></div>
 <div class="arr r" data-at=".45">➜</div>
 <div class="big r" data-at=".55" style="background:#3FE0A8"><div class="em">🤖</div><b>Assistant</b><span>listens, reads, checks the rules</span></div>
 <div class="arr r" data-at=".70">➜</div>
 <div class="big r" data-at=".78" style="background:#FFD58A"><div class="em">🏦</div><b>Bank file</b><span>ready for the owner to review</span></div>
</div>
<div class="call r" data-at=".90" style="margin-top:70px">Agents prepare. The owner decides.</div>"""))

S.append(dict(id="agentic", kick="Agentic AI", title="A chatbot talks. An agent does the job.", narr=
 "First, what does agentic AI mean? A chatbot only talks. An agent does a job, in steps. It hears the request, decides who should handle it, does the work, checks its own result, and remembers what happened. Think of a small office with a team, instead of one person who just chats.",
 html="""
<div class="row" style="margin-top:34px;gap:36px;align-items:stretch">
 <div class="card r" data-at=".12" style="width:520px;background:#EDEAFB"><div class="em">💬</div><h3>Chatbot</h3><p>Talks. Answers from memory.<br>No tools. No checking.</p></div>
 <div class="card r" data-at=".22" style="flex:1;background:#fff;border:4px solid #3FE0A8"><h3>Agent</h3>
  <div class="row" style="gap:14px;margin-top:16px;align-items:center">
   <div class="chip r" data-at=".35" style="background:#4DB8FF">1 Hear</div><span class="r" data-at=".38">➜</span>
   <div class="chip r" data-at=".48" style="background:#9B7BFF">2 Decide</div><span class="r" data-at=".50">➜</span>
   <div class="chip r" data-at=".60" style="background:#3FE0A8">3 Act</div><span class="r" data-at=".62">➜</span>
   <div class="chip r" data-at=".72" style="background:#FFB547">4 Check</div><span class="r" data-at=".74">➜</span>
   <div class="chip r" data-at=".84" style="background:#FF8FAE">5 Remember</div>
  </div></div>
</div>
<div class="call r" data-at=".92" style="margin-top:56px">Like a small office with a team, not one person chatting.</div>"""))

S.append(dict(id="team", kick="The agents", title="Meet the team", narr=
 "Our office has a team. A receptionist, called the router, reads each message and sends it to the right person. The bookkeeper reads bills. The scheme officer knows government loans. The readiness checker scores how ready your books are. A tax helper drafts GST summaries. A file preparer builds the bank file. And an auditor, called the verifier, checks everything before you see it.",
 html="""
<div class="grid4" style="margin-top:30px">
 <div class="tile r" data-at=".10" style="background:#BFE3FF"><div class="em">🛎️</div><b>Router</b><span>sends each message to the right agent</span></div>
 <div class="tile r" data-at=".24" style="background:#C9F5E3"><div class="em">📒</div><b>Bookkeeper</b><span>reads bills into the ledger</span></div>
 <div class="tile r" data-at=".38" style="background:#FFE3B0"><div class="em">🏛️</div><b>Scheme officer</b><span>knows 11 government schemes</span></div>
 <div class="tile r" data-at=".50" style="background:#E3D9FF"><div class="em">📈</div><b>Readiness check</b><span>scores how ready your books are</span></div>
 <div class="tile r" data-at=".62" style="background:#FFD6E0"><div class="em">🧾</div><b>GST helper</b><span>drafts tax summaries</span></div>
 <div class="tile r" data-at=".72" style="background:#D8F0FF"><div class="em">📁</div><b>File preparer</b><span>builds the bank file</span></div>
 <div class="tile r" data-at=".82" style="background:#3FE0A8;grid-column:span 2"><div class="em">🛡️</div><b>Auditor (verifier)</b><span>checks everything before the owner sees it</span></div>
</div>"""))

S.append(dict(id="bhashini", kick="Languages", title="Bhashini gives it a voice", narr=
 "Most owners speak Kannada or Hindi, not English. Bhashini is the Government of India's free language service. It turns speech into text, translates between languages, and speaks the answer back. So a Kannada voice note becomes a question we can work on, and the reply comes back in Kannada, spoken aloud.",
 html="""
<div class="row" style="margin-top:36px;gap:22px;align-items:stretch;justify-content:center">
 <div class="card r" data-at=".12" style="flex:1;background:#BFE3FF"><div class="em">🎤</div><h3>Speak</h3><p class="kn" style="font-size:34px">ಸಾಲಕ್ಕಾಗಿ ನನ್ನ ಪುಸ್ತಕಗಳು ಎಷ್ಟು ಸಿದ್ಧವಾಗಿವೆ?</p></div>
 <div class="arr r" data-at=".30">➜</div>
 <div class="card r" data-at=".36" style="flex:1;background:#E3D9FF"><div class="em">🔤</div><h3>Text and translate</h3><p>"How ready are my books for a loan?"</p></div>
 <div class="arr r" data-at=".52">➜</div>
 <div class="card r" data-at=".58" style="flex:1;background:#C9F5E3"><div class="em">⚙️</div><h3>Agents work</h3><p>Check the books and the rules</p></div>
 <div class="arr r" data-at=".72">➜</div>
 <div class="card r" data-at=".78" style="flex:1;background:#FFE3B0"><div class="em">🔊</div><h3>Reply aloud</h3><p class="kn" style="font-size:30px">ಕನ್ನಡದಲ್ಲಿ ಉತ್ತರ</p></div>
</div>
<div class="row r" data-at=".92" style="margin-top:50px;gap:16px;justify-content:center"><div class="chip" style="background:#FFB547">English</div><div class="chip" style="background:#4DB8FF">हिन्दी</div><div class="chip kn" style="background:#3FE0A8">ಕನ್ನಡ</div></div>"""))

S.append(dict(id="brains", kick="The two brains", title="Boss model and worker model", narr=
 "Two AI models do the thinking. Qwen is the boss. It has seven billion parameters, which you can picture as seven billion tiny dials, tuned by reading a huge amount of text. It writes answers and explains the rules. Gemma is the worker. It is smaller, and it runs on ordinary computer memory, not the expensive graphics card. It handles the routine job of reading bills. The boss thinks, the worker does the routine. Both are free, open models.",
 html="""
<div class="row" style="margin-top:36px;gap:44px;align-items:stretch">
 <div class="card r" data-at=".16" style="flex:1;background:#E3D9FF;border-top:12px solid #7A5CF0"><div class="em">🧠</div><h3>Qwen · the boss</h3>
  <div class="kv"><b>7 billion</b> dials (parameters)</div><div class="kv"><b>Graphics card</b> (GPU), about 9 GB</div><div class="kv"><b>Does:</b> writes answers, explains rules</div></div>
 <div class="card r" data-at=".52" style="flex:1;background:#C9F5E3;border-top:12px solid #1FBF8A"><div class="em">🛠️</div><h3>Gemma · the worker</h3>
  <div class="kv"><b>4 billion</b> dials (parameters)</div><div class="kv"><b>Ordinary memory</b> (CPU), no GPU</div><div class="kv"><b>Does:</b> reads bills, routine jobs</div></div>
</div>
<div class="call r" data-at=".90" style="margin-top:50px">The boss thinks. The worker does the routine. Both are free and open.</div>"""))

S.append(dict(id="super", kick="The supercomputer", title="Where the models live: Param Shavak", narr=
 "These models are too heavy for a laptop. So they live on Param Shavak, a college supercomputer, which we reach over a private network. It has a powerful graphics card with thirty two gigabytes of memory. It is shared with other labs, so we promised to use at most seventeen. The boss takes about nine. The worker takes none of it. Our app simply sends questions over, and gets answers back.",
 html="""
<div class="row" style="margin-top:36px;gap:30px;align-items:center;justify-content:center">
 <div class="big r" data-at=".10" style="background:#BFE3FF;width:380px"><div class="em">💻</div><b>Our app</b><span>on a laptop</span></div>
 <div class="arr r" data-at=".30" style="font-size:54px">⇄<div style="font-size:24px;color:#5A5890">private network</div></div>
 <div class="big r" data-at=".40" style="background:#E3D9FF;width:520px"><div class="em">🖥️</div><b>Param Shavak</b><span>shared college supercomputer</span></div>
</div>
<div class="r" data-at=".62" style="margin-top:50px">
 <div style="font-size:30px;font-weight:700;margin-bottom:10px">Graphics card memory: 32 GB in total</div>
 <div class="mbar"><div class="seg" style="width:29.4%;background:#7A5CF0">Boss ≈ 9 GB</div><div class="seg" style="width:23.7%;background:#CFC8F5;color:#14143A">spare in our 17 GB</div><div class="seg" style="width:46.9%;background:#E9E5FB;color:#5A5890">other labs</div></div>
 <div style="font-size:26px;color:#3B3B70;margin-top:10px">Our promise: never more than 17 GB. The worker model uses no graphics memory at all.</div>
</div>"""))

S.append(dict(id="rag", kick="Honest answers", title="An open-book exam, with an auditor", narr=
 "How do we stop the AI from making things up? Before answering, it looks up the official rules, like an open book exam. We keep four hundred and ninety two clauses, copied word for word from eleven government schemes. The model may only use the clauses it is shown, and must name them. Then the auditor blocks any answer that cites a clause it was never given. And all arithmetic is done by code, never by the AI. This idea is called retrieval augmented generation, or R A G.",
 html="""
<div class="row" style="margin-top:30px;gap:18px;align-items:stretch">
 <div class="tile r" data-at=".14" style="background:#BFE3FF;flex:1"><div class="em">📚</div><b>1 Look up</b><span>find the best of 492 official clauses</span></div>
 <div class="tile r" data-at=".30" style="background:#C9F5E3;flex:1"><div class="em">📖</div><b>2 Show only these</b><span>the model sees nothing else</span></div>
 <div class="tile r" data-at=".46" style="background:#FFE3B0;flex:1"><div class="em">✍️</div><b>3 Answer and cite</b><span>names the clause numbers</span></div>
 <div class="tile r" data-at=".62" style="background:#FFD6E0;flex:1"><div class="em">🛡️</div><b>4 Audit</b><span>blocks any clause it was never shown</span></div>
</div>
<div class="code r" data-at=".78" style="margin-top:44px">Q  Am I eligible for PMEGP?<br><span style="color:#0B7F58">(Sources: faq.eligibility_conditions_of_beneficiar.2)</span></div>
<div class="call r" data-at=".92" style="margin-top:30px">Numbers come from code, never from the AI.</div>"""))

S.append(dict(id="teach", kick="One model teaches another", title="The AI that practises on AI-made homework", narr=
 "Now the part we like most: one AI teaching another. Gemma invents practice bills, with different shops, items and layouts. Plain Python knows the right answers, because it made up the numbers. Qwen studies these practice sheets, using a light training method called Q Lora. Then it sits an exam on bills it has never seen. It only replaces the old version if it scores strictly higher. Honest result: we trained two new versions, both scored lower than the original at nought point nine seven six, so we rejected them. The system works, and it knows when not to change.",
 html="""
<div class="row" style="margin-top:20px;gap:30px;align-items:stretch">
 <div style="flex:1.15;display:flex;flex-direction:column;gap:12px">
  <div class="step r" data-at=".08" style="background:#C9F5E3"><b>1</b> Gemma invents practice bills</div>
  <div class="step r" data-at=".20" style="background:#BFE3FF"><b>2</b> Python writes the correct answers</div>
  <div class="step r" data-at=".32" style="background:#E3D9FF"><b>3</b> Qwen studies them (QLoRA)</div>
  <div class="step r" data-at=".44" style="background:#FFE3B0"><b>4</b> Exam on bills it has never seen</div>
  <div class="step r" data-at=".56" style="background:#FFD6E0"><b>5</b> Replace the old model only if strictly better</div>
 </div>
 <div class="card r" data-at=".66" style="flex:1;background:#fff">
  <h3 style="font-size:32px">Exam score</h3>
  <div class="bars">
   <div class="bcol"><div class="bv" style="height:244px;background:#3FE0A8">0.976</div><span>Original</span></div>
   <div class="bcol"><div class="bv" style="height:236px;background:#FFB547">0.943</div><span>Try A</span></div>
   <div class="bcol"><div class="bv" style="height:170px;background:#FF5E8A">0.679</div><span>Try B</span></div>
  </div>
  <p style="font-size:26px;margin-top:8px;color:#C8244E;font-weight:700">Both tries rejected. Original kept.</p>
 </div>
</div>"""))

S.append(dict(id="trust", kick="Trust", title="A bank file that proves itself", narr=
 "Banks need to trust what they receive. So every bank file we produce is sealed. Each ledger row is linked to the one before, like links in a chain, and a code on the first page lets the bank check that nothing was edited. And every step the AI takes is saved in a trace, so anyone can replay exactly what happened.",
 html="""
<div class="row" style="margin-top:40px;gap:12px;align-items:center;justify-content:center">
 <div class="link r" data-at=".12">Row 1</div><span class="r" data-at=".16">🔗</span>
 <div class="link r" data-at=".22">Row 2</div><span class="r" data-at=".26">🔗</span>
 <div class="link r" data-at=".32">Row 3</div><span class="r" data-at=".36">🔗</span>
 <div class="link r" data-at=".42">Row 4</div><span class="r" data-at=".46">🔗</span>
 <div class="link r" data-at=".52" style="background:#3FE0A8">Seal + QR</div>
</div>
<div class="row" style="margin-top:50px;gap:36px;align-items:stretch">
 <div class="card r" data-at=".66" style="flex:1;background:#C9F5E3"><div class="em">✅</div><h3>Untouched</h3><p>The bank scans the code and sees the file matches.</p></div>
 <div class="card r" data-at=".78" style="flex:1;background:#FFD6E0"><div class="em">⚠️</div><h3>Edited</h3><p>Change one row and the chain breaks. The check says so.</p></div>
 <div class="card r" data-at=".88" style="flex:1;background:#E3D9FF"><div class="em">🔍</div><h3>Replayable</h3><p>Every AI step is saved in a trace.</p></div>
</div>"""))

S.append(dict(id="future", kick="What comes next", title="Technical plans", narr=
 "What comes next. First, smarter search that understands meaning, so a question about a loan without guarantee finds the collateral free clause, in any language. Second, a follow up agent that waits days for a bank and reminds the owner, built with a tool called LangGraph. Third, WhatsApp, so owners need no new app. Fourth, more schemes and state programmes, and a harder training exam. Then a pilot with one hundred real businesses.",
 html="""
<div class="road" style="margin-top:28px">
 <div class="rstep r" data-at=".10" style="border-color:#4DB8FF"><div class="em">🔎</div><b>Search by meaning</b><span>"loan without guarantee" finds "collateral-free", in any language</span></div>
 <div class="rstep r" data-at=".30" style="border-color:#9B7BFF"><div class="em">⏳</div><b>Follow-up agent</b><span>waits days for a bank, then nudges the owner (LangGraph)</span></div>
 <div class="rstep r" data-at=".50" style="border-color:#3FE0A8"><div class="em">💬</div><b>WhatsApp</b><span>no new app to install</span></div>
 <div class="rstep r" data-at=".68" style="border-color:#FFB547"><div class="em">🏛️</div><b>More schemes</b><span>state programmes and a harder training exam</span></div>
 <div class="rstep r" data-at=".84" style="border-color:#FF5E8A"><div class="em">🏪</div><b>Pilot</b><span>100 real businesses</span></div>
</div>"""))

S.append(dict(id="close", kick="Thank you", title="SaralcreditAI: agents prepare, owners decide", narr=
 "That is SaralcreditAI. A team of small agents, two open models on a supercomputer, the government's language service, and strict checks, so a small business owner can get a fair chance at credit. Scan the codes to see the demos and the code.",
 html=f"""
<div class="row" style="margin-top:34px;gap:60px;justify-content:center;align-items:flex-start">
 <div class="qr r" data-at=".30"><img src="{b64('qr_demo.png')}"><b>Demo video</b></div>
 <div class="qr r" data-at=".50"><img src="{b64('qr_trust.png')}"><b>Trust demo</b></div>
 <div class="qr r" data-at=".70"><img src="{b64('qr_repo.png')}"><b>Code</b></div>
</div>
<div class="call r" data-at=".15" style="margin-top:40px;text-align:center">Agents · two open models · Param Shavak · Bhashini · strict checks</div>"""))

CSS = """
*{box-sizing:border-box;margin:0}
html,body{width:1920px;height:1080px;overflow:hidden;background:#F5F3FF;color:#14143A;font-family:'Segoe UI',Arial,sans-serif}
.kn{font-family:'Nirmala UI','Noto Sans Kannada','Segoe UI',sans-serif}
body{background:linear-gradient(135deg,#ECE7FF,#F5F3FF 55%,#DCEEFF)}
.scene{position:absolute;inset:0;padding:70px 110px 190px;display:none}
.scene.act{display:block}
.kick{font-size:28px;font-weight:700;letter-spacing:5px;text-transform:uppercase;color:#1368B8}
h1{font-size:68px;font-weight:800;letter-spacing:-1px;margin-top:6px;line-height:1.1}
.r{opacity:0;transform:translateY(26px);transition:opacity .6s,transform .6s}
.r.on{opacity:1;transform:none}
.row{display:flex}
.em{font-size:76px;line-height:1.1}
.big{border-radius:30px;padding:34px 30px;width:420px;display:flex;flex-direction:column;align-items:center;text-align:center;gap:8px}
.big b{font-size:44px}.big span{font-size:28px;color:#2c2c5a}
.arr{font-size:64px;color:#6A68A8;text-align:center}
.card{border-radius:28px;padding:30px 34px;display:flex;flex-direction:column;gap:10px}
.card h3{font-size:42px}.card p{font-size:32px;line-height:1.3;color:#2c2c5a}
.chip{font-size:30px;font-weight:700;padding:12px 26px;border-radius:999px;color:#0E0F24}
.call{background:#fff;border:3px solid #7A5CF0;border-radius:22px;padding:24px 34px;font-size:42px;font-weight:700}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:22px}
.tile{border-radius:26px;padding:26px;display:flex;flex-direction:column;gap:6px;min-height:290px}
.tile b{font-size:38px}.tile span{font-size:27px;line-height:1.25;color:#2c2c5a}
.kv{font-size:32px;margin-top:8px}
.mbar{display:flex;height:84px;border-radius:18px;overflow:hidden;font-size:28px;font-weight:700}
.seg{display:flex;align-items:center;justify-content:center;color:#fff;white-space:nowrap}
.code{background:#14143A;color:#F3F1FF;border-radius:22px;padding:26px 34px;font-family:Consolas,monospace;font-size:36px;line-height:1.5}
.step{border-radius:20px;padding:16px 24px;font-size:34px;font-weight:600}
.step b{display:inline-block;width:46px;height:46px;border-radius:50%;background:#14143A;color:#fff;text-align:center;line-height:46px;margin-right:12px;font-size:28px}
.bars{display:flex;gap:26px;align-items:flex-end;height:300px;margin-top:14px;border-bottom:4px solid #14143A}
.bcol{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;flex:1}
.bv{width:100%;border-radius:12px 12px 0 0;display:flex;align-items:flex-start;justify-content:center;padding-top:8px;font-size:32px;font-weight:800;color:#0E0F24}
.bcol span{font-size:26px;margin-top:6px;color:#3B3B70}
.link{background:#BFE3FF;border-radius:18px;padding:26px 28px;font-size:34px;font-weight:700;border:3px solid #1368B8}
.road{display:flex;gap:20px;align-items:stretch}
.rstep{flex:1;background:#fff;border-radius:26px;border-top:14px solid;padding:24px;display:flex;flex-direction:column;gap:8px}
.rstep b{font-size:36px}.rstep span{font-size:26px;line-height:1.25;color:#2c2c5a}
.qr{background:#fff;border-radius:26px;padding:24px;display:flex;flex-direction:column;align-items:center;gap:10px;border:3px solid #CFCBF0}
.qr img{width:300px;height:300px}.qr b{font-size:34px}
#cap{position:absolute;left:110px;right:110px;bottom:46px;height:118px;display:flex;align-items:center;justify-content:center;text-align:center;font-size:38px;line-height:1.25;font-weight:600;color:#fff;background:rgba(20,20,58,.92);border-radius:22px;padding:10px 30px}
#prog{position:absolute;left:0;top:0;height:10px;background:linear-gradient(90deg,#4DB8FF,#9B7BFF,#FF5E8A);width:0}
#brand{position:absolute;right:110px;top:36px;font-size:26px;font-weight:700;color:#5A5890;letter-spacing:2px}
"""

JS = """
const D = %DUR%;  // [{start,dur,cap:[[from,to,text]]}]
const total = D[D.length-1].start + D[D.length-1].dur;
const scenes = [...document.querySelectorAll('.scene')];
function setT(t){
  let i = D.findIndex(d => t >= d.start && t < d.start + d.dur); if (i < 0) i = D.length-1;
  const d = D[i], f = Math.max(0, Math.min(1, (t - d.start) / d.dur));
  scenes.forEach((s,k) => s.classList.toggle('act', k===i));
  scenes[i].querySelectorAll('.r').forEach(e => e.classList.toggle('on', f >= parseFloat(e.dataset.at)));
  const c = d.cap.find(x => f >= x[0] && f < x[1]); document.getElementById('cap').textContent = c ? c[2] : '';
  document.getElementById('cap').style.visibility = c ? 'visible' : 'hidden';
  document.getElementById('prog').style.width = (100*t/total) + '%';
}
scenes.forEach(s=>{s.classList.add('act');const b=s.querySelector('.body');let z=1.2;for(let k=0;k<5;k++){b.style.zoom=z;b.style.width=(1700/z)+'px';const h=b.getBoundingClientRect().height;z=Math.max(0.9,Math.min(1.45,z*640/h));}b.style.zoom=z;b.style.width=(1700/z)+'px';s.classList.remove('act');});
window.setT = setT; window.total = total;
window.startTL = function(){ const t0 = performance.now(); (function f(){ const t=(performance.now()-t0)/1000; setT(t); if(t<total) requestAnimationFrame(f);})(); };
setT(0);
"""


def captions(narr, lead_frac):
    sents = re.split(r"(?<=[.!?])\s+", narr.strip())
    tot = sum(len(s) for s in sents)
    out, acc = [], lead_frac
    span = 1 - lead_frac - 0.04
    for s in sents:
        w = span * len(s) / tot
        out.append([round(acc, 4), round(acc + w, 4), s])
        acc += w
    return out


async def synth(text, path):
    await edge_tts.Communicate(text, VOICE, rate="-4%").save(str(path))


def main():
    # 1. narration
    for s in S:
        p = AS / f"tech_{s['id']}.mp3"
        if not p.exists():
            asyncio.run(synth(s["narr"], p))
        s["mp3"] = p
        s["nd"] = duration(p)
    LEAD, GAP = 0.8, 1.0
    t = 0.0
    D = []
    for k, s in enumerate(S):
        lead = LEAD + (1.0 if k == 0 else 0)
        dur = lead + s["nd"] + GAP
        s["start"], s["lead"], s["dur"] = t, lead, dur
        D.append(dict(start=t, dur=dur, cap=captions(s["narr"], lead / dur)))
        t += dur
    total = t
    print("scenes", len(S), "total %.1fs" % total, "words", sum(len(s["narr"].split()) for s in S))
    # 2. page
    scenes_html = "".join(
        f'<div class="scene"><div class="kick">{k+1} / {len(S)} · {s["kick"]}</div><h1>{s["title"]}</h1><div class="body">{s["html"]}</div></div>'
        for k, s in enumerate(S))
    html = (f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"
            f"<div id='prog'></div><div id='brand'>SaralcreditAI</div>{scenes_html}<div id='cap'></div>"
            f"<script>{JS.replace('%DUR%', json.dumps(D))}</script></body></html>")
    (HERE / "out" / "tech.html").write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        if PREVIEW:
            ctx = b.new_context(viewport={"width": 1920, "height": 1080})
            pg = ctx.new_page(); pg.set_content(html)
            for k, s in enumerate(S):
                pg.evaluate(f"setT({s['start'] + s['dur'] * 0.97})")
                pg.wait_for_timeout(900)
                pg.screenshot(path=str(OUT / f"tech_prev_{k+1:02d}_{s['id']}.png"))
            b.close(); return
        t_ctx = time.time()
        ctx = b.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=str(OUT),
                            record_video_size={"width": 1920, "height": 1080})
        pg = ctx.new_page(); pg.set_content(html); pg.wait_for_timeout(600)
        t_start = time.time(); pg.evaluate("startTL()")
        pg.wait_for_timeout(int((total + 1.5) * 1000))
        vpath = pg.video.path(); ctx.close(); b.close()
    offset = t_start - t_ctx
    print("video offset %.2fs" % offset)
    # 3. audio
    ins, fc = [], []
    for k, s in enumerate(S):
        ins += ["-i", s["mp3"]]
        ms = int((offset + s["start"] + s["lead"]) * 1000)
        fc.append(f"[{k}:a]adelay={ms}|{ms}[a{k}]")
    fc.append("".join(f"[a{k}]" for k in range(len(S))) + f"amix=inputs={len(S)}:normalize=0[aout]")
    run(*ins, "-filter_complex", ";".join(fc), "-map", "[aout]", OUT / "mix_tech.wav")
    final = OUT / "SaralcreditAI-technical-explainer.mp4"
    run("-i", vpath, "-i", OUT / "mix_tech.wav", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-r", "30",
        "-c:a", "aac", "-b:a", "160k", "-t", total + offset + 0.5, final)
    print("done", final, "%.1fs" % duration(final))


if __name__ == "__main__":
    main()
